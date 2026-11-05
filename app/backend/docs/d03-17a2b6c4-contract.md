# D03-17A2b6c4 — structured dismissal correspondence

5 November 2026. Baseline: verified C3 `255a066`.
F09/F12: retain a document-local hide only across proven structured correspondence. This
is a conservative extension of the existing rule, not fuzzy matching or a product-scope change.

## Paths / verification

New private package src/ara/docx_analysis/remapping/structured/{__init__,_source,_groups,_match}.py.
Only two old source hooks: remapping/_match.py fixed-profile dispatch after existing full
verification/identity/same-source guards; docx_review_resolution/_resolve.py structured
label/suffix work estimate. New tests/acceptance/test_docx_structured_remapping.py, this
contract/result, docs/docx-structured-correspondence.md, docs/development-queue.md,.runtime.
No old tests/contracts/limits DTOs/source readers/codecs/keys/presentation/SQL/models/schema/
HTTP/worker/desktop/runner/tasks/progress/dependency changes. No mainV8 migration or publication.
Freeze/red, implementation/review/regression/full check.sh, frozen hashes and read-only mainV8,
selective local commit. New-test preparation-only fixes allowed when documented with frozen
assertions unchanged. No source/test/frozen-contract edits during full gate.

## Admission and unchanged legacy behavior

Both complete (source,attempt,result) triplets are restored and current RemapLimits checked
before any no-match branch. Same document required. Profile/policy/executor/rule/finding
semantics retain existing guards. Exact same source SHA continues to use exact dismissal keys
across revision/attempt for every supported structure. Legacy profile uses its unchanged old
context/paragraph matcher. Only the fixed direct-lists profile dispatches to new private code.
No caller registry, guess from text or automatic source profile upgrade.

Unknown/corrupt source/result remains a content-safe error; lack of a unique correspondence
for a source-valid structure returns an empty mapping. Never catch an arbitrary implementation
exception and call it normal no-match. Current _match error classification remains unchanged.

## Bounded original-source context

Source revalidation has already proved the immutable bytes and complete manifest, including
aggregate raw XML bounds before DOM allocation (100k nodes,depth128,8Mi characters). Open the
same in-memory package and parse each needed original paragraph part plus main exactly once
using existing safe ZIP/parser helpers; no filesystem/network/secret reads. Use bounded tree
builders and retain the earlier aggregate source proof; unknown manifest addresses fail.

Index nodes by (part_name,original path), never by path alone. Compute Merkle subtree hashes
bottom-up once per node: expanded tag, sorted attributes, text, tail, child count, ordered
child hashes. This is a new private fingerprint, not a change to old tree(). It retains raw
hidden/revision/unselected branches, whitespace and child positions without repeated O(n²)
subtree serialization. All caches are local to one call.

Global seal: main part name; a whole-main frame fingerprint that replaces EACH original Word
body's children by a fixed hole while retaining root/body/wrapper tags/attributes/text/tails
and ordering outside bodies; all non-main entry(name,type,sha) except the old metadata MIME
exclusions; ordered raw main sectPr subtree digests. The body hole permits distant edits
without assuming body is a direct raw child (MC may wrap it). Paragraph story identity still
binds the exact original (part,path), so a different selected body cannot reuse a match.

Cross-source section boundary: only raw sectPr nodes directly under a Word body are supported
here. Any other main sectPr (paragraph-owned, historical, wrapped) makes cross-source mapping
empty after complete source verification, not corrupt_result. Exact-source mapping still works.
This explicit conservative boundary avoids guessing section applicability. Do not claim full
paragraph-section correspondence; it is a possible later refinement, not a new source gate.

For each paragraph derive nearest original Word story ancestor body/hdr/ftr/footnote/endnote
and its part/path/tag/attributes. Compute an ancestry digest top-down, excluding the story
root itself: parent ancestry + whole parent subtree digest + child index. Direct story children
have empty ancestry; inserting a main sibling may shift an intact table/control, but changing
any enclosing table/grid/row/cell/control/MC subtree or relative cell position vetoes its
paragraphs. Source-proven nested inline revisions remain in the paragraph subtree digest.
No entire main body hash is used as paragraph ancestry.

