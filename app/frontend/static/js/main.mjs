import { createConnectedWorkspace } from '../../client/document-workspace.mjs';
import { createConnectedImporter } from '../../client/docx-files.mjs';
import { $, h, icon, toast, modal, overlay, fmtTime, sleep } from './ui.mjs';
import { connectHost } from './host.mjs';
import { createApi } from './api.mjs';
import { DocEditor, MSG } from './editor.mjs';
import { createReviewPanel, blockersNode } from './review.mjs';
import { buildExampleDocx, EXAMPLE_TITLE } from './example-docx.mjs';
import { meerkat, mascotAlert, sound, oyoy } from './mascot.mjs';
import { runTour, tourActive } from './tour.mjs';

const MAX_DOCX = 32 * 1024 * 1024;
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* optional preference */ } },
};

const app = {
  host: null, api: null, workspace: null, importer: null,
  docs: [], editors: new Map(), activeId: null, opening: null,
  examples: new Set(store.get('aira.examples', [])),
  // Бэкенд не удаляет документы: «Убрать из списка» скрывает их только в этом списке на этом компьютере.
  hiddenDocs: new Set(store.get('aira.hiddenDocs', [])), showHidden: false,
  licence: null, licenceLocked: false,
  sidebar: store.get('aira.sidebar', true), drawer: store.get('aira.drawer', true), zoom: store.get('aira.zoom', 100),
  render: () => scheduleRender(),
  setDrawer(open) { app.drawer = open; store.set('aira.drawer', open); scheduleRender(); },
};
// prepareToClose: shell shutdown handshake. activeEditor: used by dev smoke tests.
window.AIRA = { prepareToClose, activeEditor: () => app.editors.get(app.activeId) || null };

/* =========================================================
   Boot and licence (F03)
   ========================================================= */
async function boot() {
  try {
    app.host = await connectHost();
    if (!app.host.native) window.AIRA.debug = app; // dev stand only
  } catch {
    return fatal('Не удалось подключиться к локальному серверу AIRA', 'Перезапустите приложение. Если ошибка повторяется — переустановите его.');
  }
  app.api = createApi(app.host);
  const ok = await licenceGate();
  if (!ok) return;
  const conn = { origin: app.host.origin, sessionToken: app.host.sessionToken };
  app.workspace = createConnectedWorkspace({ ...conn, onState: () => onWorkspaceState() });
  app.importer = createConnectedImporter({ ...conn, onState: () => scheduleRender() });
  app.host.onCloseRequest(prepareToClose);
  // В окне приложения закрытие обрабатывает onCloseRequest (prepareToClose); в браузере — предупреждение вкладки.
  if (!app.host.native) window.addEventListener('beforeunload', e => {
    if (anyUnconfirmed()) { e.preventDefault(); e.returnValue = ''; for (const ed of app.editors.values()) void ed.flushAll(); }
  });
  setInterval(checkLicenceQuietly, 60000);
  setInterval(() => review.render(), 1000);
  $('#licence').hidden = true;
  $('#app').hidden = false;
  applyZoom();
  await refreshDocs();
  showStart();
  if (!store.get(TOURS.start, false)) setTimeout(() => startTour('start'), 500);
}

function fatal(title, text) {
  $('#licence').hidden = false;
  $('#licence').replaceChildren(h('div', { class: 'gate' }, meerkat({ mood: 'surprised', size: 84 }),
    h('h1', {}, title), h('p', { class: 'muted' }, text),
    h('button', { class: 'btn primary', onclick: () => location.reload() }, 'Повторить')));
}

const LICENCE_ERRORS = {
  network_unavailable: 'Нет подключения к интернету. AIRA проверяет лицензию при каждом запуске.',
  invalid_license: 'Ключ не найден. Проверьте, что он введён без ошибок.',
  invalid_key: 'Ключ не найден. Проверьте, что он введён без ошибок.',
  device_mismatch: 'Этот ключ уже активирован на другом компьютере. Одна лицензия — одно устройство.',
  device_limit: 'Этот ключ уже активирован на другом компьютере. Одна лицензия — одно устройство.',
  license_disabled: 'Лицензия отключена. Обратитесь к тому, кто выдал ключ.',
  license_expired: 'Срок действия лицензии закончился.',
  verification_timeout: 'Сервер лицензий не ответил вовремя. Попробуйте ещё раз.',
  activation_store_error: 'Не удалось прочитать сохранённую активацию на этом компьютере.',
  device_unavailable: 'Не удалось определить устройство для привязки лицензии.',
  clock_unavailable: 'Не удалось проверить системное время.',
};

