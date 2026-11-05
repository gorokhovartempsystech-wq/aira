// This layer checks the actor protocol; the backend proves DOCX source semantics.
export const MAX_COUNTER = 9223372036854775807n;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const HASH = /^[0-9a-f]{64}$/;
const CODES = new Set(["invalid_input", "invalid_response", "busy", "inactive",
  "counter_exhausted", "identity_unavailable", "transport_error", "request_failed",
  "request_rejected", "conflict", "session_expired"]);
const ACTIONS = new Set(["capture", "insert_text", "paste_text", "enter", "join_previous",
  "join_next", "insert_soft_break", "undo", "redo", "range_edit", "structure", "format"]);

export class DocxClientError extends Error {
  constructor(code, status = null) {
    const safe = CODES.has(code) ? code : "invalid_input";
    super(safe);
    this.name = "DocxClientError";
    this.code = safe;
    this.status = Number.isInteger(status) && status >= 100 && status <= 599 ? status : null;
  }
}
export function requireValue(ok, code = "invalid_input") {
  if (!ok) throw new DocxClientError(code);
}
export function uuid(value) {
  requireValue(typeof value === "string" && value.length === 36 && UUID.test(value));
  return value;
}
export function counter(value, minimum = 0n) {
  requireValue(typeof value === "string" && /^(0|[1-9][0-9]{0,18})$/.test(value));
  const n = BigInt(value);
  requireValue(n >= minimum && n <= MAX_COUNTER && String(n) === value);
  return n;
}
function hash(value) { requireValue(typeof value === "string" && value.length === 64 && HASH.test(value)); }
function object(value) { requireValue(value !== null && typeof value === "object" && !Array.isArray(value)); }

export function copyJson(value, maximum = 65536) {
  let count = 0, bytes = 0;
  function charge(value) {
    bytes += new TextEncoder().encode(JSON.stringify(value)).length;
    requireValue(bytes <= maximum);
  }
  function visit(item, depth) {
    requireValue(++count <= 250000 && depth <= 32);
    if (item === null || typeof item === "boolean") { charge(item); return item; }
    if (typeof item === "string") {
      requireValue(item.length <= maximum);
      for (const character of item) {
        const code = character.codePointAt(0);
        requireValue(code < 0xd800 || code > 0xdfff);
      }
      charge(item); return item;
    }
    if (typeof item === "number") { requireValue(Number.isSafeInteger(item)); charge(item); return item; }
    object(item);
    return item;
  }
  function clone(item, depth) {
    // Arrays are handled before the ordinary-object shape check in visit.
    if (Array.isArray(item)) {
      requireValue(++count <= 250000 && depth <= 32 && item.length <= 250000);
      requireValue(Reflect.ownKeys(item).length === item.length + 1);
      const out = [];
      for (let i = 0; i < item.length; i++) {
        const property = Object.getOwnPropertyDescriptor(item, String(i));
        requireValue(property && Object.hasOwn(property, "value") && property.enumerable);
        out.push(clone(property.value, depth + 1));
      }
      return out;
    }
    const basic = visit(item, depth);
    if (basic === null || typeof basic !== "object") return basic;
    const proto = Object.getPrototypeOf(item);
    requireValue(proto === Object.prototype || proto === null);
    const out = {};
    for (const key of Reflect.ownKeys(item)) {
      requireValue(typeof key === "string" && key.length <= maximum);
      visit(key, depth + 1);
      const property = Object.getOwnPropertyDescriptor(item, key);
      requireValue(property && property.enumerable && Object.hasOwn(property, "value"));
      Object.defineProperty(out, key, {value: clone(property.value, depth + 1), enumerable: true,
        configurable: true, writable: true});
    }
    return out;
  }
  try {
    const result = clone(value, 0);
    requireValue(new TextEncoder().encode(JSON.stringify(result)).length <= maximum);
    return result;
  } catch (_) { throw new DocxClientError("invalid_input"); }
}

