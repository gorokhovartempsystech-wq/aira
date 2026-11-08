// Сурикат — маскот AIRA. Один SVG с настроениями:
//   idle — стоит и моргает, happy — улыбается, wave — машет лапой,
//   surprised — глаза круглые, лапы у щёк (ошибки и предупреждения).
// Взгляд и наклон головы задаются через look(svg, dx, dy).
// Также здесь всплывающий из норки сурикат, который показывает ошибку.

import { h } from './ui.mjs';

const NS = 'http://www.w3.org/2000/svg';

// Константная разметка без пользовательских данных. Без id, чтобы сурикатов на странице могло быть несколько.
const ART = `
<g class="mk-all">
  <path class="mk-tail" d="M74 136 C 92 142 106 136 110 120"/>
  <path class="mk-tail-tip" d="M108.6 125.4 C 109.5 123.4 110 121.6 110 120"/>
  <path class="mk-fur" d="M60 70 C 43 70 36 88 36 106 C 36 126 44 140 60 140 C 76 140 84 126 84 106 C 84 88 77 70 60 70 Z"/>
  <path class="mk-cream" d="M60 84 C 50 84 47 98 47 110 C 47 126 52 135 60 135 C 68 135 73 126 73 110 C 73 98 70 84 60 84 Z"/>
  <ellipse class="mk-dark-fur" cx="48" cy="140.5" rx="10" ry="4.5"/>
  <ellipse class="mk-dark-fur" cx="72" cy="140.5" rx="10" ry="4.5"/>
  <path class="mk-scarf" d="M44 74 C 52 80 68 80 76 74 L74 81 C 70 84 66 85 63.5 85.5 L60 106 L56.5 85.5 C 54 85 50 84 46 81 Z"/>
  <circle class="mk-scarf-knot" cx="60" cy="84.5" r="2.6"/>

  <g class="only s-idle s-happy s-wave">
    <path class="mk-arm" d="M45 86 C 44 94 46 99 52 101"/>
    <ellipse class="mk-paw" cx="53" cy="102.5" rx="5" ry="4"/>
  </g>
  <g class="only s-idle s-happy">
    <path class="mk-arm" d="M75 86 C 76 94 74 99 68 101"/>
    <ellipse class="mk-paw" cx="67" cy="102.5" rx="5" ry="4"/>
  </g>
  <g class="only s-wave mk-waving">
    <path class="mk-arm" d="M75 86 C 84 81 90 72 92 62"/>
    <ellipse class="mk-paw" cx="92.5" cy="58.5" rx="5" ry="5.5"/>
  </g>

  <g class="mk-head">
    <circle class="mk-ear" cx="31" cy="40" r="7"/>
    <circle class="mk-ear" cx="89" cy="40" r="7"/>
    <circle class="mk-ear-in" cx="31.5" cy="40.5" r="3.4"/>
    <circle class="mk-ear-in" cx="88.5" cy="40.5" r="3.4"/>
    <path class="mk-face" d="M60 20 C 79 20 90 32 90 46 C 90 62 76 76 60 78 C 44 76 30 62 30 46 C 30 32 41 20 60 20 Z"/>
    <path class="mk-crown" d="M42 26 C 50 19 70 19 78 26 C 72 31 66 32 60 32 C 54 32 48 31 42 26 Z"/>
    <path class="mk-patch" d="M35 44 C 35 36 43 33 49 35 C 55 37 57 44 55 50 C 53 56 47 59 43 57 C 38 54 35 50 35 44 Z"/>
    <path class="mk-patch" d="M85 44 C 85 36 77 33 71 35 C 65 37 63 44 65 50 C 67 56 73 59 77 57 C 82 54 85 50 85 44 Z"/>

    <g class="only s-idle mk-blink">
      <g class="mk-pupil"><circle class="mk-eye" cx="46" cy="46" r="6"/><circle class="mk-shine" cx="48" cy="43.8" r="1.9"/><circle class="mk-shine" cx="44.2" cy="48.2" r=".9"/></g>
      <g class="mk-pupil"><circle class="mk-eye" cx="74" cy="46" r="6"/><circle class="mk-shine" cx="76" cy="43.8" r="1.9"/><circle class="mk-shine" cx="72.2" cy="48.2" r=".9"/></g>
    </g>
    <g class="only s-surprised">
      <circle class="mk-white" cx="46" cy="45" r="7.6"/>
      <circle class="mk-white" cx="74" cy="45" r="7.6"/>
      <g class="mk-pupil"><circle class="mk-eye" cx="46" cy="45" r="3.3"/><circle class="mk-shine" cx="47.2" cy="43.8" r="1.1"/></g>
      <g class="mk-pupil"><circle class="mk-eye" cx="74" cy="45" r="3.3"/><circle class="mk-shine" cx="75.2" cy="43.8" r="1.1"/></g>
      <path class="mk-line" d="M38 31 Q45 25.5 52 29.5"/>
      <path class="mk-line" d="M82 31 Q75 25.5 68 29.5"/>
    </g>
    <g class="only s-happy s-wave">
      <path class="mk-line thick" d="M40 47.5 Q46 40.5 52 47.5"/>
      <path class="mk-line thick" d="M68 47.5 Q74 40.5 80 47.5"/>
    </g>

    <g class="mk-glasses">
      <path class="mk-frame" d="M36.5 44.5 L30.5 41.5 M83.5 44.5 L89.5 41.5"/>
      <path class="mk-frame" d="M55.4 45 Q60 41.6 64.6 45"/>
      <circle class="mk-lens" cx="46" cy="46" r="9.6"/>
      <circle class="mk-lens" cx="74" cy="46" r="9.6"/>
      <path class="mk-glint" d="M40.2 41.6 Q42.4 38.6 46 38.2 M68.2 41.6 Q70.4 38.6 74 38.2"/>
    </g>
    <ellipse class="mk-cream" cx="60" cy="64" rx="13" ry="10"/>
    <ellipse class="mk-blush" cx="39" cy="60" rx="4.2" ry="2.6"/>
    <ellipse class="mk-blush" cx="81" cy="60" rx="4.2" ry="2.6"/>
    <path class="mk-nose" d="M55.5 57 Q60 54.5 64.5 57 Q63 61.5 60 62 Q57 61.5 55.5 57 Z"/>
    <path class="mk-line thin" d="M60 62 L60 64.8"/>
    <path class="only s-idle mk-line thin" d="M54.5 65.5 Q57.2 68.5 60 65.5 Q62.8 68.5 65.5 65.5"/>
    <g class="only s-happy s-wave">
      <path class="mk-nose" d="M53.5 65 Q60 73.5 66.5 65 Z"/>
      <path class="mk-tongue" d="M56.6 68.6 Q60 71.6 63.4 68.6 Q60 67.2 56.6 68.6 Z"/>
    </g>
    <ellipse class="only s-surprised mk-nose" cx="60" cy="69.5" rx="3.2" ry="4"/>
  </g>

  <g class="only s-surprised">
    <path class="mk-arm" d="M45 86 C 38 82 34 77 33 70"/>
    <ellipse class="mk-paw" cx="33" cy="66.5" rx="5" ry="6"/>
    <path class="mk-arm" d="M75 86 C 82 82 86 77 87 70"/>
    <ellipse class="mk-paw" cx="87" cy="66.5" rx="5" ry="6"/>
  </g>
  <g class="only s-surprised mk-shock">
    <path d="M96 17 L100 9"/><path d="M101.5 26 L109.5 22.5"/><path d="M89 12.5 L89.5 4"/>
  </g>
</g>`;

