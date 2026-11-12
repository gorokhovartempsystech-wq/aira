// Right drawer: run the check (F06/F07) and review findings, questions, filters, hiding (F08–F10).
// Filters and hidden findings are stored by the backend per document and change presentation only.

import { h, icon, toast, fmtTime, fmtClock, plural } from './ui.mjs';
import { meerkat } from './mascot.mjs';
import { reviewCounts, standaloneQuestions } from './review-data.mjs';

export const TYPES = [
  ['formulation', 'Формулировки', 'Формулировка'],
  ['duplicate', 'Дубли', 'Возможный дубль'],
  ['contradiction', 'Противоречия', 'Возможное противоречие'],
];
const TYPE_IDS = TYPES.map(t => t[0]);
const TYPE_NAME = Object.fromEntries(TYPES.map(t => [t[0], t[2]]));
const STAGES = {
  saving: 'Сохраняем версию для проверки', admitting: 'Запускаем проверку', queued: 'В очереди',
  preparing_document: 'Подготовка документа', loading_model: 'Загрузка модели', analyzing: 'Анализ требований',
  running: 'Анализ требований', settling: 'Сохраняем результат', cancel_requested: 'Останавливаем проверку',
};
const ERRORS = {
  analysis_in_progress: 'Проверка этого документа уже идёт.',
  analysis_queue_full: 'Сейчас выполняется другая проверка. Повторите через минуту.',
  analysis_limit_exceeded: 'Документ слишком большой для проверки этой моделью.',
  analysis_deadline_exceeded: 'Проверка не уложилась в 5 минут.',
  deadline_exceeded: 'Проверка не уложилась в 5 минут.',
  adapter_error: 'Модель не смогла завершить проверку.',
  adapter_timeout: 'Модель не ответила вовремя.',
  invalid_result: 'Модель вернула некорректный результат.',
  source_corrupt: 'Не удалось прочитать сохранённую версию документа.',
  interrupted: 'Проверка прервалась.',
  not_ready: 'Модель ещё не готова к работе.',
  // Причины, по которым бэкенд не принимает проверку (error_code в ответе «not_admitted»).
  unsupported_analysis_content: 'Проверка пока не поддерживает часть содержимого этого документа Word (например, сложные поля, надписи или исправления).',
  unsupported_document: 'Проверка пока не поддерживает часть содержимого этого документа Word.',
  unsupported_package: 'Проверка пока не поддерживает часть содержимого этого документа Word.',
  invalid_package: 'Не удалось прочитать файл документа для проверки.',
  empty_document: 'В документе нет текста для проверки.',
  model_unavailable: 'Модель недоступна: её файлы не найдены или повреждены. Переустановите AIRA.',
  model_input_limit_exceeded: 'Документ слишком большой для модели.',
  recovery_required: 'Проверки заблокированы после сбоя. Перезапустите AIRA (кнопка «Выйти» в окне AIRA) — при запуске она предложит снять блокировку.',
  storage_error: 'Не удалось прочитать документ из базы. Попробуйте ещё раз.',
  validation_error: 'Сервер отклонил запрос проверки. Сохраните документ и попробуйте ещё раз.',
  source_mismatch: 'Документ изменился во время запуска проверки. Сохраните и проверьте снова.',
  analysis_busy: 'Сервер сейчас занят. Повторите через минуту.',
  analysis_history_exhausted: 'Для этого документа накопилось слишком много проверок.',
  analysis_clock_error: 'Не удалось проверить системное время компьютера.',
};
// Advisory inventory; actual admission depends on source-aware backend checks.
export function blockersNode(blockers) {
  return h('div', { class: 'blockers' },
    h('ul', {}, blockers.map(b => h('li', {}, h('strong', {}, `${b.label[0].toUpperCase()}${b.label.slice(1)} — ${b.count}. `), 'Поддержка зависит от содержимого элемента.'))),
    h('p', {}, 'Оригинальные элементы сохраняются в файле. Проверка сообщит, если какое-либо содержимое пока не поддерживается.'));
}

// Понятный текст причины; для неизвестной показываем код — его можно прислать разработчикам.
const reason = (code, fallback) => ERRORS[code] || (code ? `${fallback} Код причины: ${code}.` : fallback);
const RUNNING = new Set(['saving', 'admitting', 'waiting', 'poll_error']);

