// Read-only helpers over DOCX bytes: list marker formats and images for display.
// The backend projection gives list ids and opaque spans, but not marker formats or pictures.

const W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main';
const R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships';
const A = 'http://schemas.openxmlformats.org/drawingml/2006/main';
const WP = 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing';
const V = 'urn:schemas-microsoft-com:vml';
const M = 'http://schemas.openxmlformats.org/officeDocument/2006/math';

// Элементы Word, из-за которых бэкенд не принимает проверку (not_admitted, unsupported_analysis_content).
// Проверено на бэкенде main от 5 ноября 2026; современные надписи (wps) и исправления проверку не блокируют.
export const BLOCKERS = [
  { ns: W, tag: 'softHyphen', label: 'мягкие переносы', fix: 'Ctrl+H → «Больше» → «Специальный» → «Мягкий перенос» (^-), заменить на пустое' },
  { ns: W, tag: 'noBreakHyphen', label: 'неразрывные дефисы', fix: 'Ctrl+H → найти ^~ и заменить на обычный дефис' },
  { ns: W, tag: 'sym', label: 'символы из «Вставка → Символ»', fix: 'заменить обычными знаками или удалить' },
  { ns: W, tag: 'ptab', label: 'позиционные табуляции', fix: 'заменить обычной табуляцией' },
  { ns: M, tag: 'oMath', label: 'формулы', fix: 'записать обычным текстом' },
  { ns: V, tag: 'textbox', label: 'надписи старого формата', fix: 'перенести текст из надписи в обычный абзац' },
];
const STYLE_NAMES = { title: 'Название', subtitle: 'Подзаголовок', normal: 'Обычный', header: 'Верхний колонтитул', footer: 'Нижний колонтитул' };
// Свойства стилей абзацев, на которых проверка тоже отказывает (найдено на шаблоне Word для Mac):
// рамка абзаца (pBdr, как у стиля «Название») и нумерация без списка (numPr без numId, как у «Подзаголовка»).
function styleBlockers(doc, styles) {
  if (!doc || !styles) return [];
  const byId = new Map(Array.from(styles.getElementsByTagNameNS(W, 'style')).map(s => [s.getAttributeNS(W, 'styleId'), s]));
  const used = new Map();
  for (const p of Array.from(doc.getElementsByTagNameNS(W, 'p'))) {
    const ps = kids(p, W, 'pStyle')[0];
    const id = ps ? ps.getAttributeNS(W, 'val') : null;
    if (id) used.set(id, (used.get(id) || 0) + 1);
  }
  const out = [];
  for (const [id, count] of used) {
    let border = false, badList = false;
    for (let s = byId.get(id), guard = 0; s && guard < 20; guard++) {
      const ppr = Array.from(s.children).find(c => c.localName === 'pPr');
      if (ppr && ppr.getElementsByTagNameNS(W, 'pBdr').length) border = true;
      const num = ppr && ppr.getElementsByTagNameNS(W, 'numPr')[0];
      if (num && !num.getElementsByTagNameNS(W, 'numId').length) badList = true;
      const base = Array.from(s.children).find(c => c.localName === 'basedOn');
      s = base ? byId.get(base.getAttributeNS(W, 'val')) : null;
    }
    const raw = byId.get(id)?.getElementsByTagNameNS(W, 'name')[0]?.getAttributeNS(W, 'val') || id;
    const name = `«${STYLE_NAMES[raw.toLowerCase()] || raw}»`;
    if (border) out.push({ tag: `pBdr:${id}`, count, label: `рамка абзаца в стиле ${name}`,
      fix: `выделите эти абзацы → «Главная» → «Границы» → «Нет границы» или примените к ним другой стиль` });
    if (badList) out.push({ tag: `numPr:${id}`, count, label: `незавершённая нумерация в стиле ${name}`,
      fix: 'примените к этим абзацам другой стиль, например «Обычный» или «Заголовок 2»' });
  }
  return out;
}
const findBlockers = (doc, styles) => [
  ...BLOCKERS.map(b => ({ ...b, count: doc.getElementsByTagNameNS(b.ns, b.tag).length })).filter(b => b.count),
  ...styleBlockers(doc, styles),
];
const MIME = { png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif', bmp: 'image/bmp',
  webp: 'image/webp', svg: 'image/svg+xml' };