async function licenceGate() {
  const screen = $('#licence');
  screen.hidden = false;
  let snap;
  try { snap = await app.api.licence(); } catch { fatal('Не удалось проверить лицензию', 'Локальный сервер AIRA не отвечает.'); return false; }
  if (snap === null) return true; // stand without the licence wrapper
  return new Promise(resolve => {
    let error = null;
    const draw = () => {
      const s = snap;
      app.licence = s;
      if (s.phase === 'active') { resolve(true); return; }
      const checking = s.phase === 'checking' || s.phase === 'new';
      const needKey = ['activation_required', 'failed', 'expired'].includes(s.phase);
      const code = s.phase === 'expired' ? 'license_expired' : s.error_code;
      const input = h('input', { class: 'input key', placeholder: 'Лицензионный ключ', autocomplete: 'off', spellcheck: 'false', 'aria-label': 'Лицензионный ключ' });
      const message = error || (code ? LICENCE_ERRORS[code] || `Не удалось проверить лицензию (${code}).` : null);
      screen.replaceChildren(h('form', { class: 'gate', onsubmit: async e => {
        e.preventDefault();
        const key = input.value.trim();
        if (!key) { error = 'Введите ключ, который пришёл после покупки.'; draw(); return; }
        error = null;
        try { snap = await app.api.activate(key); } catch { error = 'Не удалось отправить ключ. Попробуйте ещё раз.'; }
        draw(); poll();
      } },
        message ? meerkat({ mood: 'surprised', size: 84 }) : h('img', { src: 'assets/logo.png', alt: '', class: 'gate-logo' }),
        h('h1', {}, checking ? 'Проверяем лицензию…' : 'Активация AIRA'),
        checking ? h('span', { class: 'spinner lg' }) : null,
        needKey ? h('p', { class: 'muted' }, 'Введите ключ лицензии. Один ключ — одно устройство. Для запуска нужен интернет: лицензия проверяется при каждом старте.') : null,
        message ? h('p', { class: 'form-error' }, message) : null,
        needKey ? input : null,
        needKey ? h('button', { class: 'btn primary lg', type: 'submit' }, 'Активировать') : null,
        s.phase === 'failed' && s.retry_available && code !== 'invalid_license' && code !== 'device_mismatch'
          ? h('button', { class: 'btn', type: 'button', onclick: async () => { try { snap = await app.api.verify(); } catch { /* shown below */ } draw(); poll(); } }, 'Проверить снова') : null));
      if (needKey) input.focus();
    };
    let polling = false;
    const poll = async () => {
      if (polling) return;
      polling = true;
      while (snap.phase === 'checking' || snap.phase === 'new') {
        await sleep(500);
        try { snap = await app.api.licence(); } catch { break; }
      }
      polling = false;
      draw();
    };
    draw(); poll();
  });
}

async function checkLicenceQuietly() {
  try {
    const s = await app.api.licence();
    if (!s) return;
    app.licence = s;
    const locked = s.phase !== 'active' && s.phase !== 'checking';
    if (locked !== app.licenceLocked) { app.licenceLocked = locked; scheduleRender(); }
  } catch { /* keep the previous state */ }
}

/* =========================================================
   Documents: list, create, import, example (F04, F11, F12)
   ========================================================= */
async function refreshDocs() {
  try { app.docs = await app.api.listDocuments(); } catch { /* keep previous list */ }
  scheduleRender();
}
const docInfo = id => app.docs.find(d => d.document_id === id);
const titleOf = id => docInfo(id)?.title || (app.examples.has(id) ? EXAMPLE_TITLE : 'Документ');
const isExample = id => app.examples.has(id) || docInfo(id)?.title === EXAMPLE_TITLE;
app.isExample = isExample;
app.refreshDocs = () => refreshDocs();
app.why = (e, fallback, context) => why(e, fallback, context);

async function createDocument() {
  const r = await modal({ title: 'Новый документ', body: 'Документ создаётся по шаблону AIRA: обычный текст, три уровня заголовков и списки.',
    input: { label: 'Название документа', placeholder: 'Например, Требования к каталогу', maxLength: 200 },
    actions: [{ id: 'cancel', label: 'Отмена' }, { id: 'ok', label: 'Создать', kind: 'primary' }] });
  if (r?.id !== 'ok') return;
  await withImporter(() => app.importer.create(r.value), 'Не удалось создать документ.');
}

async function importDocument() {
  const picked = await app.host.openDocx();
  if (!picked) return;
  // Bytes from the shell may come from another JS realm; the client checks `instanceof Uint8Array`.
  if (picked.tooBig) { toast('Файл больше 32 МБ — его нельзя импортировать.', 'warn'); return; }
  const file = { name: String(picked.name || 'document.docx'), bytes: new Uint8Array(picked.bytes) };
  if (!/\.docx$/i.test(file.name)) {
    toast(/\.doc$/i.test(file.name) ? 'Формат .doc не поддерживается. Сохраните файл в Word как .docx.' : 'AIRA открывает только документы Word в формате .docx.', 'warn', { ms: 6000 });
    return;
  }
  if (file.bytes.byteLength > MAX_DOCX) { toast('Файл больше 32 МБ — его нельзя импортировать.', 'warn'); return; }
  const r = await modal({ title: 'Импорт документа Word',
    body: 'Оформление файла сохранится. Исходный файл не изменяется: AIRA работает с копией.',
    input: { label: 'Название документа', value: file.name.replace(/\.docx$/i, '').slice(0, 200), maxLength: 200 },
    actions: [{ id: 'cancel', label: 'Отмена' }, { id: 'ok', label: 'Импортировать', kind: 'primary' }] });
  if (r?.id !== 'ok') return;
  await withImporter(() => app.importer.importDocx(r.value, file.bytes),
    'Не удалось импортировать файл: он повреждён или не является документом Word.');
}

async function openExample() {
  const existing = [...app.examples].find(id => docInfo(id)) || app.docs.find(d => d.title === EXAMPLE_TITLE)?.document_id;
  if (existing) {
    app.examples.add(existing);
    store.set('aira.examples', [...app.examples]);
    return openDocument(existing);
  }
  await withImporter(() => app.importer.importDocx(EXAMPLE_TITLE, buildExampleDocx()), 'Не удалось подготовить учебный пример.', id => {
    app.examples.add(id);
    store.set('aira.examples', [...app.examples]);
  });
}

async function withImporter(fn, failMessage, onCreated) {
  const ov = overlay('Готовим документ…');
  try {
    const meta = await fn();
    onCreated?.(meta.document_id);
    await refreshDocs();
    ov.close();
    await openDocument(meta.document_id);
  } catch (e) {
    ov.close();
    const s = app.importer.status();
    if (s.canRetry) toast('Сервер не подтвердил операцию. Повторите — документ не задвоится.', 'error', {
      ms: 10000, action: { label: 'Повторить', run: () => withImporter(() => app.importer.retry(), failMessage, onCreated) } });
    else toast(why(e, failMessage, /импорт/i.test(failMessage) ? 'import' : 'create'), 'error', { ms: 7000 });
  }
}