const countsKey = run => `aira.counts.v2.${run}`;
function readCounts(run) { try { return JSON.parse(localStorage.getItem(countsKey(run))); } catch { return null; } }
function writeCounts(run, c) { try { localStorage.setItem(countsKey(run), JSON.stringify(c)); } catch { /* optional */ } }

// Stored (backend) filter. "Questions" is a local view over the full result: the backend hides
// finding-linked questions together with their findings, so it cannot be a stored type filter.
function activeFilter(p) {
  const d = new Set(p.disabled_types);
  if (!d.size) return 'all';
  if (d.size === 2 && !p.show_questions) return TYPE_IDS.find(t => !d.has(t));
  return 'custom';
}
function filterValue(id, showHidden) {
  if (id === 'all' || id === 'questions') return { disabled_types: [], show_questions: true, show_hidden: showHidden };
  return { disabled_types: TYPE_IDS.filter(t => t !== id), show_questions: false, show_hidden: showHidden };
}

export function createReviewPanel({ body, rail, app }) {
  const docState = new Map(); // documentId → {loadedRun, loading, active}
  let lastKey = null;
  // loadFailed: a known successful run could not be read (a missing first result is not an error).
  const st = id => { if (!docState.has(id)) docState.set(id, { loadedRun: null, loading: false, active: null, loadFailed: false, questionsOnly: false }); return docState.get(id); };

  async function ensureLoaded(id) {
    const s = st(id);
    const client = app.workspace.client(id);
    if (s.loading || client.review.status().review) return;
    s.loading = true;
    try {
      const r = await client.review.load();
      s.loadedRun = r.review?.run.run_id || null;
    } catch { /* no successful result yet */ }
    finally { s.loading = false; app.render(); }
  }

  async function onAnalysis(id) {
    const s = st(id);
    const client = app.workspace.client(id);
    const a = client.analysis.status();
    const run = a.receipt?.run_id;
    if (a.phase === 'finished' && a.receipt?.state?.status === 'succeeded' && run && s.loadedRun !== run && !s.loading) {
      s.loading = true;
      try {
        await client.review.load(run); s.loadedRun = run; s.loadFailed = false;
        // A fresh result is shown in full, which also gives per-type counts for the chips.
        const prefs = client.review.status().review?.preferences;
        if (prefs && activeFilter(prefs) !== 'all') {
          try { await client.review.setFilters(filterValue('all', prefs.show_hidden)); } catch { /* keep the stored filter */ }
        }
      }
      catch { s.loadedRun = run; s.loadFailed = true; }
      finally { s.loading = false; app.render(); }
    }
  }

  async function runCheck(id) {
    const ed = app.editors.get(id);
    const client = app.workspace.client(id);
    if (app.licenceLocked) { toast('Лицензия не подтверждена — новая проверка недоступна.', 'warn'); return; }
    if (ed.isEmpty()) { toast('Введите текст требований — проверять пока нечего.', 'warn'); return; }
    // Preflight is advisory; only source-aware backend admission can decide.
    await ed.flushAll();
    if (ed.laneError) { toast('Сначала завершите сохранение правки (кнопка «Повторить» вверху).', 'warn'); return; }
    st(id).active = null;
    try { await client.analysis.check(); }
    catch { app.render(); }
  }

  const act = (fn, failMsg) => async () => { try { await fn(); } catch (e) { if (failMsg) toast(app.why ? app.why(e, failMsg, 'review') : failMsg, 'error'); } finally { app.render(); } };

  function highlights(id) {
    const ed = app.editors.get(id);
    if (!ed) return;
    const r = app.workspace.client(id).review.status();
    if (!r.review || !r.canHighlight) { ed.setHighlights([], null); return; }
    const hidden = new Set(r.review.view.hidden_finding_ids);
    const items = r.review.view.findings.filter(f => !hidden.has(f.finding_id)).map(f => ({
      id: f.finding_id, type: f.type,
      ranges: [...ed.evidenceRanges(f.primary), ...(f.related ? ed.evidenceRanges(f.related) : [])],
    }));
    for (const place of r.review.view.standalone_questions || []) {
      items.push({ id: place.question_id, type: 'formulation',
        ranges: place.evidence.flatMap(evidence => ed.evidenceRanges(evidence)) });
    }
    ed.setHighlights(items, st(id).active);
  }

  function select(id, findingId, scroll = true, evidence = null) {
    st(id).active = findingId;
    const ed = app.editors.get(id);
    const r = app.workspace.client(id).review.status();
    highlights(id);
    if (scroll) {
      if (!r.canHighlight) toast('Текст изменён после проверки — подсветка отключена. Проверьте документ снова.', 'info');
      else if (!(evidence ? ed.scrollToEvidence(evidence) : ed.scrollToFinding(findingId))) toast('Фрагмент находится в части документа, которая здесь не показывается.', 'info');
    }
    lastKey = null;
    app.render();
    body.querySelector(`[data-finding="${findingId}"]`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  /* ---------- Rendering ---------- */
  function render() {
    const id = app.activeId;
    const editor = id && app.editors.get(id);
    if (!editor) { body.replaceChildren(); rail.replaceChildren(); lastKey = null; return; }
    let client;
    try { client = app.workspace.client(id); } catch { return; }
    const a = client.analysis.status(), r = client.review.status(), s = st(id);
    const key = JSON.stringify([id, a.phase, a.receipt?.state?.status, a.receipt?.state?.stage, a.stopRequested, a.canStop,
      a.canRetryAdmission, a.canRetrySave, a.busy, r.phase, r.busy, r.canRetry, r.stale, r.canHighlight,
      r.review?.view_sha256, r.review?.preferences.revision, s.active, s.loading, s.loadFailed, s.questionsOnly, editor.isEmpty(), app.licenceLocked, (editor.assets?.blockers || []).length]);
    renderRail(a, r);
    if (key === lastKey) { tick(a); return; }
    lastKey = key;
    const scroll = body.scrollTop;
    body.replaceChildren(checkBlock(id, a, r), results(id, a, r));
    body.scrollTop = scroll;
    tick(a);
    highlights(id);
  }

  function tick(a) {
    const el = body.querySelector('.timer');
    const state = a.receipt?.state;
    if (!el || !state?.created_at) return;
    const start = Date.parse(state.created_at), limit = Date.parse(state.deadline_at) - start;
    el.textContent = `${fmtClock(Date.now() - start)} из ${fmtClock(limit)}`;
  }

  function renderRail(a, r) {
    const n = r.review ? reviewCounts(r.review.view, TYPE_IDS).all : null;
    rail.replaceChildren(
      h('button', { class: 'rail-btn', title: 'Открыть панель проверки', onclick: () => app.setDrawer(true) }, icon('chevron-left')),
      h('button', { class: 'rail-btn', title: 'Замечания', onclick: () => app.setDrawer(true) }, icon('spark'),
        n ? h('span', { class: 'badge' }, String(n)) : null, RUNNING.has(a.phase) ? h('span', { class: 'rail-spin' }) : null),
      h('span', { class: 'rail-label' }, 'Проверка требований'));
  }

  function checkBlock(id, a, r) {
    const client = app.workspace.client(id);
    const editor = app.editors.get(id);
    const box = h('section', { class: 'check' });
    const state = a.receipt?.state;
    const running = RUNNING.has(a.phase) || (a.phase === 'waiting');
    if (running) {
      const stage = a.phase === 'waiting' ? (state ? (STAGES[state.stage] || STAGES[state.status] || 'Проверка идёт') : 'В очереди') : STAGES[a.phase];
      box.append(
        h('div', { class: 'running' },
          h('div', { class: 'running-head' }, h('span', { class: 'spinner' }), h('strong', {}, a.stopRequested ? 'Останавливаем проверку…' : stage),
            h('span', { class: 'timer' })),
          a.phase === 'poll_error' ? h('div', { class: 'alert warn' }, icon('alert'), h('div', {},
            'Связь с проверкой прервалась. Она может продолжаться.',
            h('button', { class: 'btn sm', 'data-pilot': 'analysis.refresh', onclick: act(() => client.analysis.refresh(), 'Сервер пока не отвечает.') }, 'Обновить'))) : null,
          h('p', { class: 'muted small' }, 'Лимит проверки — 5 минут. Текст можно править: результат отнесётся к сохранённой версии.'),
          a.canStop ? h('button', { class: 'btn block', 'data-pilot': 'analysis.stop', onclick: act(() => client.analysis.stop(), 'Не удалось отправить остановку.') }, icon('stop'), 'Остановить проверку') : null));
      if (a.receipt?.fixture) box.append(fixtureNote());
      return box;
    }
    const empty = editor.isEmpty(), blocked = !!editor.assets?.blockers?.length;
    box.append(h('button', { class: 'check-btn', disabled: empty || app.licenceLocked || a.busy || !a.canCheck,
      onclick: () => runCheck(id) }, icon('scan'), r.review ? 'Проверить снова' : 'Проверить', h('kbd', {}, 'Ctrl+Enter')));
    if (empty) box.append(h('p', { class: 'note' }, 'Введите или вставьте текст требований — проверять пока нечего.'));
    else if (blocked) box.append(h('p', { class: 'note' }, 'В документе есть особые элементы Word. Нажмите «Проверить»: приложение определит, поддерживается ли их содержимое.'));

    if (a.phase === 'save_uncertain') box.append(problem('Не удалось подтвердить сохранение версии для проверки.', 'Повторить', () => client.analysis.retrySave()));
    else if (a.phase === 'save_error') box.append(problem('Не удалось сохранить версию для проверки. Текст не потерян.', null));
    else if (a.phase === 'admission_uncertain') box.append(problem('Не удалось подтвердить запуск проверки.', 'Повторить запуск', () => client.analysis.retryAdmission()));
    else if (a.phase === 'not_admitted') {
      const code = a.receipt?.error_code, blockers = editor.assets?.blockers || [];
      const p = problem(reason(code, 'Проверка не запущена.'), 'Проверить ещё раз', () => runCheck(id));
      if (code === 'unsupported_analysis_content' && blockers.length) p.querySelector('div').append(blockersNode(blockers));
      box.append(p);
    }
    else if (a.phase === 'finished' && state && state.status !== 'succeeded') {
      const msg = state.status === 'cancelled' ? 'Проверка остановлена. Предыдущий результат сохранён.'
        : state.status === 'timed_out' ? 'Проверка не уложилась в 5 минут. Предыдущий результат сохранён.'
        : `${reason(state.error_code, 'Проверка не завершилась.')} Текст сохранён.`;
      box.append(problem(msg, state.status === 'cancelled' ? null : 'Проверить ещё раз', () => runCheck(id)));
    }
    return box;
  }

  function problem(text, label, fn) {
    return h('div', { class: 'alert error' }, meerkat({ mood: 'surprised', size: 40 }), h('div', {}, h('p', {}, text),
      label ? h('button', { class: 'btn sm', 'data-pilot': 'analysis.retry', onclick: act(fn, 'Повтор не удался — попробуйте ещё раз.') }, label) : null));
  }
  const fixtureNote = () => h('div', { class: 'alert info' }, icon('info'),
    h('div', {}, h('strong', {}, 'Тестовый режим. '), 'Это учебный результат: настоящая модель не запускалась.'));

  function results(id, a, r) {
    const client = app.workspace.client(id);
    const wrap = h('section', { class: 'results' });
    const s = st(id);
    if (s.loading || (r.phase === 'loading' && !r.review)) { wrap.append(h('p', { class: 'muted small center' }, 'Загружаем замечания…')); return wrap; }
    if (r.phase === 'read_error' && !r.review && s.loadFailed) {
      wrap.append(problem('Не удалось загрузить результат проверки.', 'Повторить', async () => {
        await client.review.load(s.loadedRun); s.loadFailed = false;
      }));
      return wrap;
    }
    if (!r.review) {
      wrap.append(h('div', { class: 'empty' }, meerkat({ mood: 'idle', size: 64 }), h('strong', {}, 'Здесь появятся замечания'),
        'Нажмите «Проверить». Модель отметит размытые формулировки, возможные дубли и противоречия, а если не хватает контекста — задаст вопросы.'));
      return wrap;
    }
    const review = r.review, v = review.view, prefs = review.preferences;
    const hidden = new Set(v.hidden_finding_ids);
    const stored = activeFilter(prefs);
    const filter = s.questionsOnly ? 'questions' : stored;
    const visible = v.findings;
    const questions = v.questions.map(q => ({ id: q.question_id, text: q.text }));
    const places = standaloneQuestions(v, filter, prefs);

    // Per-type counts come from an unfiltered view of this run (cached on this computer).
    let counts = readCounts(review.run.run_id);
    if (stored === 'all') {
      counts = reviewCounts(v, TYPE_IDS);
      writeCounts(review.run.run_id, counts);
    }

    if (review.fixture) wrap.append(fixtureNote());
    if (r.stale) wrap.append(h('div', { class: 'alert warn' }, icon('alert'), h('div', {},
      'Текст изменён после проверки. Замечания относятся к прошлой версии, подсветка выключена. ',
      h('button', { 'data-pilot': 'analysis.check', class: 'link', onclick: () => runCheck(id) }, 'Проверить снова'))));
    if (v.analysis_coverage?.state === 'partial') wrap.append(h('div', { class: 'alert warn' }, icon('alert'),
      h('div', {}, 'Проверка неполная: не все проверки успели выполниться. Отсутствие замечаний не означает, что их нет.')));
    if (r.phase === 'conflict') wrap.append(problem('Настройки показа изменились. Обновите результат и выберите снова.', 'Обновить', () => client.review.load(s.loadedRun)));
    if (r.phase === 'uncertain') wrap.append(problem('Не удалось подтвердить изменение настроек показа.', 'Повторить', () => client.review.retry()));

    wrap.append(h('div', { class: 'res-head' }, h('h3', {}, 'Замечания'),
      h('span', { class: 'muted small' }, `Проверено ${fmtTime(review.run.finished_at || review.run.created_at)}`)));

    // Filters: "Все" + one type. A chip with zero items cannot be selected.
    const busy = r.busy || r.phase !== 'ready';
    const chip = (fid, label, n, color) => {
      const on = filter === fid;
      const zero = n === 0 && !on;
      return h('button', { 'data-pilot': 'review.filter', class: `fchip${on ? ' on' : ''}`, disabled: zero || busy, 'aria-pressed': String(on),
        title: zero ? 'Нет замечаний этого типа' : null,
        onclick: () => {
          if (on) return;
          s.questionsOnly = fid === 'questions';
          lastKey = null;
          if (activeFilter(filterValue(fid, prefs.show_hidden)) === stored) { render(); return; }
          act(() => client.review.setFilters(filterValue(fid, prefs.show_hidden)), 'Не удалось применить фильтр.')();
        } },
        color ? h('span', { class: `sw t-${color}` }) : null, label, n === null || n === undefined ? null : h('span', { class: 'n' }, String(n)));
    };
    wrap.append(h('div', { class: 'filters' },
      chip('all', 'Все', counts?.all ?? null),
      TYPES.map(([t, label]) => chip(t, label, counts?.[t] ?? null, t)),
      chip('questions', 'Вопросы', counts?.questions ?? null, 'question')));

    const list = h('div', { class: 'cards' });
    const listOfResults = list;
    if (places.length) {
      const list = h('div', { class: 'cards' });
      for (const place of places) {
        list.append(h('article', { class: 'card question', 'data-finding': place.question_id },
          h('div', { class: 'card-top' }, h('span', { class: 'type' }, place.text)),
          h('p', { class: 'why' }, place.reason),
          ...place.evidence.map(evidence => evidenceQuote(id, place.question_id, evidence, null, r.canHighlight))));
      }
      listOfResults.append(h('div', { class: 'res-head' }, h('h3', {}, 'Места для проверки')), list);
    }

    if (filter !== 'questions') {
      for (const f of visible) list.append(card(id, f, hidden.has(f.finding_id), r.canHighlight));
    }
    if ((filter === 'all' || filter === 'questions') && prefs.show_questions && questions.length) {
      list.append(h('h4', { class: 'group' }, icon('help'), 'Что уточнить'));
      for (const q of questions) list.append(h('article', { class: 'card question' },
        h('p', { class: 'q' }, q.text), q.reason ? h('p', { class: 'muted small' }, q.reason) : null,
        q.quote ? h('blockquote', {}, `«${q.quote}»`) : null));
    }
    if (!list.children.length) {
      if (v.no_findings && !questions.length && !places.length) {
        list.append(h('div', { class: 'empty success' }, meerkat({ mood: 'happy', size: 64 }), h('strong', {}, 'Замечаний нет'),
          'Модель не нашла проблем в этой версии. Это подсказка, а не доказательство полноты требований.'));
      } else {
        list.append(h('div', { class: 'empty' }, h('strong', {}, 'Нечего показать'),
          hidden.size && !prefs.show_hidden ? 'Замечания этого вида скрыты.' : 'Для выбранного фильтра замечаний нет.'));
      }
    }
    wrap.append(list);

    if (hidden.size || prefs.show_hidden) {
      wrap.append(h('div', { class: 'hidden-ctl' },
        h('button', { 'data-pilot': 'review.visibility', class: 'link', disabled: busy, onclick: act(() => client.review.setFilters({ ...filterValue(filter === 'custom' ? 'all' : filter, !prefs.show_hidden) }), 'Не удалось изменить показ.') },
          prefs.show_hidden ? 'Не показывать скрытые' : `Показать скрытые (${v.counts.hidden_findings ?? hidden.size})`),
        hidden.size ? h('button', { 'data-pilot': 'review.visibility', class: 'link', disabled: busy, onclick: act(() => client.review.clearHidden(), 'Не удалось вернуть скрытые замечания.') }, 'Вернуть все скрытые') : null));
    }
    wrap.append(h('p', { class: 'muted small foot' }, 'Это подсказки для аналитика: решение, ошибка ли это, принимаете вы. Исправления вносятся вручную.'));
    return wrap;
  }

  function evidenceQuote(id, findingId, e, label, canHighlight) {
      if (!e?.quote) return null;
      const jump = ev => {
        ev.stopPropagation();
        select(id, findingId, true, e);
      };
      return h('blockquote', {
        class: canHighlight ? 'jump' : '',
        title: canHighlight ? 'Показать в тексте' : null,
        role: canHighlight ? 'button' : null,
        tabindex: canHighlight ? '0' : null,
        onclick: jump,
        onkeydown: ev => {
          if (canHighlight && (ev.key === 'Enter' || ev.key === ' ')) {
            ev.preventDefault();
            jump(ev);
          }
        },
      }, label ? h('span', { class: 'lbl' }, label) : null, `«${e.quote}»`);
  }

  function card(id, f, isHidden, canHighlight) {
    const client = app.workspace.client(id);
    const active = st(id).active === f.finding_id;
    const quote = (evidence, label) => evidenceQuote(id, f.finding_id, evidence, label, canHighlight);
    return h('article', { class: `card t-${f.type}${active ? ' active' : ''}${isHidden ? ' is-hidden' : ''}`, 'data-finding': f.finding_id,
      onclick: () => select(id, f.finding_id) },
      h('div', { class: 'card-top' },
        h('span', { class: 'type' }, TYPE_NAME[f.type] || f.type),
        h('span', { class: `conf ${f.assessment}` }, f.assessment === 'red' ? 'Уверенно' : 'Проверьте'),
        isHidden ? h('span', { class: 'pill' }, 'скрыто') : null,
        h('button', { 'data-pilot': 'review.visibility', class: 'icon-btn xs', title: isHidden ? 'Вернуть замечание' : 'Скрыть замечание',
          onclick: ev => { ev.stopPropagation(); act(() => client.review.setHidden(f.finding_id, !isHidden), 'Не удалось изменить видимость замечания.')(); } },
          icon(isHidden ? 'eye' : 'eye-off'))),
      quote(f.primary),
      h('p', { class: 'why' }, f.explanation),
      f.related ? quote(f.related, f.type === 'duplicate' ? 'Похожий фрагмент' : 'Связанный фрагмент') : null,
      f.question ? h('p', { class: 'q' }, h('b', {}, 'Что уточнить: '), f.question) : null);
  }

  return { render, ensureLoaded, onAnalysis, runCheck, select, highlights, reset: () => { lastKey = null; } };
}

export function countLabel(n) { return `${n} ${plural(n, ['замечание', 'замечания', 'замечаний'])}`; }
