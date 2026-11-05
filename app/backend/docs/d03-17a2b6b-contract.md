# D03-17A2b6b — fixed structured source storage codec

5 November 2026. Baseline verified B6A `50de930`. F06/F07/F08/F12.
One pure codec extension: persisted records support the two exact source profiles and
rebuild both from original source bytes. No live application admission in this cycle.

## Paths / gates

Only existing source storage_codec/_records.py, optional new private storage_codec/_profiles.py;
new tests/acceptance/test_docx_structured_storage.py and
 tests/docx_documents/test_structured_storage_edges.py; this contract/result,
 docs/docx-structured-storage.md, development-queue.md and ignored .runtime.
No models/schema/SQL/migration/worker/runtime/start/public API/old wire/dependency/runner/
tasks/progress/old tests changes. Public API signature unchanged; new exact snapshot profile
admission explicitly authorized, arbitrary registries/callables/profiles forbidden.
Freeze/red → implementation/review/regression → full gate → readonly mainV8/hashes → local
selective commit. Old hashes except one records hook immutable. Documented new-test preparation
corrections only with frozen assertions unchanged. No source/test/contract edits during full gate.

## Layout and fixed dispatch

SourceBundle format_version=1 remains the exact existing record layout. SQL0010 and models
constrain format1 and profile/policy token syntax, not an old single profile. Keep format1,
command/execution schemas and DB untouched. Existing final-visible-main-v1 / docx-review/1
bytes remain bit-identical. Additional fixed final-visible-direct-lists-v1 / docx-review/2
uses the same source/manifest/command/execution record columns with its own profile identity.
VisibleSnapshot and ListSnapshot accepted by exact type; unsupported/forged DTOs retain
invalid_snapshot rejection. No type-coercion, reconstructing DTOs from untrusted JSON or
upgrading existing saved snapshots to a newer profile. Policy remains exact existing value.

capture_source validates source via the fixed respective review preparer before inspecting
its fragments/context. check_source first bounds all buffers, verifies hashes/strict scalars,
then accepts only exact known profile/policy; unknown valid tokens=>unsupported_version,
malformed tokens/scalars=>corrupt_record. Restore chooses only the fixed source builder,
rederives the full manifest from source, compares canonical bytes and hash, validates admission
and command binding. Swapping supported profiles cannot authorize a changed manifest and yields
corrupt_record. No partial/stale result. Preserve old lower-error classes/codes and call-time
old builder import behavior (old monkeypatch boundary tests remain meaningful).

prepare_attempt pins saved profile and execution, includes exact structural context for new
source; new attempt changes attempt/request identity only. capture_result and restore_result
use the same exact respective prepare/validate functions and source-derived request equality.
Rehashed request/manifest/result/context or swapped attempt cannot become a capability. Counts,
private provenance, questions, semantic finding identities, checked-source/source slices remain.
No silent new→old fallback or omission of context when findings empty. Fixture empty still
no_findings=false; pure accepted provenance is not evidence that model execution occurred.
RetryCheckCommand preserves original snapshot/profile/storage revision; application retry path
change deliberately deferred to runtime cycle.

## Limits and inertness

Existing raw byte/manifest/command/execution/reply/wire/count bounds unchanged. For ListSnapshot,
CodecLimits.max_text_characters counts literal text + sum(label lengths + suffix1 unless nothing),
matching E2 cost; exact lower custom caps apply in capture and restore. Old profile literal cost
unchanged. Fragment cap512 applies before publishing storage records; marker-only and incomplete
documents remain review errors. Review/view lower limits and result corruption normalization
preserve old behavior. Context is streamed canonically, no unbounded deepcopy/DOM retention.
Import/capture/restore run without DB/files/env/network/model imports or side effects; source
bytes unchanged. No Python object is treated as authority merely because it is frozen.

## Acceptance

Source→manifest→restore→attempt→reply→result→restore for both exact profiles; new AIRA template
creation roundtrip, Unicode/hidden gaps/list context/source evidence. Byte-for-byte old protocol
and schema protection. Retry attempt/profile identity and fixture empty results. Rehashed label/
ordinal/anchor/deletion manifest; known/unknown profile swaps; forged request/result/attempt/
source/command/execution fields rejected. Exact generated+literal/manifest/wire/source bounds,
strict types and unsupported DTOs, incomplete/marker-only input. Fresh process with no database,
files/environment/network or ML imports. Old regression, full gate, hashes and readonly mainV8.
Next distinct fixture2, worker admission/lifecycle, new saved-check selection and old retry pinning,
then API/preference resolution/create→check→reopen. No claim runtime or actual ML ready here.