/* =========================================================
   Tabs: open / switch / close (F11, F12)
   ========================================================= */
const tabOf = id => app.workspace.status().tabs.find(t => t.documentId === id);

// Понятное объяснение ошибки клиентских модулей бэкенда (DocxClientError: code + HTTP-статус) и запись в журнал.
// Раньше почти везде показывалось общее «не удалось», и терялась разница между «нет связи», «занято» и т. п.
function why(e, fallback, context = '') {
  const code = e?.code, status = e?.status;
  postDiag('error', `${context}: ${fallback} [${code || e?.name || 'error'}${status ? ' ' + status : ''}]`);
  if (code === 'transport_error' || e instanceof TypeError) return 'Нет связи с сервером AIRA. Проверьте, что окно AIRA открыто, или перезапустите AIRA.';
  if (code === 'session_expired') return 'Сеанс правки устарел. Закройте документ и откройте его снова.';
  if (code === 'conflict' || status === 409) return 'Документ изменился в другом месте. Закройте его и откройте снова.';
  if (status === 413) return context === 'import' ? 'Файл слишком большой для импорта.' : 'Открыто слишком много документов. Закройте лишние и повторите.';
  if (status === 422 && context === 'import') return 'Этот файл Word не удаётся прочитать. Откройте его в Word, сохраните заново как .docx и повторите.';
  if (status === 503) return 'Сервер AIRA занят или ещё запускается. Повторите через минуту.';
  if (code === 'busy') return `${fallback} AIRA ещё выполняет предыдущее действие — повторите через секунду.`;
  if (status >= 500) return `${fallback} Ошибка на сервере AIRA — подробности в журнале (меню «?» → «Скачать журнал»).`;
  return fallback;
}

async function openDocument(id) {
  if (app.editors.has(id)) { app.workspace.focus(id); activate(id); return; }
  if (app.opening) return;
  app.opening = id;
  scheduleRender();
  try {
    try { await app.workspace.open(id); } catch { /* inspect phase below */ }
    let tab = tabOf(id);
    if (tab?.phase === 'open_uncertain') {
      toast('Не удалось подтвердить открытие документа.', 'error', { action: { label: 'Повторить', run: async () => {
        try { await app.workspace.retryOpen(id); await attachEditor(id); } catch (e) { toast(why(e, 'Документ не открылся.', 'open'), 'error'); }
      } } });
      return;
    }
    if (tab?.phase === 'recovery_required') {
      // A working copy identical to the saved document holds nothing unsaved: open it silently.
      let same = false;
      try { const rec = await app.api.recovery(id); same = rec.phase === 'working' && rec.working_sha256 === rec.document.current_sha256; } catch { /* ask */ }
      const r = same ? { id: 'recover' } : await modal({ title: 'Восстановить несохранённые изменения?',
        body: 'Для этого документа есть рабочая копия с изменениями, которые не были сохранены (например, после закрытия приложения). Восстановить их?',
        actions: [{ id: 'cancel', label: 'Не открывать' }, { id: 'recover', label: 'Восстановить', kind: 'primary' }] });
      if (r?.id !== 'recover') { try { await app.workspace.close(id); } catch { /* preview only */ } return; }
      await app.workspace.open(id, { recover: true });
      tab = tabOf(id);
    }
    if (tab?.phase === 'recovery_pending' || tab?.phase === 'reconcile_uncertain') {
      await app.workspace.reconcile(id);
      tab = tabOf(id);
    }
    if (tab?.phase !== 'open') {
      toast(tab?.phase === 'conflict' ? 'Документ изменён в другом месте. Откройте его заново позже.' : 'Документ не удалось открыть для правки.', 'error');
      return;
    }
    await attachEditor(id);
  } catch (e) {
    toast(why(e, 'Документ не удалось открыть.', 'open'), 'error', { ms: 7000 });
  } finally {
    app.opening = null;
    scheduleRender();
  }
}

async function attachEditor(id) {
  const ed = new DocEditor({ documentId: id, workspace: app.workspace, api: app.api,
    isLocked: () => app.licenceLocked,
    onChange: kind => {
      if (kind === 'projection') review.highlights(id);
      if (kind === 'local' || kind === 'projection') scheduleAutosave(id);
      scheduleRender();
    },
    onFindingClick: fid => review.select(id, fid, false) });
  app.editors.set(id, ed);
  activate(id);
  try { await ed.load(); } catch (e) { toast(why(e, 'Не удалось загрузить содержимое документа.', 'load'), 'error'); }
  review.ensureLoaded(id);
  scheduleRender();
  setTimeout(() => maybeDocTour(), 700);
}

// Автосохранение: 5 секунд без правок — версия документа сохраняется сама (как кнопка «Сохранить», но молча).
const AUTOSAVE_MS = 5000;
const autosaveTimers = new Map();
function scheduleAutosave(id) {
  clearTimeout(autosaveTimers.get(id));
  autosaveTimers.set(id, setTimeout(() => autosave(id), AUTOSAVE_MS));
}
async function autosave(id) {
  autosaveTimers.delete(id);
  const ed = app.editors.get(id);
  if (!ed || ed.disposed || ed.laneError) return;
  let c;
  try { c = app.workspace.client(id); } catch { return; }
  const s = c.editor.status();
  // Идёт ввод, отправка правки или запуск проверки — попробуем ещё раз чуть позже.
  if (ed.localPending || ed.queued || s.busy || ['saving', 'admitting'].includes(c.analysis.status().phase)) { scheduleAutosave(id); return; }
  if (!s.dirty) return;
  try {
    await ed.flushAll();
    if (!ed.laneError && c.editor.status().dirty) { await c.editor.save(); void refreshDocs(); }
  } catch {
    // Ошибку покажет строка статуса и ручное «Сохранить»; следующая правка снова запустит автосохранение.
  } finally { scheduleRender(); }
}

