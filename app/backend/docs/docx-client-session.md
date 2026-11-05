# DOCX client command lane and autosave

D03-18A1, 5 November 2026. Framework-independent ESM resources in
`ara.desktop.client`. This coordinator owns one explicitly opened server editor actor.
It does not open a document, own credentials, provide a renderer or perform a real analysis.

Import `createDocxSession` from `docx-session.mjs` and supply the opened metadata `view`
and an async `send({path, body})`. The body is already serialized; send it unchanged as POST
JSON to the trusted local app. Return `{status, body}` with parsed JSON. Never log either body.
The separate HTTP transport cycle proves the production loopback binding.

Construction is inert. Call `start()` explicitly. `edit(command)`, `checkpoint()`, `save()`
and `retry()` return promises with detached confirmed metadata. `snapshot()` and `status()`
are detached. `onState` gets safe status/counters only, not text or selections. Callback
exceptions/rejections cannot invalidate a completed command. Clock and UUID dependencies
can be injected for deterministic tests; real defaults use120000ms and crypto.randomUUID.

Only one operation can own the lane. If busy, retain the user's input in the renderer and
retry submitting it only after the caller resolves its position. There is no hidden input
queue, automatic rebasing or concurrent keystroke dispatch. An uncertain outcome retains
exact serialized bytes/path/UUID; only explicit `retry()` reuses them. Do not make a second
coordinator for the same actor to bypass an unresolved command.

The first acknowledged hash different from the last durable hash starts a two-minute timer.
Typing does not postpone it. If the deadline arrives while busy, a checkpoint follows the
acknowledgement. Unchanged/capture operations do not cause extra persistence; a checkpoint
can be durable while `dirty` remains true. Undo to a clean base can require another checkpoint
when different bytes were previously persisted. `save()` additionally establishes current
saved bytes; it is a different operation from a working checkpoint.

`canEdit`/`busy` describe admission; `uncheckpointed` describes RAM vs known durable bytes.
Phases distinguish inactive/saved/changed/saving, errors, uncertainty, conflict, session loss
and stopped. A timer service failure reports `scheduler_error` without pretending that an
acknowledged edit failed; explicit checkpoint/save remains available. A cancelled callback
cannot affect a later dirty period even if the host fails to physically cancel it.

First-attempt atomic edit413/422 with a known backend refusal releases the lane and rejects
the intent. Unknown transport, invalid ACK, controls and retries after an uncertain outcome
retain the identity.409/410 stop automatic work for explicit conflict/recovery handling.
Counters stay canonical decimal strings, with bounded BigInt comparisons. Errors contain
fixed codes/status only; the server remains responsible for source/selection semantics.

`stop()` cancels future timers. It is not a server close, discard, rollback or evidence of
successful persistence. A late acknowledgement can settle after stop without rescheduling.
Keep the instance alive to resolve pending work; losing the client instance does not undo
an accepted server command. Durable recovery is a separate explicit server workflow.

This core does not complete F05/F06 UI delivery: real licensed HTTP transport, save-before-
check admission, tab/recovery coordination and Anya's input/rendering binding follow.
