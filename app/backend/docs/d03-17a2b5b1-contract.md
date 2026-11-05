# D03-17A2b5b1 — Saved rich-text content controls

4 November 2026; F05/F06/F11, baseline b5a1 `207880e`, 5573 passed +24 subtests, 45 skipped, 839 hashes. Scope: a pure source-backed reader for
unbound rich-text SDTs, block paragraphs at story level and inline contents in all
already-supported paragraphs. No application admission, rewriting, renderer, DB,
API, dependencies, old tests or runner changes. All previous hashes remain exact.
New src/ara/docx_analysis/visible_controls/, own acceptance/edge tests, this contract,
result, guide and development queue only. Freeze/red → implementation/review → full
gate → readonly main V8/hashes → selective local commit. Documented preparation fixes
in these new tests are allowed only with assertions unchanged. No source/test/contract
changes during full gate. Continue next bounded cycle after completion.

## Evidence and boundary

[SdtContentBlock](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.sdtcontentblock?view=openxml-3.0.1)
contains the last saved content, potentially cached. This cycle neither refreshes it
from custom XML nor retrieves glossary data. dataBinding and true showingPlcHdr are
explicit gates; no policy for analyzing placeholder prompts is invented.
[RichText](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.sdtcontentrichtext?view=openxml-3.0.1)
is the default when no control type is specified. Only absent/richText type is enabled.
Plain text controls have additional whole-control formatting constraints and, together
with date/combo/checkbox/picture/group/repeating types, need separate proof.
[RunProperties](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.runproperties?view=openxml-3.0.1)
in sdtPr describes initially entered replacement text; sdtEndPr formats the delimiter.
Neither is a source run or a blanket visibility override for saved child runs.
Official ECMA-376 Part 1 2016 Strict XSD CT_SdtBlock/Run/Pr/EndPr/Placeholder inspected:
wrapper permits optional sdtPr, sdtEndPr, sdtContent in that order, each at most once;
content may be missing/empty; sdtEndPr contains zero or more rPr.

## APIs and proofs

build_control_snapshot(data, *, document_id, storage_revision, source_sha256, limits=None),
map_control_spans/span. Same exact NoteSnapshot shape, fixed profile
`docx-analysis/final-visible-rich-controls-v1`. Reuse b5a1 field reader and existing
private shared builder/profile/preflight hooks with no modification. All prior APIs
keep their old profiles and rejection boundaries. Original tree/node paths and source
bytes are retained; never promote/copy children, relabel parts or fabricate characters.
Exact source-backed batch mapping rebuilds once, even for empty queries; all snapshot,
source/profile/coverage/note links and Unicode source intervals remain verified.

## Closed supported grammar

SDT wrapper/content/pr/endPr have no attrs and only whitespace outside children.
Wrapper order/uniqueness exact. Missing/empty content emits empty_control metadata,
no paragraph or character synthesized. sdtPr singleton whitelist: alias/tag required
w:val string; id/label signed integer <=20 digits; tabIndex unsigned <=20 digits;
lock optional w:val enum unlocked/sdtLocked/contentLocked/sdtContentLocked; temporary
and showingPlcHdr optional exact six OnOff values; showingPlcHdr true blocks; richText
empty no attrs; placeholder exactly one empty docPart with required w:val string;
rPr uses existing closed run-properties grammar as metadata, its selector/visibility
never changes existing child runs. Metadata names/IDs/placeholders never enter text/DTOs.
sdtEndPr accepts only known rPr metadata. Properties use a singleton whitelist; no generic XML
schema-validity claim is made for all Office dialect ordering variants. Duplicate/unknown properties, dataBinding,
other types, foreign namespaces, invalid flags/attributes/payload remain blocked.

Inline rich controls use the same retained grammar as their containing paragraph:
real runs/hyperlinks/insertions/deletions/nested controls/closed fields/note references.
Block controls at main/header/footer/active-note level contain paragraphs and nested
block controls; paragraph inline controls work within an existing physical table cell.
A block control directly wrapping table/row/cell, cell-level block controls, section
boundaries/history within block controls, moved-range contexts not already supported,
MC/customXml remain explicit gates. Existing table/section/move proofs run unchanged.
Unknown retained content cannot be skipped merely because it is hidden or field code.
Deleted inline control branches preserve existing final-state exclusion rules.

Each retained control boundary inserts private field barriers: all simple/complex
fields must close within that control, or wholly outside. Nested control boundaries
also cannot be crossed by active fields. This is a capability restriction, not a
claim that Word cannot represent those cases. No fake public runs/paragraphs. Fields
may span several paragraphs inside one block control within the same proven flow.
Visibility and note activation stay after field processing. Any active failure empties
all public text/fragments/paragraphs/runs/references, preserving atomic completeness.

## Bounds and acceptance

Before any semantic DOM, reuse whole-source aggregate XML/table/move/note budgets and
field counter. Additional whole-source SDT count max min(10000,max_pieces), including
unused/deleted/history branches; nesting max min(32,max_xml_depth), checked before push.
Namespaced control tags count for both known Word namespaces; namespace/character budget
already bounds opaque values. No product limit or truncation; no application I/O.

Positive strict/custom UTF16, absent/explicit type, optional/missing/empty content,
block/inline/nested/table-inline/header/note flows; original anchors/canonical digest,
Unicode/tab/break mapping; control metadata does not become text or hide child runs;
child style/direct visibility still works; fields and note markers preserve context.
Negative malformed wrappers/property flags/payload, bound/placeholder/unknown controls,
wrong context, field crossings, unsupported hidden content, raw unused/deleted budgets
before DOM, source/profile forgery and inert subprocess. Targeted+regression/full gate,
all prior hashes and main V8 unchanged. Native Word and remaining matrix stay separate.
