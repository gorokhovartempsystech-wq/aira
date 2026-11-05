import {DocxClientError, requireValue, uuid} from './protocol.mjs';

export const WORKSPACE_REQUEST_TIMEOUT_MS = 30000;
const REPLY_LIMIT = 16 * 1024 * 1024 + 65536;

function record(raw, allowed, required = allowed) {
  requireValue(raw !== null && typeof raw === 'object' && !Array.isArray(raw));
  requireValue([Object.prototype, null].includes(Object.getPrototypeOf(raw)));
  const result = Object.create(null);
  for (const key of Reflect.ownKeys(raw)) {
    requireValue(typeof key === 'string' && allowed.includes(key));
    const field = Object.getOwnPropertyDescriptor(raw, key);
    requireValue(field.enumerable && Object.hasOwn(field, 'value'));
    result[key] = field.value;
  }
  requireValue(required.every(key => Object.hasOwn(result, key)));
  return result;
}
function ignoreCancellation(stream) {
  try { Promise.resolve(stream?.cancel()).catch(() => {}); } catch (_) { /* Best effort. */ }
}
function responseValue(ok) { requireValue(ok, 'invalid_response'); }
function jsonMedia(value) {
  if (typeof value !== 'string') return false;
  const parts = value.toLowerCase().split(';').map(x => x.trim());
  return parts[0] === 'application/json' && (parts.length === 1
    || (parts.length === 2 && parts[1].replaceAll(' ', '') === 'charset=utf-8'));
}

// This factory receives a trusted live host connection. It never discovers credentials.
export function createWorkspaceTransport(options) {
  let origin, token, prefix, fetchImpl, schedule, cancel;
  try {
    const o = record(options, ['origin', 'sessionToken',
      'fetchImpl', 'schedule', 'cancel'], ['origin', 'sessionToken']);
    origin = o.origin; token = o.sessionToken;
    requireValue(typeof origin === 'string');
    const port = /^http:\/\/127\.0\.0\.1:([1-9][0-9]{3,4})$/.exec(origin);
    requireValue(port !== null && port[0] === origin && Number(port[1]) >= 1024
      && Number(port[1]) <= 65535);
    requireValue(typeof token === 'string' && token.length === 64 && /^[0-9a-f]{64}$/.test(token));
    prefix = `/docx-documents/`;
    fetchImpl = o.fetchImpl === undefined ? ((...args) => globalThis.fetch(...args)) : o.fetchImpl;
    schedule = o.schedule === undefined ? ((fn, ms) => setTimeout(fn, ms)) : o.schedule;
    cancel = o.cancel === undefined ? (id => clearTimeout(id)) : o.cancel;
    for (const fn of [fetchImpl, schedule, cancel]) requireValue(typeof fn === 'function');
  } catch (_) { throw new DocxClientError('invalid_input'); }
  const active = new Set();
  return Object.freeze(async function send(request) {
    let path, body, method, lane;
    try {
      ({path, body, method} = record(request, ['path', 'body', 'method'], ['path', 'method']));
      requireValue(typeof path === 'string' && path.startsWith(prefix));
      const route = path.slice(prefix.length), pieces = route.split('/');
      uuid(pieces.shift());
      let allowed = false;
      if (pieces.length === 1 && pieces[0] === 'editor-recovery') allowed = method === 'GET';
      else if (pieces.length === 1 && pieces[0] === 'editor-sessions') allowed = method === 'POST';
      else if (pieces[0] === 'editor-sessions' && pieces.length >= 2) {
        uuid(pieces[1]);
        allowed = (method === 'GET' && (pieces.length === 2 || (pieces.length === 3 && pieces[2] === 'view')))
          || (method === 'POST' && pieces.length === 3 && ['close','reconcile'].includes(pieces[2]));
      }
      requireValue(allowed);
      if (method === 'GET') requireValue(body === undefined);
      else {
        requireValue(typeof body === 'string' && body.length <= 65536);
        for (const c of body) {
          const point = c.codePointAt(0);
          requireValue(point < 0xd800 || point > 0xdfff);
        }
        requireValue(new TextEncoder().encode(body).length <= 65536);
      }
      lane = 'ordinary';
    } catch (_) { throw new DocxClientError('invalid_input'); }
    requireValue(!active.has(lane), 'busy');
    active.add(lane);
    let controller, reader, timer, timerSet = false, done = false, complete = false;
    try {
      controller = new AbortController();
      let expire;
      const deadline = new Promise((_, reject) => { expire = reject; });
      timer = schedule(() => {
        if (done) return;
        controller.abort();
        expire(new DocxClientError('transport_error'));
      }, WORKSPACE_REQUEST_TIMEOUT_MS);
      timerSet = true;
      async function receive() {
        const response = await fetchImpl(origin + path, {
          method, body, headers: {'Content-Type': 'application/json',
            Accept: 'application/json', 'X-AIRA-Session': token},
          redirect: 'error', credentials: 'omit', cache: 'no-store',
          referrerPolicy: 'no-referrer', mode: 'same-origin', signal: controller.signal
        });
        // A nonconforming/injected fetch may settle after cancellation. Never consume it.
        if (done || controller.signal.aborted) {
          ignoreCancellation(response?.body);
          throw new DocxClientError('transport_error');
        }
        try {
          responseValue(Number.isInteger(response.status) && response.status >= 200
            && response.status <= 599 && (response.status < 300 || response.status >= 400));
          responseValue(response.url === origin + path && response.redirected === false
            && ['basic', 'default'].includes(response.type));
          responseValue(jsonMedia(response.headers.get('Content-Type')));
          responseValue([null, 'identity'].includes(response.headers.get('Content-Encoding')));
          const length = response.headers.get('Content-Length');
          responseValue(length === null || (/^(0|[1-9][0-9]{0,7})$/.test(length)
            && String(Number(length)) === length && Number(length) <= REPLY_LIMIT));
          reader = response.body.getReader();
          const bytes = new Uint8Array(REPLY_LIMIT);
          let size = 0, chunks = 0;
          for (;;) {
            const part = await reader.read();
            if (done || controller.signal.aborted) throw new DocxClientError('transport_error');
            if (part.done) break;
            responseValue(++chunks <= 4096 && part.value instanceof Uint8Array
              && size + part.value.byteLength <= REPLY_LIMIT);
            bytes.set(part.value, size); size += part.value.byteLength;
          }
          responseValue(length === null || Number(length) === size);
          const parsed = JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(bytes.subarray(0, size)));
          return {status: response.status, body: parsed};
        } catch (_) {
          if (!reader) ignoreCancellation(response.body);
          throw new DocxClientError('invalid_response');
        }
      }
      const result = await Promise.race([receive(), deadline]);
      complete = true;
      return result;
    } catch (error) {
      throw error instanceof DocxClientError ? error : new DocxClientError('transport_error');
    } finally {
      done = true;
      if (!complete) controller?.abort();
      if (reader) {
        if (!complete) ignoreCancellation(reader);
        try { reader.releaseLock(); } catch (_) { /* Pending cancellation owns the read. */ }
      }
      if (timerSet) { try { cancel(timer); } catch (_) { /* Callback checks done. */ } }
      active.delete(lane);
    }
  });
}
