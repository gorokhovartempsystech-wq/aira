// Small DOM helpers. Text always goes through textContent / text nodes, never innerHTML.
import { mascotAlert } from './mascot.mjs';

export const $ = (s, r = document) => r.querySelector(s);
export const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, '');
    else el.setAttribute(k, String(v));
  }
  append(el, children);
  return el;
}
function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

export function icon(name, cls = 'i') {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', cls);
  svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', `#i-${name}`);
  svg.append(use);
  return svg;
}

// Backend offsets are Unicode code points; DOM offsets are UTF-16 units.
export const cpLen = s => { let n = 0; for (const _ of s) n++; return n; };
export function cpToU16(s, cp) {
  let i = 0, n = 0;
  for (const ch of s) { if (n === cp) return i; i += ch.length; n++; }
  return s.length;
}
export function u16ToCp(s, u16) { return cpLen(s.slice(0, u16)); }

export const sleep = ms => new Promise(r => setTimeout(r, ms));

const pad = n => String(n).padStart(2, '0');
const MONTHS = ['янв.', 'февр.', 'марта', 'апр.', 'мая', 'июня', 'июля', 'авг.', 'сент.', 'окт.', 'нояб.', 'дек.'];
export function fmtTime(value) {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '';
  const now = new Date();
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  if (d.toDateString() === now.toDateString()) return `сегодня, ${hm}`;
  const y = new Date(now); y.setDate(now.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return `вчера, ${hm}`;
  return `${d.getDate()} ${MONTHS[d.getMonth()]}${d.getFullYear() !== now.getFullYear() ? ' ' + d.getFullYear() : ''}, ${hm}`;
}
export const fmtClock = ms => { const s = Math.max(0, Math.floor(ms / 1000)); return `${Math.floor(s / 60)}:${pad(s % 60)}`; };

export function plural(n, forms) {
  const a = Math.abs(n) % 100, b = a % 10;
  if (a > 10 && a < 20) return forms[2];
  if (b > 1 && b < 5) return forms[1];
  if (b === 1) return forms[0];
  return forms[2];
}

/* ---------- Toasts ---------- */
// Ошибки и предупреждения показывает сурикат (выглядывает из норки), остальное — обычные всплывающие строки.
export function toast(message, kind = 'info', { action = null, ms = 4000 } = {}) {
  if (kind === 'error' || kind === 'warn') { mascotAlert(message, kind, { action, ms }); return; }
  const box = $('#toasts');
  const t = h('div', { class: `toast ${kind}`, role: kind === 'error' ? 'alert' : 'status' },
    icon(kind === 'ok' ? 'check' : kind === 'info' ? 'info' : 'alert'), h('span', {}, message));
  if (action) t.append(h('button', { class: 'link', onclick: () => { t.remove(); action.run(); } }, action.label));
  box.append(t);
  while (box.children.length > 4) box.firstElementChild.remove();
  setTimeout(() => { t.classList.add('out'); setTimeout(() => t.remove(), 300); }, ms);
}

/* ---------- Modal ---------- */
// Resolves {id, value} or null. `input` adds a text field; Enter submits the primary action.
export function modal({ title, body = null, actions, input = null, wide = false, dismissable = true }) {
  return new Promise(resolve => {
    const field = input ? h('input', { class: 'input', type: 'text', value: input.value || '',
      placeholder: input.placeholder || '', maxlength: input.maxLength || 400, 'aria-label': input.label || title }) : null;
    const hint = input ? h('p', { class: 'field-error', hidden: true }) : null;
    const box = h('div', { class: `modal${wide ? ' wide' : ''}`, role: 'dialog', 'aria-modal': 'true', 'aria-label': title },
      h('h2', {}, title),
      body === null ? null : h('div', { class: 'modal-body' }, typeof body === 'string' ? h('p', {}, body) : body),
      input ? h('label', { class: 'field' }, input.label ? h('span', {}, input.label) : null, field, hint) : null,
      h('div', { class: 'modal-actions' }, actions.map(a =>
        h('button', { class: `btn ${a.kind || ''}`, 'data-id': a.id, type: 'button' }, a.label))));
    const scrim = h('div', { class: 'scrim' }, box);
    const previous = document.activeElement;
    function close(result) {
      scrim.remove();
      document.removeEventListener('keydown', onKey, true);
      if (previous && previous.focus) try { previous.focus(); } catch { /* gone */ }
      resolve(result);
    }
    function submit(id) {
      const a = actions.find(x => x.id === id);
      if (input && a?.kind?.includes('primary')) {
        const v = field.value.trim();
        const err = input.validate ? input.validate(v) : (v ? null : 'Введите значение');
        if (err) { hint.textContent = err; hint.hidden = false; field.focus(); return; }
        close({ id, value: v });
      } else close({ id, value: field ? field.value.trim() : null });
    }
    function onKey(e) {
      if (e.key === 'Escape' && dismissable) { e.preventDefault(); e.stopPropagation(); close(null); }
      else if (e.key === 'Enter' && e.target === field) {
        e.preventDefault();
        const p = actions.find(a => a.kind?.includes('primary'));
        if (p) submit(p.id);
      }
    }
    box.addEventListener('click', e => { const b = e.target.closest('[data-id]'); if (b) submit(b.dataset.id); });
    scrim.addEventListener('mousedown', e => { if (e.target === scrim && dismissable) close(null); });
    document.addEventListener('keydown', onKey, true);
    $('#modal-root').append(scrim);
    if (field) { field.focus(); field.select(); }
    else (box.querySelector('.btn.primary') || box.querySelector('.btn'))?.focus();
  });
}

export function overlay(text) {
  const el = h('div', { class: 'scrim blocking' }, h('div', { class: 'blocking-box' }, h('span', { class: 'spinner' }), h('p', {}, text)));
  $('#modal-root').append(el);
  return { set(t) { el.querySelector('p').textContent = t; }, close() { el.remove(); } };
}
