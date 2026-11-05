# D03-17A2b6c1 — explicit semantic fixture2 for structured and pinned legacy review

5 November 2026. Baseline verified B6B `ea357f7`. F06/F07/F08/F12.
One pure semantic fixture bridge, no runtime/DB admission.

## Allowed paths and gates

New src/ara/docx_analysis_worker/structured_fixture/;
 tests/acceptance/test_docx_structured_fixture.py,
 tests/docx_documents/test_structured_fixture_edges.py;
this contract/result, docs/docx-structured-fixture.md, docs/development-queue.md and ignored
.runtime. Only existing source hook docx_analysis_worker/review_fixture.py may extract
private request-header, literal-fragment and synthetic-reply helpers. Old fixture1 public
entry points pin old constants and functions at call time; all old tests unchanged. No
new arbitrary capability/profile registry, no weakened source/wire/old fixture validation.
No source codec/protocol schemas/SQL/models/native launcher/supervisor/start/HTTP/dependencies/
runner/tasks/progress changes. No real model claim or user data. Freeze/red → implementation/
review/regression → full gate → readonly mainV8/hash verification → selective local commit.
All previous hashes outside the one hook protected. Documented new-test preparation fixes
allowed only with frozen assertions unchanged. No source/test/contract edits during full gate.
New APIs inert on import and execution; no filesystem/env/network/subprocess/ML actions.

## Protocol and behavior

New docx_analysis_worker/structured_fixture/ with fixture_execution(), reply_for(request),
ReviewFixtureError re-export/shared type. Execution fixture,0.1.0,aira-review-fixture-2,
sha256('aira-review-fixture-model/2'),sha256('aira-review-fixture-adapter/2'). New public fixed
entry point only. Optional shared parsing extraction in old review_fixture.py allowed only
with old constants/function bindings supplied at call time; all old v1 tests/behavior frozen.
No native modes/start/supervisor/DB/schema/API admitted in C1.

WireMessage exact run/seq0/binding/claim_fence1/worker_uuid/execution_spec_sha256/request_sha;
canonical execution decode matches fixture2 only. Duplicate/NaN/depth/size guards unchanged;
existing parsed depth8 covers structured request maxnest7 (outer1 engine2 context3 lists4
item5 anchor6 path7). body closed request keys, source canonicalUUID/revision/sourceSHA,
provenance exact execution+attempt, snapshotSHA valid. Exactly two version/profile pairs:
- docx-review/2 + final-visible-direct-lists-v1: engine closed four keys with context;
- docx-review/1 + final-visible-main-v1: engine exact old three keys, context absent.
Same final-visible-no-comments-v2 policy. No fallback on malformed context or pair mismatch.
Legacy support is explicit for saved retries, not an automatic profile upgrade.

Literal engine fragments1..512, exact keys, unique vf-SHA IDs, nonempty validUTF8 text,
total literal <=1M, fixed document/type/status, strict int offset>=0 and<int63. Empty filters
and dismissed. Structured document_context closed lists/note_references. lists<=10k, notes<=100k.
List all exact DTO keys, strict nonboolints num_id1..int31/level0/ordinal0..int31, exactenum
format/suffix,labelvalidUTF8<=4096 (empty allowed),nullable override. Each SourceAnchor closed
source_sha256==sourceSHA, normalized nonempty part_name<=65535/no backslash/no empty/dot/dotdot
segments, patharray<=128 strict integer0..99999. No caller paths opened. Paragraph/props same
part, props descendant of paragraph; definition/instance samepart; override ifpresent samepart.
Don't infer source XML tag semantics from paths; parent fresh source proof remains authority.
Per-item fragment_ids exact existing IDs, unique and disjoint acrossitems, aggregate<=fragmentcount;
empty IDs allowed (marker-only item in otherwise checkable doc). Distinct item paragraph anchors.
List cost + literal <=1M, suffix counts1 unlessnothing. Notes kindexact, threeanchorsbound;
reference+paragraph samepart/descendant, before/afterIDs nullable but existing whennotnull;
reference uniqueness (kind,referenceanchor), repeatedtarget allowed. Do not require distinct
before/after vs allnoteIDs if parser permits same; mirror proven DTO invariants only.

Synthetic response selects first list item's available literal fragment ifany, otherwise first
literal fragment. Primaryquote<=64 actualchars; generatedlabel never inprimaryspan. Explanation
clearly 'Учебный пример'/'Реальная модель не запускалась', includes bounded label sample for
selecteditem and structural counts. Text remains data. Question synthetic and bounded. Same
closed engine0.1.0replyshape, info/yellow/confidence0, no suggestion, oneissue/onequestion;
engine/modelsfixture2,checkedactualn,seconds0. Deterministicreply and sourcevalidity provenby
capture_result. Fixture always no_findingsfalse inparent. No actualmodel imports/network/I/O.

Acceptance both supported pairs with fixture2 provenance; realcreatedAIRA lists; table/image/
notes context; blanklabelitem selectsrealfragment; hostile/unicode labels escapeasdata and
boundedexplanation; newandoldfixture mutually executionclosed. Allstructure/type/binding/refs/
size/depth/extra/duplicate/source/provenance/pair tampering rejected with no payloaddiagnostic.
Sourceforgedbutstructurallywellformed workerinputmaypasseslocalshape; explicitly demonstrate
parent capture_result rejects a changed/rehashed AttemptBundle.request_data against original source context. A reply alone does not attest which context the model actually used or the semantic truth of its explanation; valid literal evidence is not an inference-quality proof. Worker is not source authority.
Fresh processinert and oldregression; fullgate/mainV8/hash/selectivecommit. Next C2 native mode/
admission then structuredpresentation/remapping+desktop vertical before defaultappreadiness.
