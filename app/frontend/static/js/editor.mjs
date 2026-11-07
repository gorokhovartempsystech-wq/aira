// Document editor bound to the backend editor actor (createDocxSession via the workspace).
//
// Typing inside one paragraph is applied by the browser immediately and sent as one
// `range_edit` after a short pause. Enter / Shift+Enter / Backspace or Delete across a
// paragraph boundary / multi-line paste / undo / redo / styles are explicit backend commands
// followed by a fresh structural view. The backend stays the source of truth: refused edits
// are reverted to its text. Offsets are Unicode code points on the wire.

import { h, icon, toast, cpLen, cpToU16, sleep } from './ui.mjs';
import { readDocxAssets, createMarkerCounter } from './docx-assets.mjs';

const OBJ = '￼';
const pkey = path => path.join('.');
const NATIVE = new Set(['insertText', 'insertCompositionText', 'insertReplacementText',
  'deleteContentBackward', 'deleteContentForward', 'deleteWordBackward', 'deleteWordForward',
  'deleteSoftLineBackward', 'deleteSoftLineForward', 'deleteHardLineBackward', 'deleteHardLineForward',
  'deleteByCut', 'deleteContent']);
const CARET_COMMANDS = new Set(['enter', 'insert_soft_break', 'join_previous', 'join_next', 'paste']);

export const MSG = {
  refused: 'Эту правку не удалось применить: здесь оформление Word, которое AIRA пока не изменяет. Текст возвращён.',
  multi: 'Изменять сразу несколько абзацев пока нельзя. Выделите текст внутри одного абзаца.',
  object: 'Рисунки и другие объекты Word в AIRA не удаляются и не меняются — они сохраняются в файле.',
  cell: 'В ячейке таблицы можно менять только текст: новые абзацы и объединение здесь недоступны.',
  style: 'Не удалось применить стиль: в этом документе нет такого стиля Word.',
};

/* ---------- Text model helpers ---------- */
function walkUnits(el, cb) {
  for (const n of el.childNodes) {
    if (n.nodeType === Node.TEXT_NODE) cb({ node: n, text: n.data, atomic: false });
    else if (n.nodeType === Node.ELEMENT_NODE) {
      if (n.hasAttribute('data-obj')) cb({ node: n, text: OBJ, atomic: true });
      else if (n.tagName === 'BR') { if (n.hasAttribute('data-soft')) cb({ node: n, text: '\n', atomic: true }); }
      else walkUnits(n, cb);
    }
  }
}
export function textOf(el) { let s = ''; walkUnits(el, u => { s += u.text; }); return s; }

function offsetOf(paraEl, node, offset) {
  const r = document.createRange();
  r.setStart(paraEl, 0);
  try { r.setEnd(node, offset); } catch { return 0; }
  const tmp = document.createElement('div');
  tmp.append(r.cloneContents());
  return cpLen(textOf(tmp));
}

function domPoint(paraEl, cp) {
  let acc = 0, found = null;
  walkUnits(paraEl, u => {
    if (found) return;
    if (!u.atomic) {
      const len = cpLen(u.text);
      if (cp <= acc + len) found = { node: u.node, offset: cpToU16(u.text, cp - acc) };
      acc += len;
    } else {
      if (cp === acc) found = { node: u.node.parentNode, offset: Array.prototype.indexOf.call(u.node.parentNode.childNodes, u.node) };
      acc += 1;
    }
  });
  if (found) return found;
  const last = paraEl.lastChild;
  const end = last && last.nodeName === 'BR' && last.hasAttribute('data-ph') ? paraEl.childNodes.length - 1 : paraEl.childNodes.length;
  return { node: paraEl, offset: end };
}

function textChange(before, after) {
  const a = Array.from(before), b = Array.from(after);
  let start = 0, end = a.length, tail = b.length;
  while (start < end && start < tail && a[start] === b[start]) start++;
  while (end > start && tail > start && a[end - 1] === b[tail - 1]) { end--; tail--; }
  return { start, end, before: a.slice(start, end).join(''), after: b.slice(start, tail).join('') };
}

class LaneError extends Error { constructor(code) { super(code); this.code = code; } }