export function checkedView(raw) {
  const v = copyJson(raw);
  object(v); requireValue(v.kind === "editor");
  for (const name of ["registry_id", "document_id", "session_id"]) uuid(v[name]);
  const seq = counter(v.command_sequence);
  counter(v.base_storage_revision, 1n); counter(v.checkpoint_revision, 1n);
  counter(v.observed_checkpoint_revision); hash(v.base_sha256);
  object(v.document);
  const revision = counter(v.document.session_revision), position = counter(v.position_id);
  requireValue(position <= revision);
  hash(v.document.source_sha256);
  requireValue(typeof v.document.main_part === "string" && v.document.main_part.length > 0
    && v.document.main_part.length <= 1024);
  requireValue(typeof v.document.is_dirty === "boolean"
    && v.document.is_dirty === (v.document.source_sha256 !== v.base_sha256));
  for (const name of ["undo_depth", "redo_depth"])
    requireValue(Number.isInteger(v.document[name]) && v.document[name] >= 0);
  requireValue(v.document.undo_depth + v.document.redo_depth < 100);
  requireValue(["editable", "recovery_pending", "conflict", "operation_pending"].includes(v.state));
  object(v.observed_current); uuid(v.observed_current.document_id);
  requireValue(v.observed_current.document_id === v.document_id);
  counter(v.observed_current.storage_revision, 1n); hash(v.observed_current.current_sha256);
  if (v.state === "editable") requireValue(v.recovery_operation_id === null
    && v.checkpoint_revision === v.observed_checkpoint_revision
    && v.base_storage_revision === v.observed_current.storage_revision
    && v.base_sha256 === v.observed_current.current_sha256);
  requireValue(v.active_command === null || typeof v.active_command === "object");
  if (v.state === "operation_pending") requireValue(v.active_command !== null);
  object(v.selection);
  for (const name of ["anchor", "focus"]) {
    const p = v.selection[name]; object(p); object(p.anchor);
    requireValue(p.anchor.source_sha256 === v.document.source_sha256
      && p.anchor.part_name === v.document.main_part);
    requireValue(Number.isSafeInteger(p.offset) && p.offset >= 0 && p.offset <= 2147483647);
    requireValue(p.affinity === "left" || p.affinity === "right");
    requireValue(Array.isArray(p.anchor.path) && p.anchor.path.length >= 1 && p.anchor.path.length <= 128);
    requireValue(p.anchor.path.every(n => Number.isInteger(n) && n >= 0 && n <= 100000));
  }
  if (v.last_command !== null) {
    const last = v.last_command; object(last); uuid(last.command_id); hash(last.request_sha256);
    requireValue(ACTIONS.has(last.action) || last.action === "checkpoint" || last.action === "save");
    requireValue(counter(last.expected_command_sequence) + 1n === seq);
    const previous = counter(last.expected_session_revision);
    requireValue(revision === previous || revision === previous + 1n);
    requireValue(last.result_command_sequence === v.command_sequence
      && last.result_session_revision === v.document.session_revision
      && last.result_position_id === v.position_id);
  }
  return v;
}

export function commandBody(command) {
  const c = copyJson(command, 8 * 1024 * 1024);
  object(c); requireValue(ACTIONS.has(c.action));
  requireValue(Object.keys(c).every(k => ["action", "value", "after"].includes(k)));
  return c;
}
export function checkedAck(raw, pending) {
  const v = checkedView(raw), previous = pending.before;
  for (const name of ["registry_id", "document_id", "session_id"])
    requireValue(v[name] === previous[name], "invalid_response");
  const last = v.last_command;
  requireValue(last !== null && last.command_id === pending.id && last.action === pending.action
    && last.expected_command_sequence === previous.command_sequence
    && last.expected_session_revision === previous.document.session_revision
    && counter(v.command_sequence) === counter(previous.command_sequence) + 1n, "invalid_response");
  const sameSource = v.document.source_sha256 === previous.document.source_sha256;
  if (pending.operation !== "commands") {
    requireValue(sameSource && v.document.session_revision === previous.document.session_revision
      && v.position_id === previous.position_id, "invalid_response");
    requireValue(counter(v.checkpoint_revision) > counter(previous.checkpoint_revision), "invalid_response");
    if (pending.operation === "checkpoint") requireValue(v.base_sha256 === previous.base_sha256
      && v.base_storage_revision === previous.base_storage_revision
      && v.document.is_dirty === previous.document.is_dirty, "invalid_response");
    else requireValue(!v.document.is_dirty && v.base_sha256 === v.document.source_sha256
      && counter(v.base_storage_revision) >= counter(previous.base_storage_revision), "invalid_response");
  } else {
    requireValue(v.base_sha256 === previous.base_sha256
      && v.base_storage_revision === previous.base_storage_revision
      && v.checkpoint_revision === previous.checkpoint_revision, "invalid_response");
    if (v.document.session_revision === previous.document.session_revision || pending.action === "capture")
      requireValue(sameSource, "invalid_response");
    if (pending.action === "capture") requireValue(v.document.session_revision === previous.document.session_revision, "invalid_response");
  }
  return v;
}