// Обучение по документу — при первом открытии, когда на экране нет окон и другого обучения.
function maybeDocTour(tries = 30) {
  if (store.get(TOURS.doc, false) || !app.activeId) return;
  if (tourActive() || $('#modal-root').children.length) { if (tries) setTimeout(() => maybeDocTour(tries - 1), 500); return; }
  startTour('doc');
}

function activate(id) {
  app.activeId = id;
  const paper = $('#paper');
  paper.replaceChildren(app.editors.get(id).root);
  $('#start').hidden = true;
  $('#doc-view').hidden = false;
  review.reset();
  scheduleRender();
}

function showStart() {
  app.activeId = null;
  $('#doc-view').hidden = true;
  $('#start').hidden = false;
  if (window.CSS?.highlights) CSS.highlights.clear();
  scheduleRender();
}

// Confirmed refusal is terminal; uncertain admission must retain its stop/retry guards.
const isRunning = a => a.canStop && a.phase !== 'not_admitted';

// Confirmed refusal is settled by the updated client; use its normal close path.
async function waitClientIdle(id) {
  const c = app.workspace.client(id);
  const idle = await waitFor(() => !c.editor.status().busy && !c.review.status().busy
    && !c.files.status().busy, 15000);
  if (!idle) throw new Error('busy');
}
async function closeAllTabs() {
  for (const t of app.workspace.status().tabs) {
    if (t.phase !== 'open') continue;
    await waitClientIdle(t.documentId);
    await app.workspace.close(t.documentId);
  }
}

async function waitFor(cond, ms = 15000) {
  const end = Date.now() + ms;
  while (!cond()) { if (Date.now() > end) return false; await sleep(80); }
  return true;
}

async function closeDocument(id) {
  const ed = app.editors.get(id);
  if (!ed) return;
  await ed.flushAll();
  const c = app.workspace.client(id);
  if (isRunning(c.analysis.status())) {
    const r = await modal({ title: 'Идёт проверка', body: 'Остановить проверку и закрыть документ?',
      actions: [{ id: 'cancel', label: 'Отмена' }, { id: 'stop', label: 'Остановить и закрыть', kind: 'primary' }] });
    if (r?.id !== 'stop') return;
    try { await c.analysis.stop(); } catch { /* checked below */ }
    if (!await waitFor(() => !isRunning(c.analysis.status()) && !c.analysis.status().busy, 20000)) {
      toast('Проверка ещё останавливается. Закройте документ чуть позже.', 'warn'); return;
    }
  }
  if (c.editor.status().dirty) {
    const r = await modal({ title: `Сохранить изменения в «${titleOf(id)}»?`,
      body: 'Если не сохранять, изменения останутся в рабочей копии на этом компьютере, и AIRA предложит восстановить их при следующем открытии.',
      actions: [{ id: 'cancel', label: 'Отмена' }, { id: 'keep', label: 'Не сохранять' }, { id: 'save', label: 'Сохранить', kind: 'primary' }] });
    if (!r || r.id === 'cancel') return;
    if (r.id === 'save' && !await saveDocument(id, { quiet: true })) return;
  }
  await waitFor(() => { const s = c.editor.status(); return !s.busy; }, 15000);
  try {
    await waitClientIdle(id);
    await app.workspace.close(id);
  } catch (e) {
    const tab = tabOf(id);
    if (tab?.phase === 'close_uncertain') {
      toast('Не удалось подтвердить закрытие. Изменения не удалены.', 'error', { action: { label: 'Повторить', run: async () => {
        try { await app.workspace.retryClose(id); detach(id); } catch (e) { toast(why(e, 'Закрытие пока не подтверждено.', 'close'), 'error'); }
      } } });
    } else toast(why(e, 'Документ сейчас занят — попробуйте закрыть ещё раз.', 'close'), 'warn');
    return;
  }
  detach(id);
}

function detach(id) {
  clearTimeout(autosaveTimers.get(id));
  autosaveTimers.delete(id);
  app.editors.get(id)?.dispose();
  app.editors.delete(id);
  if (app.activeId === id) {
    const next = app.workspace.status().tabs.find(t => app.editors.has(t.documentId));
    if (next) activate(next.documentId); else showStart();
  }
  void refreshDocs();
}

/* =========================================================
   Save / export / close the application (Nikita: save buttons, files, unfinished writes)
   ========================================================= */
async function saveDocument(id = app.activeId, { quiet = false } = {}) {
  const ed = app.editors.get(id);
  if (!ed) return false;
  await ed.flushAll();
  if (ed.laneError) { toast('Последняя правка не подтверждена — нажмите «Повторить» в строке статуса.', 'warn'); return false; }
  const editor = app.workspace.client(id).editor;
  await waitFor(() => !editor.status().busy);
  try {
    await editor.save();
    if (!quiet) toast('Документ сохранён', 'ok');
    void refreshDocs();
    return true;
  } catch (e) {
    if (editor.status().canRetry) toast('Сохранение не подтверждено. Изменения не потеряны.', 'error', { ms: 10000,
      action: { label: 'Повторить', run: async () => { try { await editor.retry(); toast('Документ сохранён', 'ok'); } catch (e) { toast(why(e, 'Сохранение снова не подтверждено.', 'save'), 'error'); } scheduleRender(); } } });
    else toast(why(e, 'Не удалось сохранить документ.', 'save'), 'error', { ms: 7000 });
    return false;
  } finally { scheduleRender(); }
}