export class DocEditor {
  constructor({ documentId, workspace, api, isLocked, onChange, onFindingClick }) {
    Object.assign(this, { documentId, workspace, api, isLocked, onChange, onFindingClick });
    this.root = h('div', { class: 'doc', contenteditable: 'true', spellcheck: 'true', lang: 'ru',
      role: 'textbox', 'aria-multiline': 'true', 'aria-label': 'Текст документа' });
    this.paras = [];
    this.byKey = new Map();
    this.dirty = new Set();
    this.chain = Promise.resolve();
    this.queued = 0;
    this.flushTimer = null;
    this.projection = null;
    this.assets = null;
    this.assetsLoading = false;
    this.highlights = { items: [], active: null };
    this.laneError = null;
    this.composing = false;
    this.disposed = false;
    this.bind();
  }

  get client() { return this.workspace.client(this.documentId); }
  get editor() { return this.client.editor; }

  /* ---------- Loading and rendering ---------- */
  async load() {
    await this.reload({ caret: null });
    await this.loadAssets(true);
  }

  async reload({ caret = null } = {}) {
    const snap = this.editor.snapshot();
    const data = await this.api.view(this.documentId, snap.session_id);
    if (this.disposed) return;
    this.apply(data.projection, data.view, caret);
    this.onChange?.('projection');
    if (this.needsAssets()) void this.enqueue(() => this.loadAssets(false)).catch(() => {});
  }

  signature(blocks) {
    const out = [];
    const walk = list => {
      for (const b of list) {
        if (b.kind === 'paragraph') out.push(pkey(b.anchor.path));
        else if (b.kind === 'table') { out.push('t' + pkey(b.anchor.path)); for (const r of b.rows) for (const c of r.cells) walk(c.blocks); }
        else out.push('o' + pkey(b.anchor?.path || []));
      }
    };
    walk(blocks);
    return out.join('|');
  }

  apply(projection, view, caret) {
    const oldSig = this.projection ? this.signature(this.projection.blocks) : null;
    const newSig = this.signature(projection.blocks);
    const focused = this.root.contains(document.activeElement) || document.activeElement === this.root;
    this.projection = projection;
    if (caret === 'server' || oldSig !== newSig) {
      const keep = caret === 'server' ? null : this.selectionInfo();
      this.renderAll();
      this.dirty.clear();
      if (caret === 'server' && view?.selection) this.placeCaret(pkey(view.selection.focus.anchor.path), view.selection.focus.offset);
      else if (keep && focused) this.placeCaret(keep.anchor.entry.key, keep.anchor.offset);
      return;
    }
    // Same structure: refresh data, keep DOM of paragraphs the user is still editing.
    const flat = [];
    const collect = list => { for (const b of list) {
      if (b.kind === 'paragraph') flat.push(b);
      else if (b.kind === 'table') for (const r of b.rows) for (const c of r.cells) collect(c.blocks);
    } };
    collect(projection.blocks);
    const sel = this.selectionInfo();
    for (const b of flat) {
      const entry = this.byKey.get(pkey(b.anchor.path));
      if (!entry) continue;
      const styleChanged = entry.block.style_id !== b.style_id || entry.block.numbering_id !== b.numbering_id
        || entry.block.numbering_level !== b.numbering_level;
      entry.block = b;
      const domText = textOf(entry.el);
      if (styleChanged) {
        this.replaceParagraph(entry);
        if (sel?.anchor.entry === entry) this.placeCaret(entry.key, sel.anchor.offset);
      } else if (domText !== b.text && !this.dirty.has(entry.key)) {
        this.fillParagraph(entry.el, b);
        if (sel?.anchor.entry === entry) this.placeCaret(entry.key, Math.min(sel.anchor.offset, cpLen(b.text)));
      }
    }
    this.updateMarkers();
    this.applyHighlights();
  }

  renderAll() {
    this.paras = [];
    this.byKey = new Map();
    const frag = document.createDocumentFragment();
    this.projection.blocks.forEach((b, i) => frag.append(this.renderBlock(b, i)));
    this.root.replaceChildren(frag);
    this.updateMarkers();
    this.applyHighlights();
  }

  renderBlock(b, topIndex) {
    if (b.kind === 'paragraph') return this.renderParagraph(b, topIndex);
    if (b.kind === 'table') return this.renderTable(b);
    return h('div', { class: 'obj-block', contenteditable: 'false', 'data-obj': '' },
      icon('lock'), 'Элемент Word показан не полностью — он сохраняется в файле без изменений');
  }