const dec = new TextDecoder();

async function unzip(bytes) {
  const buf = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
  const dv = new DataView(buf), u8 = new Uint8Array(buf);
  let eocd = -1;
  for (let i = u8.length - 22; i >= Math.max(0, u8.length - 65557); i--) {
    if (dv.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
  }
  if (eocd < 0) throw new Error('not_zip');
  const count = dv.getUint16(eocd + 10, true);
  let p = dv.getUint32(eocd + 16, true);
  const files = {};
  for (let k = 0; k < count && dv.getUint32(p, true) === 0x02014b50; k++) {
    const nlen = dv.getUint16(p + 28, true);
    files[dec.decode(u8.subarray(p + 46, p + 46 + nlen))] = {
      method: dv.getUint16(p + 10, true), size: dv.getUint32(p + 20, true), at: dv.getUint32(p + 42, true) };
    p += 46 + nlen + dv.getUint16(p + 30, true) + dv.getUint16(p + 32, true);
  }
  return async name => {
    const f = files[name];
    if (!f) return null;
    const start = f.at + 30 + dv.getUint16(f.at + 26, true) + dv.getUint16(f.at + 28, true);
    const data = u8.subarray(start, start + f.size);
    if (f.method === 0) return data;
    if (f.method !== 8) return null;
    const stream = new Blob([data]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
    return new Uint8Array(await new Response(stream).arrayBuffer());
  };
}

const xml = bytes => bytes ? new DOMParser().parseFromString(dec.decode(bytes), 'application/xml') : null;
const wa = (el, n) => el?.getAttributeNS(W, n) ?? el?.getAttribute('w:' + n) ?? null;
const kids = (el, ns, n) => el ? Array.from(el.getElementsByTagNameNS(ns, n)) : [];

function readNumbering(doc) {
  const out = new Map();
  if (!doc) return out;
  const abstract = new Map();
  for (const a of kids(doc, W, 'abstractNum')) {
    const levels = {};
    for (const lvl of kids(a, W, 'lvl')) {
      levels[wa(lvl, 'ilvl')] = {
        fmt: wa(kids(lvl, W, 'numFmt')[0], 'val') || 'decimal',
        text: wa(kids(lvl, W, 'lvlText')[0], 'val') ?? '%1.',
        start: Number(wa(kids(lvl, W, 'start')[0], 'val') || 1),
      };
    }
    abstract.set(wa(a, 'abstractNumId'), levels);
  }
  for (const n of kids(doc, W, 'num')) {
    const levels = abstract.get(wa(kids(n, W, 'abstractNumId')[0], 'val'));
    if (levels) out.set(String(wa(n, 'numId')), levels);
  }
  return out;
}

// styleId → {name, level}; level 1..3 for headings ("heading 1", "Заголовок 1", outline level).
function readStyles(doc) {
  const out = new Map();
  for (const st of kids(doc, W, 'style')) {
    if (wa(st, 'type') !== 'paragraph') continue;
    const name = wa(kids(st, W, 'name')[0], 'val') || '';
    const outline = kids(st, W, 'outlineLvl')[0];
    let level = 0;
    const m = /^(?:heading|заголовок)\s*(\d)$/i.exec(name.trim());
    if (m) level = Number(m[1]);
    else if (/^title$/i.test(name)) level = 1;
    else if (outline) level = Number(wa(outline, 'val')) + 1;
    out.set(wa(st, 'styleId'), { name, level: level >= 1 && level <= 9 ? level : 0 });
  }
  return out;
}

export async function readDocxAssets(bytes) {
  const get = await unzip(bytes);
  const numbering = readNumbering(xml(await get('word/numbering.xml')));
  const stylesXml = xml(await get('word/styles.xml'));
  const styles = readStyles(stylesXml);
  const images = new Map();
  const urls = [];
  const doc = xml(await get('word/document.xml'));
  const rels = xml(await get('word/_rels/document.xml.rels'));
  const targets = new Map();
  for (const r of rels ? Array.from(rels.getElementsByTagName('Relationship')) : []) {
    targets.set(r.getAttribute('Id'), r.getAttribute('Target'));
  }
  if (doc) {
    // Paths follow the backend anchors: element-child indices starting at the document root.
    const walk = async (el, path) => {
      const name = el.localName;
      if ((name === 'drawing' || name === 'pict') && el.namespaceURI === W) {
        const blip = kids(el, A, 'blip')[0];
        const rid = blip ? blip.getAttributeNS(R, 'embed') : kids(el, V, 'imagedata')[0]?.getAttributeNS(R, 'id');
        const extent = kids(el, WP, 'extent')[0];
        const info = { width: extent ? Math.round(Number(extent.getAttribute('cx')) / 9525) : null };
        const target = rid && targets.get(rid);
        if (target && !/^https?:/i.test(target)) {
          const part = target.startsWith('/') ? target.slice(1) : 'word/' + target.replace(/^\.\//, '');
          const ext = part.split('.').pop().toLowerCase();
          const data = MIME[ext] ? await get(part) : null;
          if (data) {
            info.url = URL.createObjectURL(new Blob([data], { type: MIME[ext] }));
            urls.push(info.url);
          } else info.unsupported = ext.toUpperCase();
        }
        images.set(path.join('.'), info);
        return;
      }
      let i = 0;
      for (const child of Array.from(el.children)) await walk(child, [...path, i++]);
    };
    let i = 0;
    for (const child of Array.from(doc.documentElement.children)) await walk(child, [i++]);
  }
  return { numbering, styles, images, blockers: doc ? findBlockers(doc, stylesXml) : [], revoke() { urls.forEach(u => URL.revokeObjectURL(u)); } };
}

// Marker text for a list paragraph: bullet or computed number ("1.", "2.1." …).
export function createMarkerCounter(numbering) {
  const counters = new Map();
  return (numId, level, styleId) => {
    if (numId === null || numId === undefined) {
      if (styleId === 'ListBullet') return { kind: 'bullet', text: '•' };
      if (styleId === 'ListNumber') numId = 'style:ListNumber', level = 0;
      else return null;
    }
    const lv = Number(level || 0);
    const def = numbering?.get(String(numId))?.[String(lv)] || (String(numId).startsWith('style:') ? { fmt: 'decimal', text: '%1.', start: 1 } : null);
    if (!def) return { kind: 'bullet', text: '•' };
    const c = counters.get(String(numId)) || [];
    c[lv] = (c[lv] ?? (def.start - 1)) + 1;
    c.length = lv + 1;
    counters.set(String(numId), c);
    if (def.fmt === 'bullet' || def.fmt === 'none') return { kind: 'bullet', text: def.fmt === 'none' ? '' : '•' };
    const text = def.text.replace(/%(\d)/g, (_, d) => {
      const v = c[Number(d) - 1] ?? 1;
      return def.fmt === 'lowerLetter' ? String.fromCharCode(96 + ((v - 1) % 26) + 1)
        : def.fmt === 'upperLetter' ? String.fromCharCode(64 + ((v - 1) % 26) + 1)
        : def.fmt === 'lowerRoman' ? roman(v).toLowerCase() : def.fmt === 'upperRoman' ? roman(v) : String(v);
    });
    return { kind: 'number', text };
  };
}
function roman(n) {
  const t = [[1000, 'M'], [900, 'CM'], [500, 'D'], [400, 'CD'], [100, 'C'], [90, 'XC'], [50, 'L'], [40, 'XL'], [10, 'X'], [9, 'IX'], [5, 'V'], [4, 'IV'], [1, 'I']];
  let s = '';
  for (const [v, r] of t) while (n >= v) { s += r; n -= v; }
  return s;
}
