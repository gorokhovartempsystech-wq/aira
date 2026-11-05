import {DocxClientError, requireValue, uuid, counter, MAX_COUNTER, copyJson,
  checkedView, commandBody, checkedAck} from "./protocol.mjs";

export {DocxClientError};
export const AUTOSAVE_DELAY_MS = 120000;
const REFUSALS = new Set(["validation_error", "invalid_input", "unsupported_intent",
  "unsupported_boundary", "unsupported_range", "unsupported_structure", "unsupported_format",
  "invalid_selection", "stale_selection", "invalid_anchor", "invalid_range", "text_mismatch",
  "editor_request_too_large", "editor_limit_exceeded", "text_limit_exceeded",
  "session_limit_exceeded", "projection_limit_exceeded", "package_limit_exceeded",
  "range_limit_exceeded", "boundary_limit_exceeded", "format_limit_exceeded"]);

// Owns one actor's request lane, not the renderer, network connection or server actor.
export function createDocxSession({view: initial, send, makeId = () => globalThis.crypto.randomUUID(),
  schedule = (fn, delay) => setTimeout(fn, delay), cancel = id => clearTimeout(id), onState = () => {}}) {
  let view = checkedView(initial);
  for (const fn of [send, makeId, schedule, cancel, onState]) requireValue(typeof fn === "function");
  let durable = view.document.is_dirty ? null : view.document.source_sha256;
  let started = false, stopped = false, timer = null, due = false;
  let pending = null, inFlight = false, failure = null, schedulerFailed = false;
  const needsCheckpoint = () => view.document.source_sha256 !== durable;
  const editable = () => view.state === "editable" && view.active_command === null;

  function status() {
    const phase = stopped ? "stopped" : !started ? "inactive" : inFlight ? "saving"
      : failure || (pending ? "uncertain" : !editable() ? "conflict" : schedulerFailed ? "scheduler_error"
        : needsCheckpoint() ? "changed" : "saved");
    return {phase, busy: inFlight, canEdit: started && !stopped && !pending && editable()
      && !["conflict", "expired"].includes(failure),
      canRetry: pending !== null && !inFlight && failure !== "expired",
      dirty: view.document.is_dirty, uncheckpointed: needsCheckpoint(),
      commandSequence: view.command_sequence, sessionRevision: view.document.session_revision};
  }
  function emit() {
    try { Promise.resolve(onState(status())).catch(() => {}); } catch (_) { /* Isolate renderer. */ }
  }
  function cancelTimer() {
    const old = timer;
    timer = null; // Invalidate the callback even when the platform cannot cancel it.
    if (old !== null) {
      try { cancel(old.handle); } catch (_) { /* A cancelled callback is harmless. */ }
    }
  }
  function coordinate() {
    if (!started || stopped || !editable() || ["conflict", "expired"].includes(failure)) {
      cancelTimer(); return;
    }
    if (!needsCheckpoint()) { cancelTimer(); due = false; schedulerFailed = false; return; }
    if (due) {
      if (!pending) void begin("checkpoint").catch(() => { failure ??= "error"; emit(); });
    } else if (timer === null) {
      const token = {handle: null};
      timer = token;
      try {
        token.handle = schedule(() => {
          if (timer !== token) return;
          timer = null; due = true; coordinate(); emit();
        }, AUTOSAVE_DELAY_MS);
        schedulerFailed = false;
      } catch (_) {
        if (timer === token) timer = null;
        schedulerFailed = true;
      }
    }
  }
  async function dispatch() {
    const attempt = pending;
    requireValue(attempt !== null && !inFlight, "busy");
    inFlight = true; failure = null; emit();
    let response;
    try {
      try { response = await send(Object.freeze({path: attempt.path, body: attempt.body})); }
      catch (_) { throw new DocxClientError("transport_error"); }
      if (response?.status !== 200) {
        const statusCode = response?.status;
        const knownRefusal = attempt.operation === "commands" && !attempt.uncertain
          && (statusCode === 413 || statusCode === 422) && REFUSALS.has(response?.body?.code);
        if (knownRefusal) {
          pending = null; failure = "error";
          throw new DocxClientError("request_rejected", statusCode);
        }
        failure = statusCode === 409 ? "conflict" : statusCode === 410 ? "expired" : "uncertain";
        throw new DocxClientError(statusCode === 409 ? "conflict"
          : statusCode === 410 ? "session_expired" : "request_failed", statusCode);
      }
      let next;
      try { next = checkedAck(response.body, attempt); }
      catch (_) { throw new DocxClientError("invalid_response"); }
      view = next;
      if (attempt.operation !== "commands") durable = next.document.source_sha256;
      pending = null; failure = null;
      return copyJson(next);
    } catch (error) {
      if (pending === attempt) { attempt.uncertain = true; failure ??= "uncertain"; }
      throw error instanceof DocxClientError ? error : new DocxClientError("invalid_response");
    } finally {
      inFlight = false;
      coordinate(); emit();
    }
  }
  async function begin(operation, command) {
    requireValue(!pending && !inFlight, "busy");
    requireValue(started && !stopped, "inactive");
    requireValue(editable() && !["conflict", "expired"].includes(failure), "conflict");
    requireValue(counter(view.command_sequence) < MAX_COUNTER, "counter_exhausted");
    const c = operation === "commands" ? commandBody(command) : null;
    if (operation === "commands" && c.action !== "capture")
      requireValue(counter(view.document.session_revision) < MAX_COUNTER, "counter_exhausted");
    if (operation !== "commands")
      requireValue(counter(view.checkpoint_revision) < MAX_COUNTER, "counter_exhausted");
    let id;
    try { id = uuid(makeId()); } catch (_) { throw new DocxClientError("identity_unavailable"); }
    requireValue(id !== view.last_command?.command_id, "identity_unavailable");
    const value = {command_id: id, expected_command_sequence: view.command_sequence,
      expected_session_revision: view.document.session_revision};
    if (c !== null) value.command = c;
    const body = JSON.stringify(copyJson(value, operation === "commands" ? 8 * 1024 * 1024 : 65536));
    pending = {id, body, operation, action: c?.action ?? operation, before: view, uncertain: false,
      path: `/docx-documents/${view.document_id}/editor-sessions/${view.session_id}/${operation}`};
    return dispatch();
  }
  return Object.freeze({
    start() { requireValue(!stopped, "inactive"); started = true; coordinate(); emit(); return status(); },
    edit: command => begin("commands", command),
    checkpoint: () => begin("checkpoint"),
    save: () => begin("save"),
    async retry() { requireValue(pending !== null && !inFlight, "busy"); return dispatch(); },
    snapshot: () => copyJson(view), status,
    stop() { stopped = true; cancelTimer(); emit(); return status(); }
  });
}