async function exportDocument() {
  const id = app.activeId, ed = app.editors.get(id);
  if (!ed) return;
  await ed.flushAll();
  const files = app.workspace.client(id).files;
  const finish = async result => {
    const name = `${titleOf(id).replace(/[\\/:*?"<>|]+/g, '').trim().slice(0, 120) || 'Документ'}.docx`;
    try {
      const r = await app.host.saveDocx(name, result.bytes);
      if (r?.saved === true) toast(r.path ? `Файл сохранён: ${r.path}` : 'Файл сохранён', 'ok', { ms: 6000 });
      else if (r?.browser) toast('Документ сохранён и передан браузеру для загрузки.', 'ok');
      else if (r?.saved === false) toast('Сохранение файла отменено.', 'info');
    } catch { toast('Не удалось записать файл. Попробуйте выбрать другую папку.', 'error'); }
    void refreshDocs();
  };
  const ov = overlay('Готовим DOCX…');
  try {
    const result = await files.exportDocx();
    ov.close();
    await finish(result);
  } catch (e) {
    ov.close();
    if (files.status().canRetry) toast('Экспорт не завершён: версия для выгрузки не подтверждена.', 'error', { ms: 10000,
      action: { label: 'Повторить', run: async () => { try { await finish(await files.retry()); } catch (e) { toast(why(e, 'Экспорт снова не удался.', 'export'), 'error'); } } } });
    else toast(why(e, 'Не удалось подготовить DOCX.', 'export'), 'error', { ms: 7000 });
  } finally { scheduleRender(); }
}

function anyUnconfirmed() {
  for (const [id, ed] of app.editors) {
    if (ed.localPending || ed.laneError) return true;
    try { const s = app.workspace.client(id).editor.status(); if (s.uncheckpointed || s.busy || s.canRetry) return true; } catch { /* closed */ }
  }
  return false;
}

// Shell shutdown handshake: every accepted edit is written to a working copy before quitting.
// Never forces: on failure the user decides to retry or keep the app open.
async function prepareToClose() {
  if (!app.workspace) return true;
  const ov = overlay('Сохраняем рабочие копии перед закрытием…');
  try {
    for (const ed of app.editors.values()) await ed.flushAll();
    for (const [id, ed] of app.editors) if (ed.laneError) throw new Error('lane');
    for (const id of app.editors.keys()) {
      const a = app.workspace.client(id).analysis;
      if (isRunning(a.status())) { try { await a.stop(); } catch { /* wait below */ } }
      await waitFor(() => !isRunning(a.status()) && !a.status().busy, 20000);
    }
    for (const id of app.editors.keys()) await waitFor(() => !app.workspace.client(id).editor.status().busy, 15000);
    await closeAllTabs();
    for (const ed of app.editors.values()) ed.dispose();
    app.editors.clear();
    showStart(); // закрытые документы больше не перерисовываются, если окно ещё не закрылось
    ov.close();
    return true;
  } catch (e) {
    ov.close();
    postDiag('error', `prepareToClose: ${e?.code || e?.message || e}`);
    const r = await modal({ title: 'Не удалось завершить запись',
      body: 'AIRA не получила подтверждение, что последние изменения записаны. Если закрыть приложение сейчас, их можно потерять.',
      actions: [{ id: 'stay', label: 'Не закрывать', kind: 'primary' }, { id: 'retry', label: 'Повторить' }], dismissable: false });
    if (r?.id === 'retry') return prepareToClose();
    scheduleRender();
    return false;
  }
}

/* =========================================================
   Rendering of chrome (sidebar, top bar, toolbar)
   ========================================================= */
let frame = 0;
function scheduleRender() {
  if (frame) return;
  frame = requestAnimationFrame(() => { frame = 0; renderChrome(); review.render(); });
}

function onWorkspaceState() {
  const open = new Set(app.workspace.status().tabs.filter(t => t.phase === 'open').map(t => t.documentId));
  for (const id of app.editors.keys()) if (open.has(id)) void review.onAnalysis(id).catch(() => {});
  scheduleRender();
}

let sidebarKey = null;
function renderChrome() {
  if (!app.workspace) return;
  document.body.classList.toggle('no-sidebar', !app.sidebar);
  document.body.classList.toggle('drawer-closed', !app.drawer || !app.activeId);
  // После обучения карточка учебного примера уходит со стартового экрана — он остаётся в меню «?».
  $('#start [data-start="example"]').hidden = store.get(TOURS.start, false) && !tourActive();
  document.body.classList.toggle('has-doc', !!app.activeId);
  $('#licence-banner').hidden = !app.licenceLocked;
  renderSidebar();
  renderTopbar();
  renderToolbar();
}

