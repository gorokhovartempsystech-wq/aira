# D03-18A1 — DOCX command and autosave client coordinator 

5 November 2026. Baseline `9e17f1b`.
F05/F06/F12; B9C1/B9B full gate passed6849 tests. Fixed two-minute local checkpoint, not an
unannounced backend timer. A framework-independent client for one explicitly opened editor
actor, later bound to Anya's renderer and to a real loopback transport in a separate cycle.
No replacement of her UI, automatic document open/discard, accounts or real-model claim.

Paths: new src/ara/desktop/client/ Python resource package + ESM modules; one additive
package-data entry in pyproject.toml, no dependency/default/testpath/lint changes. New
 tests/acceptance/test_docx_client_session.py and docx_client_session_cases.mjs; docs/d03-18a1-contract.md, docs/d03-18a1-result.md, docs/docx-client-session.md and
 docs/development-queue.md; .runtime. No old tests/source/wire/SQL/runner changes.
Freeze meaningful tests before implementation, actual red, target/review and full repository
check with explicit builder Ruff, input hashes and mainV8 readonly comparison. New-test
preparation corrections may retain frozen assertions with documented evidence.

Public createDocxSession({view, send, makeId?, schedule?, cancel?, onState?}) is inert. It
receives an opened editor metadata view, never docx bytes, credentials or an app singleton.
start() activates scheduling; edit(command), checkpoint(), save() issue existing paths;
retry() repeats the one unresolved immutable operation. snapshot()/status() are detached;
stop() cancels future background work, not the server actor or pending accepted operation.
No background thread, fetch or timer at module import/constructor. Default timer120000ms.

A new command uses canonical UUID identity and the last confirmed decimal counter strings.
One in-flight/uncertain intent; busy rejects before taking ownership of another command.
No queue of stale anchors, silent rebasing, UUID replacement after failure or automatic retry.
Caller retains rejected input. Serialize/clone bounded plain JSON once so later mutation cannot
change the exact retry path/body. Counter arithmetic uses BigInt through2^63-1, never Number.
Exhaustion refuses before dispatch. Dependencies and callbacks are isolated; errors/status
contain safe codes and counters, never input text, anchors, response bodies or credentials.

ACK must match document/registry/session, own command_id/action and expected/result counters.
Sequence increases by exactly1; edit revision unchanged or+1; controls do not change editor
revision. Checkpoint preserves current bytes/base/dirty and confirms durable hash; save matches
current bytes as base and clears dirty. Wrong/malformed/stale ACK cannot replace confirmed view.
The whole parsed reply is detached; protocol validation is not a claim to verify DOCX semantics.

Initial clean view has its saved hash durable. Initial dirty view gets a conservative checkpoint.
First acknowledged content hash differing from durable hash arms one timer. Continuous typing
and selection/noop ACKs do not postpone it. At deadline, if busy, retain a due flag and checkpoint
only after ACK; otherwise checkpoint immediately. While checkpoint pending, no other writes.
After success, same dirty bytes do not trigger repeated writes. Undo to the saved base may still
need checkpoint if a different hash was persisted. Returning to durable hash cancels the timer.
Stop during an in-flight request permits its acknowledgement to settle, but never reschedules.

Unknown transport/5xx/invalid ACK retains exact identity; retry sends identical body/path and
updates state only on valid ACK.409 marks conflict,410 session lost: stop automatic work, preserve
pending input and confirmed metadata for explicit recovery. A first-attempt edit413/422 known
atomic refusal can release its slot while rejecting the intent; a retry after uncertain outcome
and any control failure retain the identity. No status is treated as rollback of prior writes.
No loop that repeatedly sends invalid commands or creates hidden retries.

Acceptance with virtual clock: exact120000 deadline, sustained typing, no-op/capture, initial
working state, hash equality vs dirty flag, checkpoint acknowledgement, undo before/after a
checkpoint, deadline during edit, overlap rejection, lost ACK/exact retry/body immutability,
malformed/wrong identity/counters, >2^53 arithmetic/exhaustion,403/409/410/413/422/5xx policy,
callback failure, stop during dispatch, two independent documents, and packaged ESM asset entry.
Follow-up real licensed HTTP run proves backend protocol matching and durable recovery. No
production UI readiness is inferred from pure virtual-time cases.