  headingLevel(styleId) {
    if (!styleId) return 0;
    const known = { Title: 1, Heading1: 1, Heading2: 2, Heading3: 3 };
    if (known[styleId]) return known[styleId];
    return this.assets?.styles.get(styleId)?.level || 0;
  }

  renderParagraph(b, topIndex) {
    const level = this.headingLevel(b.style_id);
    const el = h(level ? `h${Math.min(level, 3)}` : 'p', { class: 'para', 'data-key': pkey(b.anchor.path) });
    const entry = { key: pkey(b.anchor.path), block: b, el, top: topIndex };
    el._entry = entry;
    this.paras.push(entry);
    this.byKey.set(entry.key, entry);
    this.fillParagraph(el, b);
    return el;
  }

  replaceParagraph(entry) {
    const fresh = this.renderParagraphElement(entry.block);
    fresh._entry = entry;
    entry.el.replaceWith(fresh);
    entry.el = fresh;
  }
  renderParagraphElement(b) {
    const level = this.headingLevel(b.style_id);
    const el = h(level ? `h${Math.min(level, 3)}` : 'p', { class: 'para', 'data-key': pkey(b.anchor.path) });
    this.fillParagraph(el, b);
    return el;
  }

  fillParagraph(el, b) {
    el.replaceChildren();
    const spans = b.spans || [];
    if (!b.text) { el.append(h('br', { 'data-ph': '' })); return; }
    for (const s of spans) {
      if (s.kind === 'text') el.append(s.hyperlink ? h('span', { class: 'hl' }, s.text) : document.createTextNode(s.text));
      else if (s.kind === 'tab') el.append(document.createTextNode(s.text || '\t'));
      else if (s.kind === 'break') el.append(h('br', { 'data-soft': '' }));
      else el.append(this.renderObject(s));
    }
    if (spans.length && spans[spans.length - 1].kind === 'break') el.append(h('br', { 'data-ph': '' }));
  }

  renderObject(span) {
    const info = this.assets?.images.get(pkey(span.anchor.path));
    if (info?.url) {
      return h('span', { class: 'obj img', contenteditable: 'false', 'data-obj': '' },
        h('img', { src: info.url, alt: 'Изображение из документа', style: info.width ? { width: `${info.width}px` } : null, draggable: 'false' }));
    }
    const label = info ? (info.unsupported ? `Изображение ${info.unsupported}` : 'Изображение') : 'Объект Word';
    return h('span', { class: 'obj chip', contenteditable: 'false', 'data-obj': '',
      title: 'Сохраняется в DOCX без изменений' }, icon(info ? 'image' : 'lock'), label);
  }

  renderTable(t) {
    const table = h('table', { class: 'doc-table', 'data-key': 't' + pkey(t.anchor.path) });
    const owners = [];
    for (const row of t.rows) {
      const tr = h('tr');
      let col = 0;
      for (const cell of row.cells) {
        const span = cell.grid_span || 1;
        if (cell.vertical_merge === 'continue' && owners[col]) {
          owners[col].rowSpan += 1;
          col += span;
          continue;
        }
        const td = h('td', { colspan: span > 1 ? span : null });
        for (const b of cell.blocks) td.append(this.renderBlock(b, null));
        if (!cell.blocks.length) td.append(h('br'));
        for (let i = 0; i < span; i++) owners[col + i] = cell.vertical_merge === 'restart' ? td : null;
        tr.append(td);
        col += span;
      }
      table.append(tr);
    }
    return h('div', { class: 'table-wrap' }, table);
  }

  updateMarkers() {
    const next = createMarkerCounter(this.assets?.numbering);
    for (const entry of this.paras) {
      const b = entry.block;
      const m = (b.numbering_id !== null && b.numbering_id !== undefined) || b.style_id === 'ListBullet' || b.style_id === 'ListNumber'
        ? next(b.numbering_id, b.numbering_level, b.style_id) : null;
      entry.marker = m;
      if (m) {
        entry.el.classList.add('li');
        entry.el.dataset.marker = m.text;
        entry.el.style.setProperty('--lvl', String(b.numbering_level || 0));
      } else {
        entry.el.classList.remove('li');
        delete entry.el.dataset.marker;
      }
    }
  }