function renderSidebar() {
  const tabs = app.workspace.status().tabs.filter(t => app.editors.has(t.documentId) || t.documentId === app.opening);
  const statusOf = id => {
    try { const c = app.workspace.client(id); return { dirty: c.editor.status().dirty, checking: isRunning(c.analysis.status()) }; }
    catch { return { dirty: false, checking: false }; }
  };
  const all = app.docs.filter(d => !isExample(d.document_id))
    .sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at));
  const hiddenCount = all.filter(d => app.hiddenDocs.has(d.document_id)).length;
  const library = app.showHidden ? all : all.filter(d => !app.hiddenDocs.has(d.document_id));
  const key = JSON.stringify([tabs.map(t => [t.documentId, statusOf(t.documentId)]), app.activeId, app.opening,
    library.map(d => [d.document_id, d.title, d.updated_at]), app.docs.length, [...app.hiddenDocs], app.showHidden]);
  if (key === sidebarKey) return;
  sidebarKey = key;
  $('#open-list').replaceChildren(...(tabs.length ? tabs.map(t => {
    const id = t.documentId, s = statusOf(id);
    return h('li', { class: `doc-item${id === app.activeId ? ' active' : ''}` },
      h('button', { class: 'doc-link', onclick: () => openDocument(id), title: titleOf(id) },
        icon(isExample(id) ? 'book' : 'doc'), h('span', { class: 'name' }, titleOf(id)),
        isExample(id) ? h('span', { class: 'tag' }, 'пример') : null,
        s.checking ? h('span', { class: 'spinner xs', title: 'Идёт проверка' }) : s.dirty ? h('span', { class: 'dot', title: 'Есть несохранённые изменения' }) : null),
      h('button', { class: 'icon-btn xs', title: 'Закрыть', onclick: () => closeDocument(id) }, icon('x')));
  }) : [h('li', { class: 'muted small empty-li' }, 'Нет открытых документов')]));
  $('#doc-list').replaceChildren(...(library.length ? library.map(d => {
    const id = d.document_id, hidden = app.hiddenDocs.has(id);
    return h('li', { class: `doc-item${id === app.activeId ? ' active' : ''}${hidden ? ' hidden-doc' : ''}` },
      h('button', { class: 'doc-link two', onclick: () => openDocument(id), title: d.title },
        icon('doc'), h('span', { class: 'name' }, d.title), h('span', { class: 'meta' }, hidden ? `скрыт · ${fmtTime(d.updated_at)}` : fmtTime(d.updated_at))),
      hidden
        ? h('button', { class: 'icon-btn xs', title: 'Вернуть в список', 'aria-label': 'Вернуть в список', onclick: () => setHidden(id, false) }, icon('eye'))
        : h('button', { class: 'icon-btn xs', title: 'Убрать из списка', 'aria-label': 'Убрать из списка', onclick: () => setHidden(id, true) }, icon('eye-off')));
  }) : [h('li', { class: 'muted small empty-li' }, hiddenCount ? 'Все документы убраны из списка' : 'Здесь появятся ваши документы')]));
  const toggle = $('#hidden-toggle');
  toggle.hidden = !hiddenCount;
  toggle.textContent = app.showHidden ? 'Не показывать убранные' : `Убранные из списка: ${hiddenCount}`;
}

function setHidden(id, hidden) {
  if (hidden) app.hiddenDocs.add(id); else app.hiddenDocs.delete(id);
  if (!app.hiddenDocs.size) app.showHidden = false;
  store.set('aira.hiddenDocs', [...app.hiddenDocs]);
  scheduleRender();
  if (hidden) toast(`«${titleOf(id)}» убран из списка. Сам документ хранится на компьютере.`, 'info',
    { ms: 6000, action: { label: 'Вернуть', run: () => setHidden(id, false) } });
}

function saveState(id) {
  const ed = app.editors.get(id);
  const s = app.workspace.client(id).editor.status();
  if (ed.laneError === 'conflict' || s.phase === 'conflict') return { cls: 'err', text: 'Документ изменён в другом месте', retry: false };
  if (ed.laneError === 'session_expired' || s.phase === 'expired') return { cls: 'err', text: 'Сеанс правки устарел — закройте и откройте документ', retry: false };
  if (ed.laneError || s.phase === 'uncertain') return { cls: 'err', text: 'Правка не подтверждена', retry: true };
  if (s.busy || ed.queued) return { cls: '', text: 'Сохранение…' };
  if (ed.localPending) return { cls: 'draft', text: 'Есть несохранённые изменения' };
  if (s.dirty) return { cls: 'draft', text: s.uncheckpointed ? 'Есть несохранённые изменения' : 'Черновик записан · документ не сохранён',
    title: 'Рабочая копия автоматически записывается раз в две минуты. «Сохранить» фиксирует версию документа.' };
  return { cls: 'ok', text: 'Сохранено' };
}

function renderTopbar() {
  const id = app.activeId;
  $('#doc-title').replaceChildren(...(id ? [h('span', { class: 'title' }, titleOf(id)),
    isExample(id) ? h('span', { class: 'tag' }, 'учебный пример') : null].filter(Boolean) : []));
  const status = $('#save-status');
  if (!id) { status.replaceChildren(); return; }
  const s = saveState(id);
  status.className = `save-status ${s.cls}`;
  status.title = s.title || '';
  status.replaceChildren(...[s.cls === 'ok' ? icon('check') : s.cls === 'err' ? icon('alert') : h('span', { class: 'dot' }), s.text,
    s.retry ? h('button', { class: 'link', onclick: () => app.editors.get(id).retryLane() }, 'Повторить') : null].filter(Boolean));
  $('#zoom-value').textContent = `${app.zoom}%`;
}

function renderToolbar() {
  const id = app.activeId, ed = id && app.editors.get(id);
  if (!ed) return;
  const block = ed.currentBlock();
  const locked = app.licenceLocked || !!ed.laneError;
  for (const b of document.querySelectorAll('#toolbar [data-cmd]')) b.disabled = locked;
  const select = $('#style-select');
  select.disabled = locked;
  select.value = String(block?.level || 0);
  $('[data-cmd="bullet"]').classList.toggle('on', block?.list === 'bullet');
  $('[data-cmd="numbered"]').classList.toggle('on', block?.list === 'number');
  const proj = ed.projection;
  $('#doc-notice').hidden = !proj?.has_unprojected_content;
  // Заранее предупредить, если в DOCX есть элементы, из-за которых бэкенд не примет проверку.
  const blockers = ed.assets?.blockers || [];
  const bkey = JSON.stringify([id, blockers.map(b => [b.tag, b.count])]);
  if ($('#check-notice').dataset.key !== bkey) {
    $('#check-notice').dataset.key = bkey;
    $('#check-notice').hidden = !blockers.length;
    $('#check-notice .body').replaceChildren(...(blockers.length ? [h('strong', {}, 'В документе есть особые элементы Word. '),
      'Совместимость будет определена при проверке. Исходный файл не изменяется:', blockersNode(blockers)] : []));
  }
  $("#example-banner").hidden = !isExample(id);
}

