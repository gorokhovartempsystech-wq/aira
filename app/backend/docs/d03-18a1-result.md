# D03-18A1 — client command/autosave coordinator complete

5 November2026. Baseline9e17f1b, acceptance freeze2eef779. Actual red37failed1.07s;
firstimplementation37passed0.96s. Ten independent review cases initially gave8failed,
39passed1.35s. Two new review preparations were corrected: increment the injected UUID
for the subsequent checkpoint, and use a directly returning async callback instead of a
helper that discarded its promise. Frozen37 assertions/preparations remain unchanged.

Review fixes isolate timer/cancel failures from accepted acknowledgements, invalidate late
cancelled callbacks, clone command input before reading getters, bound cumulative JSON work,
validate main_part, refuse exhausted checkpoint counters before dispatch, and report an
automatic identity failure without losing confirmed metadata. An additional line-ending
canonical-input case already passed before extra explicit length/canonical-string guards;
it is regression evidence, not a reproduced regex defect. Final target **48passed /1.35s**.
Prior workspace/app plus the47-case target passed **104tests,6warnings /3.45s**.

The coordinator uses canonical counter strings/BigInt, one unresolved immutable identity,
explicit exact retries and a fixed120000ms deadline from the first uncheckpointed hash.
Continuous typing does not postpone persistence. A checkpoint can remain dirty; undo after
one may need another checkpoint even when it returns to the saved base. Unknown outcomes
block fresh writes; stopped instances can settle a late ACK without restarting timers.

`bash scripts/check.sh`: **6897passed,45skipped,76warnings,24subtests passed /1283.53s**,
exit0. Recursive Ruff959files plus explicit builder check/format5 passed. An earlier full
run was deliberately interrupted for the canonical-input investigation; its exit2/log are
retained and are not completion evidence. The final gate used1066 unchanged input hashes.
All1060 previous inputs are unchanged except the authorized single package-data entry.
Freeze prefixes remain intact; independent review cases were appended only. Readonly mainV8
schema/revision/counts match B9C1; no row contents read or main database migration performed.

An isolated real wheel build verified all3 client package assets byte-for-byte. Missing build
tools were prepared only under ignored.runtime; project/global dependencies were not changed.
No runner/SQL/wire/oldsource/oldtest changes, publication or unrelated user files included.

[Client usage](docx-client-session.md). This cycle is a pure framework-independent core,
not a complete input renderer or connected UI. Next **D03-18A2** proves bounded pinned HTTP,
lost-ACK retries and durable recovery against an owned licensed macOS fixture desktop.
RealML, finalGUI, native Windows/Word visual acceptance and release remain separate gates.