  /* ---------- DOCX assets (list formats, images, heading styles) ---------- */
  needsAssets() {
    if (!this.projection || this.assetsLoading) return false;
    if (!this.assets) return true;
    for (const e of this.paras) {
      const id = e.block.numbering_id;
      if (id !== null && id !== undefined && !this.assets.numbering.has(String(id))) return true;
      for (const s of e.block.spans || []) if (s.kind === 'opaque' && !this.assets.images.has(pkey(s.anchor.path))) {
        if (!this.assets.missing.has(pkey(s.anchor.path))) return true;
      }
    }
    return false;
  }

  async loadAssets(initial) {
    if (this.assetsLoading || this.disposed) return;
    this.assetsLoading = true;
    try {
      const snap = this.editor.snapshot();
      const bytes = await this.api.workingBytes(this.documentId, snap);
      const assets = await readDocxAssets(bytes);
      assets.missing = new Set();
      for (const e of this.paras) for (const s of e.block.spans || []) {
        if (s.kind === 'opaque' && !assets.images.has(pkey(s.anchor.path))) assets.missing.add(pkey(s.anchor.path));
      }
      this.assets?.revoke();
      this.assets = assets;
      const headingsChanged = this.paras.some(e => e.block.style_id && !['Heading1', 'Heading2', 'Heading3', 'Title'].includes(e.block.style_id) && assets.styles.get(e.block.style_id)?.level);
      if (initial || headingsChanged) {
        const sel = this.selectionInfo();
        this.renderAll();
        if (sel && this.root.contains(document.activeElement)) this.placeCaret(sel.anchor.entry.key, sel.anchor.offset);
      } else {
        for (const e of this.paras) {
          if (!(e.block.spans || []).some(s => s.kind === 'opaque')) continue;
          const objs = Array.from(e.el.querySelectorAll('[data-obj]'));
          const spans = e.block.spans.filter(s => s.kind === 'opaque');
          objs.forEach((node, i) => spans[i] && node.replaceWith(this.renderObject(spans[i])));
        }
        this.updateMarkers();
      }
    } catch {
      // Display-only data. Lists show bullets and objects show placeholders without it.
    } finally {
      this.assetsLoading = false;
    }
  }

  /* ---------- Selection ---------- */
  entryOfNode(node) {
    if (!node || !this.root.contains(node)) return null;
    const el = (node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement)?.closest('[data-key]');
    return el && el._entry && this.root.contains(el) ? el._entry : null;
  }
  pointInfo(node, offset) {
    const entry = this.entryOfNode(node);
    return entry ? { entry, offset: offsetOf(entry.el, node, offset) } : null;
  }
  selectionInfo() {
    const sel = getSelection();
    if (!sel || !sel.rangeCount) return null;
    const a = this.pointInfo(sel.anchorNode, sel.anchorOffset);
    const f = this.pointInfo(sel.focusNode, sel.focusOffset);
    if (!a || !f) return null;
    return { anchor: a, focus: f, collapsed: sel.isCollapsed, multi: a.entry !== f.entry };
  }
  placeCaret(key, offset) {
    const entry = this.byKey.get(key);
    if (!entry) return;
    const p = domPoint(entry.el, offset);
    const sel = getSelection();
    const r = document.createRange();
    r.setStart(p.node, p.offset);
    r.collapse(true);
    sel.removeAllRanges();
    sel.addRange(r);
    if (document.activeElement !== this.root) this.root.focus({ preventScroll: true });
    const rect = r.getBoundingClientRect();
    if (rect && (rect.top < 80 || rect.bottom > window.innerHeight - 40)) entry.el.scrollIntoView({ block: 'nearest' });
  }

  /* ---------- Input ---------- */
  bind() {
    const r = this.root;
    r.addEventListener('beforeinput', e => this.onBeforeInput(e));
    r.addEventListener('input', () => this.onInput());
    r.addEventListener('compositionstart', () => { this.composing = true; });
    r.addEventListener('compositionend', () => { this.composing = false; this.onInput(); });
    r.addEventListener('paste', e => this.onPaste(e));
    r.addEventListener('drop', e => e.preventDefault());
    r.addEventListener('dragstart', e => e.preventDefault());
    r.addEventListener('keydown', e => this.onKey(e));
    r.addEventListener('click', () => this.onClick());
    r.addEventListener('focusout', () => { if (this.dirty.size) this.scheduleFlush(50); });
  }