function applyZoom() {
  document.documentElement.style.setProperty('--doc-scale', String(app.zoom / 100));
  store.set('aira.zoom', app.zoom);
  scheduleRender();
}

/* =========================================================
   Начальное обучение с сурикатом
   ========================================================= */
const TOURS = { start: 'aira.tour.start', doc: 'aira.tour.doc' };

function legend() {
  return h('div', { class: 'tour-legend' }, [['formulation', 'Формулировки'], ['duplicate', 'Дубли'], ['contradiction', 'Противоречия'], ['question', 'Вопросы']]
    .map(([t, label]) => h('span', {}, h('i', { style: { background: `var(--t-${t})` } }), label)));
}
function ensureSidebar() { if (!app.sidebar) { app.sidebar = true; store.set('aira.sidebar', true); renderChrome(); } }

function startSteps() {
  return [
    { mood: 'wave', title: 'Привет! Я сурикат AIRA', nextLabel: 'Поехали',
      text: ['Сурикаты стоят на посту и первыми замечают опасность. Я делаю то же с требованиями: ищу размытые формулировки, дубли и противоречия.',
        'Покажу, что здесь где. Это займёт минуту.'] },
    { target: '.start-cards', title: 'С чего начать',
      text: 'Создайте новый документ, загрузите файл .docx из Word или откройте учебный пример с типичными ошибками.' },
    { target: '.sidebar', before: ensureSidebar, pad: 0, title: 'Ваши документы',
      text: ['Слева — открытые документы и все сохранённые. «Новый документ» сразу спросит название.',
        'Ненужный документ можно убрать из списка значком глаза. Саму панель скрывает кнопка в левом верхнем углу.'] },
    { target: '#home-btn', title: 'Возврат на старт', text: 'Логотип AIRA возвращает на этот экран. Открытые документы при этом не закрываются.' },
    { title: 'Как проходит проверка', extra: legend,
      text: ['Откройте документ и нажмите «Проверить» справа или Ctrl+Enter. Проверка идёт на этом компьютере и занимает до 5 минут.',
        'Найденное я подсвечу в тексте своим цветом, а если не хватит контекста — задам вопрос.'] },
    { mood: 'surprised', title: 'Если что-то пойдёт не так',
      text: 'Я выгляну из норки в правом нижнем углу, покажу, что случилось, и подскажу, что делать. Ваш текст при этом не теряется.',
      action: { label: 'Показать', run: () => mascotAlert('Вот так я сообщаю об ошибке: что случилось и что можно сделать дальше.', 'error', { ms: 6000 }) } },
    { target: '[data-start="example"]', mood: 'happy', title: 'Попробуем?',
      text: ['Учебный пример — самый быстрый способ увидеть проверку в деле.',
        'После обучения эта карточка спрячется. Пример и обучение всегда доступны по кнопке «?» в правом верхнем углу.'],
      nextLabel: 'Открыть пример', laterLabel: 'Позже', onDone: () => openExample() },
  ];
}

function docSteps() {
  return [
    { target: '#paper', pad: 0, side: 'right', title: 'Это ваш документ',
      text: 'Пишите прямо на листе. Правки сохраняются сами через секунду после паузы. Enter делит абзац, Ctrl+Z отменяет.' },
    { target: '#toolbar', title: 'Оформление', text: 'Отмена и повтор, стиль абзаца — обычный текст или заголовок трёх уровней — и списки.' },
    { target: '.zoom', title: 'Размер текста', text: 'A− и A+ меняют только масштаб на экране, сам файл не меняется.' },
    { target: '.drawer', before: () => { app.drawer = true; store.set('aira.drawer', true); renderChrome(); review.render(); }, pad: 0, side: 'left',
      title: 'Проверка требований', extra: legend,
      text: ['Здесь запуск проверки, её ход и замечания. Текст можно править и во время проверки.',
        'Фильтр показывает все замечания или один тип, «Вопросы» — то, что стоит уточнить. Лишнее замечание скрывается значком глаза.'] },
    { target: '#drawer-close', title: 'Больше места', text: 'Шторку можно свернуть в узкую полосу справа и открыть обратно кнопкой на полосе.' },
    { target: '.doc-actions', mood: 'happy', title: 'Сохранение и экспорт',
      text: '«Сохранить» (Ctrl+S) фиксирует версию. «Экспорт DOCX» выгружает файл для Word без замечаний AIRA. Закрыть документ — крестиком в списке слева.' },
  ];
}

function startTour(kind) {
  if (kind === 'doc' && !app.activeId) kind = 'start';
  if (kind === 'start') showStart();
  runTour(kind === 'doc' ? docSteps() : startSteps(), { onFinish: () => { store.set(TOURS[kind], true); scheduleRender(); } });
  renderChrome();
}

/* ---------- Журнал диагностики ---------- */
// События интерфейса (сообщения сурката, ошибки скриптов) — в журнал сервера (aira.log), без текста документов.
function postDiag(kind, message) {
  if (!app.host?.sessionToken) return;
  try {
    void fetch('/aira/diagnostics/client', { method: 'POST', credentials: 'omit', keepalive: true,
      headers: { 'Content-Type': 'application/json', 'X-AIRA-Session': app.host.sessionToken },
      body: JSON.stringify({ kind, message: String(message).slice(0, 800) }) }).catch(() => {});
  } catch { /* журнал не обязателен */ }
}
window.addEventListener('aira:alert', e => postDiag(e.detail.kind, e.detail.message));
window.addEventListener('error', e => postDiag('js-error', `${e.message} @${(e.filename || '').split('/').pop()}:${e.lineno}`));
window.addEventListener('unhandledrejection', e => postDiag('js-rejection', e.reason?.code || e.reason?.message || e.reason));