## Groups, context and candidate correspondence

One group per snapshot paragraph in deterministic logical order, including empty groups for
context. Attach all ordered literal fragments to their exact paragraph. Normalize pieces to
part-aware paths relative to the paragraph, retaining kind, offsets and source offsets; never
join separate fragments or add generated characters. Keys exclude source SHA, fragment IDs,
absolute analysis offsets and shifted absolute paragraph paths. Bind story identity, raw tree,
ancestry digest and relative fragment segmentation. Per-story styled prefix hashes whole prior
paragraphs containing any original pPr subtree (including hidden/unselected markup), with a
streaming digest, not copied growing prefix strings.

Own list context binds num_id,level,ordinal,format,label,suffix; relative numPr; original
numbering definition/instance/optional override (part,path); and fragment associations as local
positions. Own note links bind kind, target(part,path), relative reference path, and local
before/after fragment positions. Source hashes/fragment IDs are not compared across revisions.
Empty/marker-only groups still affect neighbors/prefix/counters even though they cannot supply
cross-source candidates. All original raw/context facts must agree; metadata shape is not proof.

Candidate uniqueness uses (part,literal text tuple); no empty/whitespace-only candidates and no
arbitrary selection among repeated groups. Match full group key with same raw/context evidence.
Require equal immediate neighbor signatures within the SAME story (raw subtree, ancestry digest and own
list/reference semantics, explicit start/end markers). Reject ALL members of crossing pairs
with linear prefix/suffix inversion detection, not an arbitrary longest subsequence. Keep the
one-to-one group map before converting to ordered fragment-position correspondence.

## Note dependence and finding semantics

Current source grammar permits note references only from main, not nested notes/header/footer.
For a note group, every incoming reference to its exact target story must have a matched main
parent group. Compare COMPLETE old incoming sets normalized through that parent map against
new incoming sets: mapped paragraph identity + relative reference path + kind + target identity.
Build incoming sets once per target and cache dependence verdicts per target story, not
once per note paragraph. Multiple/shared references all must correspond. A changed/new/removed/unmatched/marker-only
parent prevents transfer of the note finding; it does not corrupt the source. No recursive
reference graph or invented displayed note number. Unchanged note parts alone are insufficient.

Flatten surviving group pairs to old fragment ID→new fragment ID, preserving positions.
Reuse existing full finding signature, including primary AND related evidence, rule/question/
assessment and executor identity. Matching primary alone cannot hide a changed related context.
Output existing FindingTransfer records only; no preferences, source or result mutation.

## Resolution budget and acceptance

The existing untrusted resolution estimate adds sum(label length + one suffix character for
space/tab, zero for nothing) on direct-lists snapshots to len(analysis_text), for each existing
source pass. Old-profile estimate unchanged. Check array/type/cardinality/label/suffix bounds
before summing; proof still comes from codec before any dismissal use. A budget failure stays
preferences_resolution_limit/413 with no partial alias subset. No new configurable limits.

Frozen acceptance includes direct lists and distant edits; duplicates/order crossing; blank
item counters, global numbering/styles and styled prefix; whole table/cell/related contexts;
controls/MC/inline revisions; main body MC wrapper; strict+UTF16/final sections; explicit
paragraph-section no-transfer; multi-fragment note/image boundaries; part/path collisions;
shared/changed/new/removed/marker-only note parents; exact-source revisions for all structures;
corruption before early identity rejection; limits; pure resolution aliases and generated cost.
Regression covers old matching/resolution/preferences/presentation/HTTP; native/PG tests remain
unchanged. Persistent structured HTTP/desktop integration follows in its own cycle. Real ML,
UI/native Windows/Word/signing/TLS gates remain separate.