  canType() {
    if (this.isLocked?.() || this.laneError) return false;
    const s = this.editor.status();
    return s.canEdit || s.busy;
  }

  onBeforeInput(e) {
    const t = e.inputType;
    if (!this.canType()) { if (e.cancelable) e.preventDefault(); this.onChange?.('locked'); return; }
    if (t === 'historyUndo' || t === 'historyRedo') { e.preventDefault(); this.intent(t === 'historyUndo' ? 'undo' : 'redo', null); return; }
    if (t.startsWith('format') || t.startsWith('insertFrom') || t === 'insertLink' || t === 'insertHorizontalRule'
      || t === 'insertOrderedList' || t === 'insertUnorderedList') { e.preventDefault(); return; }
    const sel = this.selectionInfo();
    if (!sel) { e.preventDefault(); return; }
    if (t === 'insertParagraph') {
      e.preventDefault();
      if (sel.multi || !sel.collapsed) { toast(MSG.multi, 'warn'); return; }
      this.intent('enter', sel);
      return;
    }
    if (t === 'insertLineBreak') { e.preventDefault(); if (!sel.multi) this.intent('insert_soft_break', sel); return; }
    if (sel.multi) { e.preventDefault(); toast(MSG.multi, 'warn'); return; }
    if (!NATIVE.has(t)) { e.preventDefault(); return; }

    const text = textOf(sel.anchor.entry.el);
    const lo = Math.min(sel.anchor.offset, sel.focus.offset), hi = Math.max(sel.anchor.offset, sel.focus.offset);
    if (!sel.collapsed && Array.from(text).slice(lo, hi).join('').includes(OBJ)) { e.preventDefault(); toast(MSG.object, 'warn'); return; }

    if (t.startsWith('delete')) {
      const backward = t.endsWith('Backward');
      const atStart = sel.collapsed && sel.anchor.offset === 0;
      const atEnd = sel.collapsed && sel.anchor.offset === cpLen(text);
      const ranges = e.getTargetRanges ? e.getTargetRanges() : [];
      let crosses = false, touchesObject = false;
      for (const r of ranges) {
        const s = this.pointInfo(r.startContainer, r.startOffset), en = this.pointInfo(r.endContainer, r.endOffset);
        if (!s || !en || s.entry !== en.entry) { crosses = true; continue; }
        if (Array.from(textOf(s.entry.el)).slice(Math.min(s.offset, en.offset), Math.max(s.offset, en.offset)).join('').includes(OBJ)) touchesObject = true;
      }
      if (crosses || (!ranges.length && ((backward && atStart) || (!backward && atEnd)))) {
        e.preventDefault();
        if (backward && atStart) this.intent('join_previous', sel);
        else if (!backward && atEnd) this.intent('join_next', sel);
        else toast(MSG.multi, 'warn');
        return;
      }
      if (touchesObject) { e.preventDefault(); toast(MSG.object, 'warn'); }
    }
  }

  onInput() {
    const sel = this.selectionInfo();
    if (sel) this.dirty.add(sel.anchor.entry.key);
    else for (const e of this.paras) if (textOf(e.el) !== e.block.text) this.dirty.add(e.key);
    this.scheduleFlush(600);
    this.onChange?.('local');
  }

  onPaste(e) {
    e.preventDefault();
    if (!this.canType()) return;
    const text = (e.clipboardData?.getData('text/plain') || '').replace(/\r\n?/g, '\n');
    if (!text) return;
    const sel = this.selectionInfo();
    if (!sel) return;
    if (sel.multi) { toast(MSG.multi, 'warn'); return; }
    if (!/[\n\t]/.test(text)) { document.execCommand('insertText', false, text); return; }
    this.intent('paste', sel, text.replace(/\t/g, ' '));
  }

  onKey(e) {
    const mod = e.ctrlKey || e.metaKey;
    if (e.key === 'Tab') { e.preventDefault(); return; }
    if (mod && !e.altKey && (e.code === 'KeyZ' || e.code === 'KeyY')) {
      e.preventDefault();
      if (!this.canType()) return;
      this.intent(e.code === 'KeyY' || e.shiftKey ? 'redo' : 'undo', null);
      return;
    }
    if (mod && ['KeyB', 'KeyI', 'KeyU'].includes(e.code)) e.preventDefault();
  }

