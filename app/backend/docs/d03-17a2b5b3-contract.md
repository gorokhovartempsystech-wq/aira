# D03-17A2b5b3 — saved plain-text controls with uniform current formatting

5 November 2026, F05/F06/F11. Baseline: verified C2C `969ca5a`.
An opt-in reader/mapping extension, not editing controls, application admission or
native Word parity. Source DOCX remains untouched.

## Paths and verification

New src/ara/docx_analysis/visible_plain_controls/, new acceptance
test_docx_visible_plain_controls.py and edge test_visible_plain_controls_edges.py;
this contract/result, docs/docx-visible-plain-controls.md, docs/development-queue.md,
ignored .runtime evidence. Three private hook files only:
visible_controls/_grammar.py, visible_controls/_reader.py, visible_compatibility/_api.py
(under src/ara/docx_analysis). Old APIs/defaults/profiles/tests unchanged. No schema,
dependencies, runner/tasks/progress or product-scope changes. All prior hashes outside
these hooks must match. Freeze/red → implementation/review/regression/full gate →
readonly main V8/hashes → selective local commit. Documented new-test preparation
corrections allowed with assertions unchanged. No source/test/frozen-contract changes
during full gate. Continue next bounded cycle after completion.

## Evidence and fixed supported subset

[ECMA-376 Part1 fifth edition2016](https://ecma-international.org/publications-and-standards/standards/ecma-376/)
§17.5.2.44, printed545–546 (PDF554–555), and Strict CT_SdtText/CT_SdtPr inspected.
[Microsoft SdtContentText](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.sdtcontenttext?view=openxml-3.0.1)
identifies the uniform-formatting/one-paragraph-or-cell restriction. Plain controls
cannot wrap a row/table. multiLine governs adding new soft breaks, not display of
existing ones: validate optional OnOff but preserve existing br(textWrapping)/cr even
when false/absent. Do not infer editor permission or remove stored breaks.

Enable unbound text control type alongside all existing rich/default control behavior.
Exactly one declared text/richText type; duplicate/mixed/other type, dataBinding and
active placeholder remain explicit gates. text is a leaf, only optional w:multiLine,
existing exact boolean spellings. Input rPr/endPr do not override saved run formatting.

Plain inline content belongs to one logical paragraph. Plain block content: at most
one p. Plain cell content: at most one tc, optional first tcPr, at most one p. Empty or
absent sdtContent is legal in these roles. Plain row type refuses even when empty.
Resolve actual logical role through the source view parent index and surrounding
sdtContent/sdt wrappers; never infer it from original path truncation or payload shape.
Regular table geometry/visibility proofs remain mandatory.

Allowed current content: ordinary literal runs t/tab/soft br/cr/commentReference,
supported bookmark/comment-range markers, retained ins and excluded del wrappers.
Normal old grammar validates attributes, order, revision shape, style usage and hidden
content. Current nested controls/hyperlinks/fields/note markers/media/custom XML and
page/column breaks inside plain controls remain explicit unsupported gates. Rich
controls preserve their prior fields/notes/table behavior. No control crossing by fields.

Uniformity proof across segmented current runs: one owning paragraph and identical
canonical current rPr children/attrs/selectors (unordered distinct property names,
None/empty rPr both empty; ignore historical rPrChange after existing grammar proof).
Same paragraph and same selector/properties ensure same current formatting basis;
do not guess equivalence of different style IDs or explicit versus inherited props.
This is a conservative proof, not full formatting normalization. All current runs,
including hidden runs, participate. Deleted payload is excluded; retained insertion
runs participate. Reject unproved formatting with unsupported_plain_control_formatting.
No concatenation/rewrite of source runs. Source slices and Unicode offsets remain exact.

## API and reuse

New build_plain_control_snapshot(data, *, document_id, storage_revision, source_sha256,
limits=None), map_plain_control_spans(...requests,limits=None), singular span equivalent.
Same exact identity/bytes/VisibleLimits, NoteSnapshot and mapping DTOs/errors. Fixed
docx-analysis/final-visible-plain-controls-v1 profile, same C2B MC style profile/policy.
No caller view/catalog/context/reader/profile injection. One fresh selected view and
coherent catalogs, through private C2C builder extraction with old fixed defaults.
Original package validation/raw controls/fields and all semantic/output bounds active.

Old Grammar gets default extended_property refusal and default control_code; old Reader
gets grammar_type default. New Grammar validates plain type and records its content;
normal cache prevents repeated parsing. New Reader indexes bounded logical parents
before inherited table-control proof, then validates every recorded plain control after
normal plans/field/table validation and before contexts/output assembly. This lets a
plain cell skip descendants only when the existing table proof has actually established
that its cell is deleted. Never infer deletion from an unproved cellDel marker.
Emit metadata plain_text_control/plain_control_format_proven; no output precedes proof.
No new schema table/global enum/state, no semantic XML reparse/serialization, no I/O.
Old public profiles retain behavior and mutually reject snapshots with the new profile.

Any unsupported active content, format or source part gives atomic incomplete output,
no text/fragments/paragraphs/runs/references. Existing early blocked context behavior
preserved. Mapping rebuilds once per batch including empty, validates exact DTO and
compares exact source-backed snapshot; rehashing is not authority. All original anchors
and canonical hashes are version-bound, private text absent from repr/errors.

## Acceptance

Inline/block/cell, nested rich and supported header/note/table contexts; Strict UTF16,
MC and custom part addresses; uniform segmented runs, Unicode mapping; all multiLine
spellings and omitted with saved br/cr; current styles/hidden runs, historical rPrChange,
comments/ins/del, input/end properties not overrides; empty controls. Refuse invalid
type/flags/roles/cardinality/uniformity, retained unsupported content including hidden,
row/table/plain nesting, boundary crossing. Exact old/new profiles/rehashed attacks,
batch rebuild once, raw quotas, manifest/output bounds and inert process. Full gate,
unchanged hashes outside three hooks and readonly V8 required.
