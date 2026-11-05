# D03-17A2b6c2 — native structured fixture admission and pinned retries

5 November 2026. Baseline verified C1 `f7dedca`. 
One vertical backend feature: native fixture2 executes a saved structured source and retries
the original profile after later edits/restart. No desktop default/presentation claim yet.

## Paths / gates

New src/ara/docx_analysis_runs/structured.py and
src/ara/docx_analysis_worker/supervisor/structured_fixture.py;
tests/acceptance/test_docx_structured_runtime.py,
tests/docx_documents/test_structured_runtime_edges.py;
this contract/result, docs/docx-structured-runtime.md, docs/development-queue.md,.runtime.
Exactly7 old source hooks allowed: docx_analysis_runs/_start.py;
docx_analysis_worker/supervisor/runtime.py and supervisor/_admission.py;
macos/_launch.py and macos/_fixture_child.py;
windows/_adopt.py and windows/_fixture_child.py.
No other launch/ownership/guardian/SQL/publication/drain algorithms, old tests, source codecs,
schemas, DB/models/migrations/dependencies/runner/tasks/progress/HTTP/desktop changes.
Freeze/red → implementation/review/regression → full gate → readonly mainV8/hashes → local
selective commit. Old hashes outside seven hooks immutable. New-test preparation corrections
allowed only documented with frozen assertions unchanged. No source/test/contract edits during
full gate. Native Windows gate remains unexecuted on macOS; platform-neutral child tests do not
replace it. No global tools/publication/push/secrets/user data use.

## Saved source and retry

New explicit structured.start_saved / structured.retry_run retain the old keyword signatures.
Old _start functions remain old semantics on old inputs and public defaults unchanged.
Extract private common saved-start algorithm parameterized by an internal fixed builder, with
old wrapper resolving build_visible_snapshot at call time and new wrapper pinning build_list_snapshot.
Extract private retry algorithm parameterized by internal snapshot loader: old wrapper uses
old builder; new wrapper calls restore_source on original stored SourceBundle and takes its
snapshot. No public registry or caller-supplied builder/capability. Old get_source already
source-validates; restore again is acceptable bounded pure proof, never a new current-document read.

All existing input/scope/target identity/idempotency/deadline/queue/active-run/transaction checks
unchanged. Durable replay precedes provider/config as before, even across the two entry points;
it returns the original accepted source/policy and never re-enqueues/upgrades it. The new saved
path derives fixed structured profile from the exact SavedTarget bytes. Retry pins original
source bytes/revision/hash/profile/snapshot, even after current saved document changes; new
executor provenance/attempt may differ. Both existing profiles supported by source codec and
fixture2's explicit legacy pair. Unknown/corrupt source, nonterminal parent, scope mismatch,
invalid target/empty/unsupported/bounds errors retain existing public codes and atomic no-enqueue.
SQLschemaV13 and SourceBundleformat1 unchanged; no upgrade of mainV8.

## Closed supervisor policy and child mode

_create_supervisor gains a PRIVATE exact source_profile selector with default old PROFILE;
only old PROFILE/new LIST_PROFILE strings accepted before any work. Supervisor stores the
fixed choice (same issued exact class, owner/registry/PID/thread checks intact). _admission's
start closure dispatches to old vs new fixed module for both saved and retry. Old factory and
all caller defaults remain old profile. No arbitrary callable or profile registry exposed.

New create_structured_fixture_supervisor has same public keyword args as old semantic factory,
selects exact native Parent by sys.platform, fixes execution=fixture2, source_profile=LIST_PROFILE
and backend.start(mode='review2'). Unsupported host fails runtime_unavailable; never uses fake
platform. Constructor inert; processes/SQL start only on explicit .start(), as before.

Add exact review2 mode to macOS and Windows existing closed mode sets. Their child bodies
import structured_fixture.reply_for only after existing startup gate, emit identical four-frame
protocol (ready,stage,stage,result/error), and return existing success/error statuses. Old review
mode pins fixture1. No new executable/path/env/endpoint or dynamic module argument. Error frame
contains adapter_error, no source text. SHA/seq/provenance/binding validation stays in wire and
fixture. Native physical closure, slot/fence/lease/publication/stop ordering remain unchanged.

## Acceptance

Pure child dispatch on both host modules with valid/invalid structured request, exact payload,
frame order/hash/no private diagnostics; old/new identity isolation and closed mode registration.
Disposable PG saved-start new profile + canonical context, durable replay (provider not called),
exact saved bytes after current changes, target mismatch, unsupported/empty no enqueue, legacy
start still rejects structured source. Retry original structured and legacy profiles after current
source changes, preserving oldsource/manifest and changing attempt/executor only, nonterminal/
corrupt/scoped rejection. Real available-native supervisor executes actual AIRA heading/list DOCX,
stops without result, closes cleanly, restarts and restores stored context, successfully retries
old and new parent records without profile upgrades. Fixed-policy constructor validation/inertness.
Full old lifecycle regression, mainV8/hash checks. Next structured presentation/correspondence then
explicit desktop composition; actual ML/native Windows/Word/release gates remain separate.