  onClick() {
    const sel = getSelection();
    if (!sel?.isCollapsed || !sel.rangeCount) return;
    const id = this.findingAt(sel.anchorNode, sel.anchorOffset);
    if (id) this.onFindingClick?.(id);
  }

  /* ---------- Command lane ---------- */
  enqueue(fn) {
    this.queued++;
    this.onChange?.('queue');
    const p = this.chain.then(fn).finally(() => { this.queued--; this.onChange?.('queue'); });
    this.chain = p.catch(() => {});
    return p;
  }

  scheduleFlush(ms) {
    clearTimeout(this.flushTimer);
    this.flushTimer = setTimeout(() => { this.flushTimer = null; void this.enqueue(() => this.flushAndSync()).catch(() => {}); }, ms);
  }

  async waitReady() {
    for (;;) {
      if (this.disposed) throw new LaneError('inactive');
      const s = this.editor.status();
      const a = this.client.analysis.status().phase;
      if (a === 'admission_uncertain' || a === 'save_uncertain') throw new LaneError('analysis_pending');
      if (s.canEdit && !s.busy && !['saving', 'admitting'].includes(a)) return;
      if (!s.busy && !s.canEdit) throw new LaneError(s.phase);
      await sleep(60);
    }
  }

  async flushAndSync() {
    try {
      if (await this.flush()) await this.reload();
    } catch (e) { await this.failure(e); }
  }

  // Sends local paragraph text to the backend. Returns true when something was sent.
  async flush() {
    clearTimeout(this.flushTimer);
    this.flushTimer = null;
    if (!this.dirty.size || !this.projection) return false;
    if (this.composing) { this.scheduleFlush(300); return false; }
    await this.waitReady();
    const edits = [], empties = [], sent = new Map();
    for (const key of [...this.dirty]) {
      const entry = this.byKey.get(key);
      if (!entry || !entry.el.isConnected) { this.dirty.delete(key); continue; }
      const now = textOf(entry.el), before = entry.block.text;
      if (now === before) { this.dirty.delete(key); continue; }
      const c = textChange(before, now);
      if (c.before.includes(OBJ) || c.after.includes(OBJ) || /[\t\n\r]/.test(c.after)) {
        this.revertParagraph(entry); toast(MSG.object, 'warn'); continue;
      }
      if (!before) { empties.push({ entry, text: now }); sent.set(key, now); continue; }
      try { edits.push(this.rangeEdit(entry, c)); sent.set(key, now); }
      catch { this.revertParagraph(entry); toast(MSG.refused, 'warn'); }
    }
    if (!edits.length && !empties.length) return false;
    if (edits.length) await this.editor.edit({ action: 'range_edit', value: edits, after: this.afterTarget(sent) });
    for (const item of empties) {
      await this.capture(item.entry, 0, 0);
      await this.editor.edit({ action: 'insert_text', value: item.text });
    }
    for (const [key, text] of sent) {
      const entry = this.byKey.get(key);
      if (entry && textOf(entry.el) === text) this.dirty.delete(key);
    }
    return true;
  }

  rangeEdit(entry, c) {
    const spans = (entry.block.spans || []).filter(s => s.kind === 'text');
    const position = offset => {
      const span = spans.find(s => s.start <= offset && offset < s.end) || spans.find(s => s.end === offset);
      if (!span) throw new Error('no_span');
      return { anchor: span.anchor, offset: offset - span.start };
    };
    return { start: position(c.start), end: position(c.end), expected_text: c.before, replacement_text: c.after };
  }

  afterTarget(sent) {
    const sel = this.selectionInfo();
    let index = this.projection.blocks.findIndex(b => b.kind === 'paragraph');
    let offset = 0;
    if (sel && sel.anchor.entry.top !== null) {
      const e = sel.anchor.entry;
      const serverText = sent.get(e.key) ?? e.block.text;
      if (textOf(e.el) === serverText) { index = e.top; offset = Math.min(sel.anchor.offset, cpLen(serverText)); }
    }
    const point = { block_index: index, offset, affinity: 'left' };
    return { anchor: point, focus: point };
  }

