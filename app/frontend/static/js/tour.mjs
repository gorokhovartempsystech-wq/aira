// Начальное обучение: сурикат по шагам подсвечивает части интерфейса и смотрит на них.
// Шаг: { target?, title, text: string | string[], extra?: () => Node, mood?, side?, pad?, before?,
//        nextLabel?, action?: {label, run} (кнопка рядом с «Далее»), onDone? + laterLabel? (на последнем шаге) }

import { h, icon } from './ui.mjs';
import { meerkat, setMood, look } from './mascot.mjs';

let current = null;
export const tourActive = () => current !== null;
export function closeTour() { current?.finish(false); }

export function runTour(steps, { onFinish = () => {} } = {}) {
  closeTour();
  let i = 0, nextBtn = null, timer = 0;
  const spot = h('div', { class: 'tour-spot' });
  const svg = meerkat({ mood: 'wave', size: 92 });
  const card = h('div', { class: 'tour-card' }, svg);
  const root = h('div', { class: 'tour', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Знакомство с AIRA' }, spot, card);
  const previous = document.activeElement;

  const visibleRect = sel => {
    const el = sel ? document.querySelector(sel) : null;
    if (!el) return null;
    const r = el.getBoundingClientRect();
    const left = Math.max(0, r.left), top = Math.max(0, r.top);
    const right = Math.min(innerWidth, r.right), bottom = Math.min(innerHeight, r.bottom);
    return right - left > 2 && bottom - top > 2 ? { left, top, right, bottom, width: right - left, height: bottom - top } : null;
  };

  function show(n) {
    i = Math.max(0, Math.min(steps.length - 1, n));
    clearTimeout(timer);
    const step = steps[i];
    if (step.before) { step.before(); timer = setTimeout(draw, 120); }
    else draw();
  }

  function draw() {
    const step = steps[i];
    const last = i === steps.length - 1;
    const texts = [].concat(step.text || []);
    nextBtn = h('button', { class: 'btn primary sm', type: 'button', onclick: () => {
      if (!last) return show(i + 1);
      finish(true);
      step.onDone?.();
    } }, step.nextLabel || (last ? 'Готово' : 'Далее'));
    const bubble = h('div', { class: 'tour-bubble' },
      h('button', { class: 'icon-btn xs tour-close', type: 'button', title: 'Закрыть обучение', 'aria-label': 'Закрыть обучение', onclick: () => finish(true) }, icon('x')),
      h('div', { class: 'tour-step' }, `Шаг ${i + 1} из ${steps.length}`),
      h('h3', {}, step.title),
      texts.map(t => h('p', {}, t)),
      step.extra ? step.extra() : null,
      h('div', { class: 'tour-foot' },
        h('div', { class: 'tour-dots', 'aria-hidden': 'true' }, steps.map((_, k) => h('i', { class: k === i ? 'on' : null }))),
        h('div', { class: 'tour-btns' },
          i > 0 ? h('button', { class: 'btn sm', type: 'button', onclick: () => show(i - 1) }, 'Назад') : null,
          step.action ? h('button', { class: 'btn sm', type: 'button', onclick: () => step.action.run() }, step.action.label) : null,
          last && step.laterLabel ? h('button', { class: 'btn sm', type: 'button', onclick: () => finish(true) }, step.laterLabel) : null,
          nextBtn)));
    card.querySelector('.tour-bubble')?.remove();
    card.append(bubble);
    setMood(svg, step.mood || 'idle');
    place();
    nextBtn.focus({ preventScroll: true });
  }

  function place() {
    const step = steps[i];
    const r = visibleRect(step.target);
    const vw = innerWidth, vh = innerHeight, M = 12, G = 14, pad = step.pad ?? 6;
    root.classList.toggle('is-center', !r);
    const size = r ? 92 : 124;
    svg.setAttribute('width', String(size));
    svg.setAttribute('height', String(Math.round(size * 1.25)));
    const cw = card.offsetWidth, ch = card.offsetHeight;
    let left = (vw - cw) / 2, top = (vh - ch) / 2;
    if (!r) {
      Object.assign(spot.style, { left: `${vw / 2}px`, top: `${vh / 2}px`, width: '0px', height: '0px' });
    } else {
      Object.assign(spot.style, { left: `${r.left - pad}px`, top: `${r.top - pad}px`, width: `${r.width + 2 * pad}px`, height: `${r.height + 2 * pad}px` });
      const cx = x => Math.max(M, Math.min(vw - cw - M, x)), cy = y => Math.max(M, Math.min(vh - ch - M, y));
      const options = {
        below: [cx(r.left + r.width / 2 - cw / 2), r.bottom + pad + G, r.bottom + pad + G + ch <= vh - M],
        above: [cx(r.left + r.width / 2 - cw / 2), r.top - pad - G - ch, r.top - pad - G - ch >= M],
        right: [r.right + pad + G, cy(r.top + r.height / 2 - ch / 2), r.right + pad + G + cw <= vw - M],
        left: [r.left - pad - G - cw, cy(r.top + r.height / 2 - ch / 2), r.left - pad - G - cw >= M],
      };
      const order = [step.side, 'below', 'above', 'right', 'left'].filter(Boolean);
      const pick = order.map(k => options[k]).find(o => o && o[2]);
      if (pick) [left, top] = pick;
      else top = vh - ch - M;
    }
    card.style.left = `${Math.round(left)}px`;
    card.style.top = `${Math.round(top)}px`;
    // Сурикат смотрит на подсвеченное место, на центральных шагах — на пользователя.
    if (r) {
      const sw = size, sh = size * 1.25;
      const mx = left + sw / 2, my = top + ch - sh * 0.7;
      const dx = r.left + r.width / 2 - mx, dy = r.top + r.height / 2 - my, d = Math.hypot(dx, dy) || 1;
      look(svg, dx / d, dy / d);
    } else look(svg, 0, 0.2);
  }

  function onKey(e) {
    if (e.target.closest?.('.mk-pop')) return;
    if (e.key === 'Escape') { e.preventDefault(); finish(true); }
    else if (e.key === 'ArrowRight' && i < steps.length - 1) { e.preventDefault(); show(i + 1); }
    else if (e.key === 'ArrowLeft' && i > 0) { e.preventDefault(); show(i - 1); }
    else if (e.key === 'Tab' || e.key === 'Enter' || e.key === ' ') return;
    // Пока идёт обучение, горячие клавиши приложения не срабатывают.
    e.stopPropagation();
    if (e.ctrlKey || e.metaKey) e.preventDefault();
  }
  function onFocus(e) {
    if (!root.contains(e.target) && !e.target.closest?.('.mk-pop')) nextBtn?.focus({ preventScroll: true });
  }
  const onResize = () => place();

  function finish(done) {
    if (current !== api) return;
    current = null;
    clearTimeout(timer);
    document.removeEventListener('keydown', onKey, true);
    document.removeEventListener('focusin', onFocus, true);
    removeEventListener('resize', onResize);
    root.classList.add('out');
    setTimeout(() => root.remove(), 200);
    try { previous?.focus?.({ preventScroll: true }); } catch { /* gone */ }
    onFinish(done);
  }

  const api = { finish };
  current = api;
  document.addEventListener('keydown', onKey, true);
  document.addEventListener('focusin', onFocus, true);
  addEventListener('resize', onResize);
  document.body.append(root);
  show(0);
  return api;
}
