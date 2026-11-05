# D03-17A2b6a — source-bound structured review wire v2

5 November 2026. Baseline verified E2 `eaa1ef5`. F06/F07/F08/F11/F12.
One pure protocol bridge for fixed ListSnapshot and explicit list/note context. No inference,
worker/runtime/storage/start API admission in this cycle. Old v1 bytes and APIs unchanged.

## Paths and gates

New src/ara/docx_analysis/structured_review/ and contracts/docx-review-v2.json;
tests/acceptance/test_docx_review_v2.py, tests/docx_documents/test_review_v2_edges.py;
this contract/result, docs/docx-structured-review.md, docs/development-queue.md and .runtime.
Only old private hook review/_validate.py: extract generic internal validator with pinned
mapper/request_factory/base_factory. Existing public validate_engine_reply supplies existing
v1 functions at call time (preserve monkeypatch behavior). New public wrapper supplies fixed
list mapper/v2 factories. Old request/parse/shape/schema/public behavior and all old tests frozen.
No DB/schema/worker/runtime/model/dependency/runner/tasks/progress changes. Contracts v1 immutable;
new v2 schema explicitly authorized by this cycle. Freeze/red → implementation/review/regression
→ full gate → readonly mainV8/hashes → selective local commit, then next bounded cycle.
Documented new-test preparation fixes allowed only with assertions unchanged. No source/test/
contract edits during full gate. No user data, secrets, files/network/env read on import/build.

## API and request

prepare_structured_review(data,snapshot,*,provenance,limits=None),
validate_structured_reply(data,snapshot,*,provenance,request,reply,limits=None).
Re-export existing ReviewProvenance/ReviewLimits/ReviewError/PreparedReview/ReviewEnvelope;
these wrappers contain canonical bounded bytes, not an implicit source/engine capability.
Fixed ListSnapshot/profile final-visible-direct-lists-v1 and policy final-visible-no-comments-v2.
Source authority is map_list_spans; one fresh rebuild on prepare, one on validate even with zero
issues. Incomplete source => unsupported_document, no literal fragments => empty_document (F06).
A source-only marker document retains metadata in its snapshot but does not invent an ML span.

New version docx-review/2. Request retains source/document/revision/SHA/snapshot/profile/policy/
provenance envelope shape; engine_request contains exact literal fragments/disabled_types=[]/
dismissed=[] plus required document_context={lists:snapshot.lists,note_references:snapshot.references}.
Dataclass fields serialize canonically with exact source anchors and all item fields. Labels and
suffix remain context, never prefix text or alter offset/type/document/status. engine_request_json
also contains context; it cannot be lost when a future adapter consumes that payload. No caller
provided context or JSON fields accepted. No arbitrary snapshot/profile registry in this cycle.

Source quantities: existing view limits (10k paragraphs/fragments,100k notes,1M aggregate literal+
generated cost), byte/depth/evidence/reply limits unchanged. encode streams canonical content,
no unbounded asdict copy or JSON reparse of trusted source data needed. Context contributes to
request/result max_wire_bytes. No model inference or actual adapter-ready claim.

## Reply and result

Reply grammar remains the existing bounded engine0.1.0 literal-span syntax (closed keys/types,
count/provenance checks, exact quotes, whole related fragment, no NaN/duplicate keys). A future
actual C2 adapter must consume context explicitly; worker fixture2 is separate. Valid provenance
is still data, not evidence that real weights ran. Fixture always no_findings=false.

Compare full source-rederived PreparedReview, including both byte payloads/hash, before publishing
result. Invalid span/unknown fragment => invalid_reply; other source/input errors preserve existing
classes/codes. Every issue, related finding, question, count and private provenance rule retained.
Generated labels cannot be addressed as literal spans. Result is docx-review/2, fixed new profile,
with required top-level document_context exactly matching the request engine context. Same literal
coverage/evidence and semantic ID calculation (already source/snapshot/profile-bound); changes in
labels/context change snapshot binding and therefore identities. Attempt-only changes preserve
semantic identities. No silent fallback to v1 or omitted context on empty finding lists.

## JSON contract

New self-contained Draft2020-12 schema urn:aira:docx-review:2. Copy unchanged common v1 definitions
as the starting point, changing only version/profile, engine_request.context, result.context, and
new fragment_id/list_item/note_reference/document_context definitions. All refs internal, no remote
resolution. Every object is closed with exact required keys. List item fields match E2 DTO, nullable
start_override_anchor, num_id1..int31/level0/ordinal0..int31/formatdecimal|bullet/label<=4096/
suffixtab|space|nothing/fragment_ids<=10k. lists<=10k, note_references<=100k, note kindfootnote|endnote,
nullable before/after fragment IDs. Primitive anchors reuse v1 exact schema; source proof stronger
than JSON structure. v1 schema and every existing definition/file immutable. Validate meta-schema
with an already available external local library if possible, without dependency installation;
runtime authority comes from fresh source, not schema validation alone.

## Acceptance

Actual list/heading/body AIRA DOCX, table/image/note splits and exact literal request context.
Canonical bytes/SHA/engine payload; genuine original XML slices in replies; questions/dedup/related
spans and semantic binding. Empty and unsupported snapshots, old/new profile isolation, mutated
rehashed labels/anchors and PreparedReview context/hash/engine payload, unknown/label spans and
wrong quotes/counts/provenance/duplicates fail atomically. Exact context-inclusive wire limits,
one fresh map batch for many/no issues, inert fresh process and no real model imports. Closed v2
schema invariants and optional local meta-schema/valid payload QA. All previous937 hashes outside
the one hook, old tests unchanged, full gate and readonly mainV8 mandatory. Next B6B codec dispatch,
then fixture2/runtime/application admission and create→check→reopen; real weights remain absent.