export const MOODS = ['idle', 'happy', 'wave', 'surprised'];

export function meerkat({ mood = 'idle', size = 96, label = null } = {}) {
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', '0 0 120 150');
  svg.setAttribute('width', String(size));
  svg.setAttribute('height', String(Math.round(size * 1.25)));
  if (label) { svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', label); }
  else svg.setAttribute('aria-hidden', 'true');
  svg.innerHTML = ART;
  setMood(svg, mood);
  return svg;
}

export function setMood(svg, mood) {
  for (const m of MOODS) svg.classList.remove(`mood-${m}`);
  svg.classList.add('meerkat', `mood-${MOODS.includes(mood) ? mood : 'idle'}`);
}

// dx, dy от −1 до 1: куда смотрит сурикат (зрачки и лёгкий наклон головы).
export function look(svg, dx = 0, dy = 0) {
  const c = v => Math.max(-1, Math.min(1, Number(v) || 0));
  svg.style.setProperty('--lx', c(dx).toFixed(2));
  svg.style.setProperty('--ly', c(dy).toFixed(2));
}

// Направление от сурика к точке на экране.
export function lookAt(svg, x, y) {
  const r = svg.getBoundingClientRect();
  const cx = r.left + r.width / 2, cy = r.top + r.height * 0.32;
  const dx = x - cx, dy = y - cy, d = Math.hypot(dx, dy) || 1;
  look(svg, dx / d, dy / d);
}

/* ---------- «Ой-ёй!» ---------- */
// Голос Windows на русском, если он есть; иначе — короткий мультяшный сигнал. Не чаще раза в 3 секунды.
export const sound = {
  get on() { try { return localStorage.getItem('aira.sound') !== 'off'; } catch { return true; } },
  set on(v) { try { localStorage.setItem('aira.sound', v ? 'on' : 'off'); } catch { /* только на этот сеанс */ } },
};
let lastSound = 0, audio = null;
try { window.speechSynthesis?.getVoices(); } catch { /* голоса подгрузятся позже */ }

export function oyoy(force = false) {
  if ((!sound.on && !force) || Date.now() - lastSound < 3000) return;
  lastSound = Date.now();
  try {
    const synth = window.speechSynthesis;
    const voices = synth ? synth.getVoices() : [];
    const ru = voices.find(v => /^ru/i.test(v.lang) && v.localService) || voices.find(v => /^ru/i.test(v.lang));
    if (ru) {
      const u = new SpeechSynthesisUtterance('Ой-ёй!');
      Object.assign(u, { voice: ru, lang: ru.lang, rate: 1.2, pitch: 1.7, volume: 0.9 });
      synth.cancel();
      synth.speak(u);
      return;
    }
  } catch { /* перейдём на сигнал */ }
  chirp();
}

function chirp() {
  try {
    audio ||= new (window.AudioContext || window.webkitAudioContext)();
    const t = audio.currentTime + 0.01;
    // «ой» — вверх-вниз, «ёй» — ниже и с удивлённым подъёмом в конце
    [[t, 0.17, 620, 880, 560], [t + 0.21, 0.24, 520, 760, 430]].forEach(([at, len, f0, f1, f2]) => {
      const osc = audio.createOscillator(), gain = audio.createGain();
      osc.type = 'triangle';
      osc.frequency.setValueAtTime(f0, at);
      osc.frequency.linearRampToValueAtTime(f1, at + len * 0.35);
      osc.frequency.exponentialRampToValueAtTime(f2, at + len);
      gain.gain.setValueAtTime(0.0001, at);
      gain.gain.exponentialRampToValueAtTime(0.22, at + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, at + len);
      osc.connect(gain).connect(audio.destination);
      osc.start(at);
      osc.stop(at + len + 0.02);
    });
  } catch { /* без звука */ }
}

/* ---------- Сурикат выглядывает из норки и показывает ошибку ---------- */
let pop = null;

const TITLES = { error: 'Ой, что-то пошло не так', warn: 'Так не получится' };

export function mascotAlert(message, kind = 'error', { action = null, ms = 6000 } = {}) {
  oyoy();
  // Для журнала диагностики (main.mjs отправляет в aira.log): что именно увидел пользователь.
  window.dispatchEvent(new CustomEvent('aira:alert', { detail: { kind, message } }));
  if (!pop) pop = buildPop();
  const p = pop;
  clearTimeout(p.timer);
  p.el.className = `mk-pop ${kind === 'warn' ? 'warn' : 'error'}`;
  p.el.setAttribute('role', kind === 'error' ? 'alert' : 'status');
  p.title.textContent = TITLES[kind] || TITLES.error;
  p.msg.textContent = message;
  // replaceChildren(null) вставил бы текст «null», поэтому пустые элементы отфильтровываются.
  p.actions.replaceChildren(...[
    action ? h('button', { class: 'btn sm primary', type: 'button', onclick: () => { hidePop(); action.run(); } }, action.label) : null,
    h('button', { class: 'btn sm', type: 'button', onclick: () => hidePop() }, 'Понятно')].filter(Boolean));
  document.body.classList.add('mk-on');
  // Перезапуск анимации: при новой ошибке сурикат снова вздрагивает.
  void p.el.offsetWidth;
  p.el.classList.add('in');
  requestAnimationFrame(() => {
    const b = p.bubble.getBoundingClientRect();
    lookAt(p.svg, b.left + b.width * 0.6, b.top + b.height * 0.4);
  });
  p.wait = Math.max(ms, kind === 'error' ? 8000 : 5000);
  p.timer = setTimeout(hidePop, p.wait);
  return p.el;
}

function buildPop() {
  const svg = meerkat({ mood: 'surprised', size: 96 });
  const title = h('strong', { class: 'mk-title' });
  const msg = h('p', { class: 'mk-msg' });
  const actions = h('div', { class: 'mk-actions' });
  const bubble = h('div', { class: 'mk-bubble' }, title, msg, actions);
  const stage = h('div', { class: 'mk-stage' }, h('div', { class: 'mk-hole' }), h('div', { class: 'mk-clip' }, svg), h('div', { class: 'mk-lip' }));
  const el = h('div', { class: 'mk-pop' }, bubble, stage);
  const p = { el, svg, title, msg, actions, bubble, timer: null, wait: 6000 };
  el.addEventListener('mouseenter', () => clearTimeout(p.timer));
  el.addEventListener('mouseleave', () => { clearTimeout(p.timer); p.timer = setTimeout(hidePop, 2500); });
  el.addEventListener('keydown', e => { if (e.key === 'Escape') hidePop(); });
  document.body.append(el);
  return p;
}

export function hidePop() {
  const p = pop;
  if (!p) return;
  pop = null;
  clearTimeout(p.timer);
  p.el.classList.remove('in');
  p.el.classList.add('out');
  document.body.classList.remove('mk-on');
  setTimeout(() => p.el.remove(), 450);
}