async function downloadLog() {
  try {
    const r = await fetch('/aira/diagnostics/log', { cache: 'no-store', credentials: 'omit', headers: { 'X-AIRA-Session': app.host.sessionToken } });
    if (!r.ok) throw new Error(String(r.status));
    const name = (r.headers.get('Content-Disposition') || '').match(/filename="([^"]+)"/)?.[1] || 'aira-log.txt';
    const bytes = new Uint8Array(await r.arrayBuffer());
    if (app.host.saveFile) {
      const res = await app.host.saveFile(name, bytes, 'text/plain');
      if (res?.saved) toast(`Журнал сохранён: ${res.path}. Отправьте этот файл разработчикам.`, 'ok', { ms: 7000 });
      return;
    }
    const url = URL.createObjectURL(new Blob([bytes], { type: 'text/plain' }));
    const a = h('a', { href: url, download: name });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    toast(`Журнал сохранён в «Загрузки»: ${name}. Отправьте этот файл разработчикам.`, 'ok', { ms: 7000 });
  } catch {
    toast('Не удалось получить журнал. Он лежит в папке %LOCALAPPDATA%\\AIRA\\logs (кнопка «Журнал» в окне AIRA).', 'error', { ms: 9000 });
  }
}

// Меню кнопки «?»: обучение и учебный пример.
function helpMenu() {
  if ($('.help-menu')) { $('.help-menu').remove(); return; }
  const item = (ic, label, run) => h('button', { class: 'menu-item', type: 'button', role: 'menuitem', onclick: () => { close(); run(); } }, icon(ic), label);
  const menu = h('div', { class: 'help-menu', role: 'menu' },
    item('help', app.activeId ? 'Обучение: работа с документом' : 'Пройти обучение', () => startTour(app.activeId ? 'doc' : 'start')),
    app.activeId ? item('help', 'Обучение: стартовый экран', () => startTour('start')) : null,
    item('book', 'Открыть учебный пример', () => openExample()),
    h('div', { class: 'menu-sep' }),
    item(sound.on ? 'volume' : 'volume-off', sound.on ? 'Звук сурката: включён' : 'Звук сурката: выключен', () => {
      sound.on = !sound.on;
      if (sound.on) oyoy(true);
      toast(sound.on ? 'Сурикат снова говорит «Ой-ёй!» при ошибках.' : 'Звук сурката выключен.', 'info');
    }),
    item('download', 'Скачать журнал для разработчиков', () => downloadLog()));
  const r = $('#help-btn').getBoundingClientRect();
  Object.assign(menu.style, { top: `${r.bottom + 6}px`, right: `${innerWidth - r.right}px` });
  const away = e => { if (!menu.contains(e.target) && !e.target.closest('#help-btn')) close(); };
  const esc = e => { if (e.key === 'Escape') close(); };
  function close() { menu.remove(); document.removeEventListener('mousedown', away, true); document.removeEventListener('keydown', esc, true); }
  document.addEventListener('mousedown', away, true);
  document.addEventListener('keydown', esc, true);
  document.body.append(menu);
  menu.querySelector('.menu-item').focus();
}

/* =========================================================
   Events
   ========================================================= */
const review = createReviewPanel({ body: $('#drawer-body'), rail: $('#rail'), app });

$('#sidebar-toggle').addEventListener('click', () => { app.sidebar = !app.sidebar; store.set('aira.sidebar', app.sidebar); scheduleRender(); });
$('#new-doc').addEventListener('click', () => createDocument());
$('#home-btn').addEventListener('click', () => showStart());
$('#help-btn').addEventListener('click', () => helpMenu());
$('#hidden-toggle').addEventListener('click', () => { app.showHidden = !app.showHidden; scheduleRender(); });
$('#start').addEventListener('click', e => {
  const a = e.target.closest('[data-start]')?.dataset.start;
  if (a === 'create') createDocument();
  else if (a === 'import') importDocument();
  else if (a === 'example') openExample();
});
$('#save-btn').addEventListener('click', () => saveDocument());
$('#export-btn').addEventListener('click', () => exportDocument());
$('#zoom-out').addEventListener('click', () => { app.zoom = Math.max(70, app.zoom - 10); applyZoom(); });
$('#zoom-in').addEventListener('click', () => { app.zoom = Math.min(160, app.zoom + 10); applyZoom(); });
$('#zoom-value').addEventListener('click', () => { app.zoom = 100; applyZoom(); });
$('#drawer-close').addEventListener('click', () => app.setDrawer(false));
$('#licence-retry').addEventListener('click', async () => { try { await app.api.verify(); } catch { /* polled */ } setTimeout(checkLicenceQuietly, 1500); });

$('#toolbar').addEventListener('mousedown', e => { if (e.target.closest('button')) e.preventDefault(); });
$('#toolbar').addEventListener('click', e => {
  const cmd = e.target.closest('[data-cmd]')?.dataset.cmd;
  const ed = app.editors.get(app.activeId);
  if (!cmd || !ed) return;
  if (cmd === 'undo') ed.undo();
  else if (cmd === 'redo') ed.redo();
  else if (cmd === 'bullet' || cmd === 'numbered') ed.toggleList(cmd);
});
$('#style-select').addEventListener('change', e => {
  const ed = app.editors.get(app.activeId);
  if (ed) ed.setStyle(Number(e.target.value));
});
document.addEventListener('selectionchange', () => { if (app.activeId) scheduleRender(); });
document.addEventListener('keydown', e => {
  if (!(e.ctrlKey || e.metaKey) || !app.activeId || $('#modal-root').children.length) return;
  if (e.code === 'KeyS') { e.preventDefault(); saveDocument(); }
  else if (e.key === 'Enter') { e.preventDefault(); review.runCheck(app.activeId); }
});

boot();
export { MSG };