  async capture(entry, a, f) {
    const snap = this.editor.snapshot();
    const anchor = { source_sha256: snap.document.source_sha256, part_name: snap.document.main_part, path: entry.block.anchor.path };
    await this.editor.edit({ action: 'capture', value: {
      anchor: { anchor, offset: a, affinity: 'right' }, focus: { anchor, offset: f, affinity: 'right' } } });
  }

  intent(kind, sel, text) {
    clearTimeout(this.flushTimer);
    const point = sel ? { key: sel.anchor.entry.key, a: sel.anchor.offset, f: sel.focus.offset, cell: sel.anchor.entry.top === null } : null;
    return this.enqueue(async () => {
      try {
        await this.flush();
        if (CARET_COMMANDS.has(kind)) {
          const entry = point && this.byKey.get(point.key);
          if (!entry) return;
          await this.waitReady();
          await this.capture(entry, point.a, point.f);
        }
        await this.waitReady();
        await this.editor.edit(kind === 'paste' ? { action: 'paste_text', value: text } : { action: kind });
        await this.reload({ caret: 'server' });
      } catch (e) {
        await this.failure(e, point?.cell && kind !== 'undo' && kind !== 'redo' ? MSG.cell : MSG.refused);
      }
    });
  }

  async failure(e, refusedMessage = MSG.refused) {
    if (e?.code === 'request_rejected') {
      toast(refusedMessage, 'warn');
      try { await this.reload(); } catch { /* shown via status */ }
      return;
    }
    if (e?.code === 'analysis_pending') { this.onChange?.('lane'); return; }
    this.laneError = e?.code || 'request_failed';
    this.root.setAttribute('contenteditable', 'false');
    this.onChange?.('lane');
  }

  revertParagraph(entry) {
    this.fillParagraph(entry.el, entry.block);
    this.dirty.delete(entry.key);
  }

  // After an unknown outcome: repeat exactly the same request, then resync.
  retryLane() {
    return this.enqueue(async () => {
      try {
        if (this.editor.status().canRetry) await this.editor.retry();
        this.laneError = null;
        this.root.setAttribute('contenteditable', 'true');
        await this.reload();
        if (this.dirty.size) this.scheduleFlush(50);
      } catch (e) { await this.failure(e); }
      this.onChange?.('lane');
    });
  }

  flushAll() {
    clearTimeout(this.flushTimer);
    return this.enqueue(() => this.flushAndSync());
  }

  get localPending() { return this.dirty.size > 0 || this.queued > 0 || this.composing; }

  isEmpty() {
    return !this.paras.some(e => (textOf(e.el) || e.block.text).replace(OBJ, '').trim());
  }

  /* ---------- Paragraph styles and lists ---------- */
  selectedEntries() {
    const sel = this.selectionInfo();
    if (!sel) return [];
    const i = this.paras.indexOf(sel.anchor.entry), j = this.paras.indexOf(sel.focus.entry);
    return this.paras.slice(Math.min(i, j), Math.max(i, j) + 1);
  }

  currentBlock() {
    const sel = this.selectionInfo();
    if (!sel) return null;
    const e = sel.anchor.entry;
    return { level: this.headingLevel(e.block.style_id), list: e.marker?.kind || null, cell: e.top === null };
  }

  headingStyleId(level) {
    if (!level) return null;
    const own = ['Heading1', 'Heading2', 'Heading3'][level - 1];
    if (!this.assets || this.assets.styles.has(own)) return own;
    for (const [id, s] of this.assets.styles) if (s.level === level) return id;
    return own;
  }

  setStyle(level) { return this.format(entries => entries.map(e => ({
    entry: e, style_id: this.headingStyleId(level),
    list_kind: level ? 'none' : (e.marker ? (e.marker.kind === 'number' ? 'numbered' : 'bullet') : 'none'),
    list_id: level || !e.marker || e.block.numbering_id === null ? null : String(e.block.numbering_id),
  }))); }

