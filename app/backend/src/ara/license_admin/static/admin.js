'use strict';
const $ = s => document.querySelector(s);
let csrf = null;
let offset = 0;
let pending = null;
let disableId = null;
let working = false;
const MESSAGES = {
  invalid_login: 'Неверный логин или пароль.',
  try_later: 'Слишком много попыток. Повторите позже.',
  invalid_input: 'Проверьте получателя и срок: целое число от 1 до 36500 дней.',
  issuance_conflict: 'Этот запрос отличается от ранее сохранённого. Обновите список перед новой выдачей.',
  service_unavailable: 'Сервер временно недоступен. Повторите попытку.',
  license_storage_unavailable: 'Не удалось подтвердить сохранение. Повторите тот же запрос.',
  sign_in_required: 'Войдите ещё раз: время сеанса закончилось.',
  csrf_required: 'Сеанс изменился. Обновите страницу и войдите снова.',
};
function message(id, text, success = false) {
  $(id).textContent = text;
  $(id).classList.toggle('success', success);
}
function showLogin() {
  csrf = null;
  $('#workspace').hidden = true;
  $('#logout').hidden = true;
  $('#login-panel').hidden = false;
  $('#login-form').elements.password.value = '';
  if ($('#key-dialog').open) $('#key-dialog').close();
}
async function api(action, value) {
  const headers = {'X-AIRA-Admin-Request': '1'};
  if (value !== undefined) {
    headers['Content-Type'] = 'application/json';
    if (csrf) headers['X-AIRA-Admin-CSRF'] = csrf;
  }
  let reply;
  try {
    reply = await fetch('./api/' + action, {
      method: value === undefined ? 'GET' : 'POST', headers,
      credentials: 'same-origin', cache: 'no-store',
      ...(value === undefined ? {} : {body: JSON.stringify(value)}),
      signal: AbortSignal.timeout(15000),
    });
  } catch { throw new Error('service_unavailable'); }
  let result;
  try { result = await reply.json(); } catch { throw new Error('service_unavailable'); }
  if (!reply.ok) {
    if (reply.status === 401 && action !== 'login') showLogin();
    throw new Error(result.code || 'service_unavailable');
  }
  return result;
}
function errorText(error) { return MESSAGES[error.message] || 'Не удалось выполнить действие. Повторите попытку.'; }
const date = value => value === null ? 'После активации' : new Date(value).toLocaleDateString('ru-RU');
const STATUS = {unactivated: 'Не активирована', active: 'Действует', expired: 'Истекла', disabled: 'Отключена'};
function cell(text, cls) { const el = document.createElement('td'); el.textContent = text; if (cls) el.className = cls; return el; }
function draw(rows, more) {
  const list = $('#license-list');
  list.replaceChildren();
  for (const license of rows) {
    const row = document.createElement('tr');
    const label = cell(license.label);
    const identifier = document.createElement('span');
    identifier.className = 'identifier'; identifier.textContent = 'Выдана ' + date(license.created_at_ms) + ' · ID ' + license.id.slice(-8); label.append(identifier);
    const state = cell(''); const badge = document.createElement('span');
    badge.className = 'badge ' + license.status; badge.textContent = STATUS[license.status] || 'Неизвестно'; state.append(badge);
    const action = cell(''); const button = document.createElement('button');
    button.className = 'table-action'; button.textContent = 'Отключить'; button.disabled = license.status === 'disabled';
    button.addEventListener('click', () => {
      disableId = license.id;
      $('#disable-description').textContent = license.label;
      $('#disable-dialog').showModal();
    });
    action.append(button);
    row.append(label, state, cell(license.days < 1 ? 'Меньше дня' : license.days.toLocaleString('ru-RU') + ' дн.'), cell(date(license.expires_at_ms)), action);
    list.append(row);
  }
  $('#empty').hidden = rows.length !== 0;
  $('#list-count').textContent = rows.length + (more ? '+' : '');
  $('#previous').disabled = offset === 0;
  $('#next').disabled = !more;
  $('#page-label').textContent = rows.length ? `${offset + 1}–${offset + rows.length}` : '';
}
async function load() {
  const state = await api('state?offset=' + offset);
  csrf = state.csrf;
  $('#login-panel').hidden = true;
  $('#workspace').hidden = false;
  $('#logout').hidden = false;
  draw(state.licenses, state.more);
  message('#list-message', '');
}
function busy(value) {
  working = value;
  $('#issue-button').disabled = value;
  $('#issue-button').textContent = value ? 'Сохраняем…' : pending ? 'Повторить создание' : 'Создать ключ';
  $('#issue-form').elements.label.readOnly = !!pending;
  $('#issue-form').elements.days.readOnly = !!pending;
}
$('#login-form').addEventListener('submit', async event => {
  event.preventDefault();
  $('#login-button').disabled = true;
  const form = event.target;
  try {
    await api('login', {username: form.elements.username.value.trim(), password: form.elements.password.value});
    form.elements.password.value = '';
    await load(); message('#login-message', '');
  } catch (error) { message('#login-message', errorText(error)); }
  finally { $('#login-button').disabled = false; }
});
$('#issue-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (working) return;
  if (!pending) {
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    const hex = Array.from(bytes, n => n.toString(16).padStart(2, '0')).join('').toUpperCase();
    pending = {identifier: crypto.randomUUID(), key: 'AIRA-' + hex.match(/.{8}/g).join('-'), days: Number(event.target.elements.days.value), label: event.target.elements.label.value.trim()};
  }
  busy(true); message('#issue-message', '');
  try {
    await api('issue', pending);
    $('#issued-key').value = pending.key;
    $('#key-description').textContent = `${pending.label} · ${pending.days} дней с первой активации.`;
    pending = null;
    message('#copy-message', '');
    $('#key-dialog').showModal();
    message('#issue-message', 'Лицензия создана.', true);
    try { offset = 0; await load(); } catch { message('#list-message', 'Ключ создан, но список не обновился. Нажмите «Обновить список».'); }
  } catch (error) {
    if (['invalid_input', 'issuance_conflict'].includes(error.message)) pending = null;
    message('#issue-message', errorText(error) + (pending ? ' Повтор использует тот же ключ и не создаёт вторую лицензию.' : '')); 
    if (error.message === 'sign_in_required') message('#login-message', errorText(error));
  } finally { busy(false); }
});
$('#copy-key').addEventListener('click', async () => {
  try { await navigator.clipboard.writeText($('#issued-key').value); message('#copy-message', 'Ключ скопирован.', true); }
  catch { $('#issued-key').focus(); $('#issued-key').select(); message('#copy-message', 'Нажмите ⌘C на Mac или Ctrl+C на Windows, чтобы скопировать выделенный ключ.'); }
});
$('#close-key').addEventListener('click', () => $('#key-dialog').close());
$('#key-dialog').addEventListener('close', () => { $('#issued-key').value = ''; });
$('#cancel-disable').addEventListener('click', () => $('#disable-dialog').close());
$('#confirm-disable').addEventListener('click', async () => {
  $('#confirm-disable').disabled = true;
  try { await api('disable', {identifier: disableId}); $('#disable-dialog').close(); await load(); }
  catch (error) { $('#disable-dialog').close(); message('#list-message', errorText(error)); }
  finally { $('#confirm-disable').disabled = false; }
});
$('#logout').addEventListener('click', async () => {
  try { await api('logout', {}); pending = null; busy(false); showLogin(); message('#login-message', 'Вы вышли.', true); }
  catch (error) { message('#list-message', errorText(error)); }
});
$('#refresh').addEventListener('click', () => load().catch(error => message('#list-message', errorText(error))));
$('#next').addEventListener('click', () => { offset += 50; load().catch(error => message('#list-message', errorText(error))); });
$('#previous').addEventListener('click', () => { offset = Math.max(0, offset - 50); load().catch(error => message('#list-message', errorText(error))); });
load().catch(error => { showLogin(); message('#login-message', error.message === 'sign_in_required' ? '' : errorText(error)); });