  toggleList(kind) {
    return this.format(entries => {
      const target = kind === 'numbered' ? 'number' : 'bullet';
      const all = entries.every(e => e.marker?.kind === target);
      const prev = this.paras[this.paras.indexOf(entries[0]) - 1];
      const cont = !all && prev?.marker?.kind === target && prev.block.numbering_id !== null ? String(prev.block.numbering_id) : null;
      return entries.map(e => ({
        entry: e,
        style_id: this.headingLevel(e.block.style_id) ? null : e.block.style_id,
        list_kind: all ? 'none' : kind,
        list_id: all ? null : (e.marker?.kind === target && e.block.numbering_id !== null ? String(e.block.numbering_id) : cont),
      }));
    });
  }

  format(plan) {
    const sel = this.selectionInfo();
    const entries = this.selectedEntries();
    if (!entries.length) { toast('Поставьте курсор в абзац, который нужно оформить.', 'info'); return Promise.resolve(); }
    const keep = sel ? { key: sel.anchor.entry.key, offset: sel.anchor.offset } : null;
    return this.enqueue(async () => {
      try {
        if (await this.flush()) await this.reload();
        await this.waitReady();
        const fresh = entries.map(e => this.byKey.get(e.key)).filter(Boolean);
        if (!fresh.length) return;
        const snap = this.editor.snapshot();
        const value = plan(fresh).map(p => ({
          anchor: { ...p.entry.block.anchor, source_sha256: snap.document.source_sha256 },
          expected_text: p.entry.block.text, style_id: p.style_id, list_kind: p.list_kind, list_id: p.list_id,
        }));
        await this.editor.edit({ action: 'format', value });
        await this.reload();
        if (keep) this.placeCaret(keep.key, keep.offset);
      } catch (e) { await this.failure(e, MSG.style); }
    });
  }

  undo() { return this.intent('undo', null); }
  redo() { return this.intent('redo', null); }

  /* ---------- Finding highlights ---------- */
  setHighlights(items, active) {
    this.highlights = { items, active };
    this.applyHighlights();
  }
  rangeFor(r) {
    const entry = this.byKey.get(r.key);
    if (!entry) return null;
    const a = domPoint(entry.el, r.start), b = domPoint(entry.el, r.end);
    const range = new Range();
    try { range.setStart(a.node, a.offset); range.setEnd(b.node, b.offset); } catch { return null; }
    return range;
  }
  applyHighlights() {
    if (!window.CSS?.highlights || typeof Highlight === 'undefined') return;
    for (const t of ['formulation', 'duplicate', 'contradiction', 'active']) CSS.highlights.delete(`aira-${t}`);
    if (!this.root.isConnected) return;
    const groups = {};
    for (const item of this.highlights.items) {
      for (const r of item.ranges) {
        const range = this.rangeFor(r);
        if (!range) continue;
        (groups[item.type] ||= []).push(range);
        if (item.id === this.highlights.active) (groups.active ||= []).push(range);
      }
    }
    for (const [type, ranges] of Object.entries(groups)) {
      const hl = new Highlight(...ranges);
      if (type === 'active') hl.priority = 10;
      CSS.highlights.set(`aira-${type}`, hl);
    }
  }
  findingAt(node, offset) {
    for (const item of this.highlights.items) for (const r of item.ranges) {
      const range = this.rangeFor(r);
      try { if (range && range.isPointInRange(node, offset)) return item.id; } catch { /* other tree */ }
    }
    return null;
  }
  scrollToFinding(id) {
    const item = this.highlights.items.find(x => x.id === id);
    const first = item?.ranges.find(r => this.byKey.has(r.key));
    if (!first) return false;
    const el = this.byKey.get(first.key).el;
    el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash');
    return true;
  }

  // Maps review evidence (offsets relative to Word text nodes) to paragraph offsets.
  evidenceRanges(evidence) {
    const out = [];
    for (const s of evidence?.slices || []) {
      if (s.paragraph_anchor.source_sha256 !== this.projection?.source_sha256) continue;
      const entry = this.byKey.get(pkey(s.paragraph_anchor.path));
      if (!entry) continue;
      const span = (entry.block.spans || []).find(x => pkey(x.anchor.path) === pkey(s.anchor.path));
      if (!span) continue;
      out.push({ key: entry.key, start: span.start + s.start, end: span.start + s.end });
    }
    return out;
  }

  dispose() {
    this.disposed = true;
    clearTimeout(this.flushTimer);
    this.assets?.revoke();
    this.root.remove();
  }
}
