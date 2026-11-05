# D03-17A2b4b2 — Visible note references, stories and exact mapping

4 November 2026, F05/F06/F11. Baseline b1 `11b79da`: 5467 passed +24 subtests, 45 skipped; 816 hashes. Pure opt-in
reader only, no DB/API/ML admission, exports, UI, dependency or runner changes.
New namespace `src/ara/docx_analysis/visible_notes/`, own acceptance reading/mapping
and edge tests, contract/result/guide/queue. Exactly three shared source files may
change through default-preserving hooks: visible_main/_reader.py (root_path_for and
extended_run), tables/_context.py (root_path_for), moves/_index.py (root_path argument).
All previous tests and every other old source stay unchanged. Freeze/red, implementation,
review additions, targeted/regression/full gate, readonly main V8, local commit.
Documented new-test setup corrections allowed without weaker assertions. No source
edits while full gate is running.

## Evidence and conservative scope

FootnoteReference (SDK) defines generated marker and rejects note-inside-note references:
https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.footnotereference?view=openxml-3.0.1
FootnoteReferenceMark is an empty generated label, not text; its style is optional:
https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.footnotereferencemark?view=openxml-3.0.1
Word supports reference IDs -2147483648..32767; comments/textboxes ignored:
https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oi29500/540efde2-e14f-4ab0-b0aa-7961a41fe10b
https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oi29500/d399b2b6-68ad-4c7f-aba0-0d1b77a5aa60
Earlier Office clarification rejects header/footer references; until native resolution
our supported contexts remain only main paragraphs and current table-cell paragraphs:
https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oe376/a028bde7-ec7e-4850-a583-17cf5e0a63b4
CustomMarkFollows suppresses automatic numbering; it does not identify a safe literal
character range to remove. True remains an explicit gate; absent/false supported:
https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.footnoteendnotereferencetype.custommarkfollows?view=openxml-3.0.1
Move range starts may not have duplicate IDs; the container name links a move pair:
https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.movefromrangestart?view=openxml-3.0.1
No layout, display-number calculation, native Word parity or complete DOCX claim.

## API and manifest

build_note_snapshot(data, *, document_id, storage_revision, source_sha256, limits=None),
map_note_spans/span; same exact input identity, bytes/source check, VisibleLimits,
fixed errors and original archive-before-hash boundary. Fixed new profile
`docx-analysis/final-visible-note-stories-v1`, same policy final-visible-no-comments-v2.

Frozen slots NoteSnapshot extends VisibleSnapshot with references tuple. New frozen
NoteReference(kind, reference_anchor, paragraph_anchor, target_anchor,
before_fragment_id, after_fragment_id); anchors/collections repr-hidden, kind footnote
or endnote, before/after optional existing fragment IDs. No raw ID, label/author/r:id,
ET/source references. Original main_part never changes. References ordered by retained
main reading order. Normal notes emitted once, ordered by first retained use, after
main and unique section stories. Each note story_anchor is its original definition
(path i, part notes.xml), flow is that note or its actual table cell. Main/header/footer
flow rules unchanged. No copied/wrapped XML or relabeled DocxSource.

New exact shape validator checks every inherited field against old schemas with the
new fixed profile, exact new references separately, no global schema mutation. Old
public mapping/profile still rejects NoteSnapshot. Bound references and resulting
fragments by max_pieces and max_paragraphs respectively; count all paragraph/run/piece/
text/coverage/manifest outputs globally. Batch mapping does one fresh original rebuild,
also on empty requests; compare entire snapshot including references then map pieces
using existing exact interval code. Rehashing forged references or source paths fails.

## Preflight and source selection

Before any semantic DOM count all main/styles/settings/header/footer/footnote/endnote
XML, including inactive, unbound, special, hidden and opaque nested content. Use one
aggregate visible counter plus global table/revision/move counters on all story XML;
count candidate note parts/definitions with NoteLimits and shared XML caps. Additional
style/table-style preflight precedes semantic styles. Read fresh SectionCatalog,
NoteCatalog and one StyleContext; cache one table style proof against exactly it.
Any catalog or active-story failure makes the whole new snapshot incomplete with
empty paragraphs/runs/fragments/analysis_text/references; retain explicit blockers.

Resolve ONLY retained visible marker atoms after inherited run visibility. Main run
footnoteReference/endnoteReference: exact empty leaf, required w:id bounded signed
20 decimal digits and optional boolean w:customMarkFollows. Recognize syntax before
visibility; only visible markers resolve targets/native ID range/custom mark semantics.
Hidden valid references and references inside excluded deletion/moveFrom/history/deleted
cells do not activate notes. Unrecognized retained branches cannot authorize orphan
exclusion. Main/table-cell inserted/moveTo/current references follow the old grammar.
Header/footer references and nested note references remain explicit context gates;
labels footnoteRef/endnoteRef allowed only in their matching selected note, empty/noattrs.

Resolve against the sole fresh main-linked NotePart of matching kind and canonical ID.
No target/missing link/special type -> unresolved_note_reference; active IDs outside
native range -> unsupported_note_identifier; true customMarkFollows ->
unsupported_custom_note_mark. A shape-valid hidden reference does not trigger those
semantic gates. Same ID in foot/end is independent. Additional unbound part cannot
satisfy main reference. Repeated visible refs produce separate links, same note text
once. No magic special IDs. Matching generated self label emits metadata, not reference.

## Marker boundaries and text

Reader extended_run defaults to previous Refusal. Note reader adds private empty
boundary atoms; these never become VisiblePiece. Existing contexts removes hidden-run
atoms; split each retained paragraph at visible reference/label markers, without
joining text across a removed generated marker. Every nonblank segment is a fragment;
empty/whitespace-only segments are skipped. No fake literal number or source character.
Fragment IDs include original story/flow/paragraph and preceding marker SourceAnchor
(None for first segment) under the new profile/domain. Offsets stay original code points.
Synthetic two LF joins remain between fragments, without source slices.

Each visible reference records nearest nonblank fragment on its left/right within
the SAME paragraph, nullable at edges; consecutive markers may share neighbors. Keep
links even in marker-only paragraphs, where both are None. Compute links linearly,
never scan all fragments for each reference. A self label creates a boundary/metadata,
not a link or a new requirement. Old one-fragment/paragraph profiles remain unchanged.

## Original note subtree proofs and accounting

Build each used note part reader tree once; the fresh catalog has its own bounded
definition proof. Locate definitions by original catalog paths. Never
re-index a whole part once per note. Root-path hooks start at original definition's
physical child index. NoteReader uses same GridReader/StoryReader grammar for paragraph,
table/history/revisions/style/visibility and original-part relationships. Table proof
uses original subtree with prefixed anchors; move indexing is per note with original
prefix, no pairing across notes (or across main/header/footer). Before reading any
selected note from a part, scan that whole original part once for move-range starts:
validate their shape and uniqueness of (kind, canonical ID) and (kind, name), including
unused definitions. An invalid/duplicate start gives move_catalog_blocked; different
complete pairs in separate notes must have distinct identities within the part.
This avoids treating the same part's notes as independent ID namespaces. Existing conservative
moves in excluded/history contexts remain blocked; source content is not rewritten.

Only after all retained reference and active-content grammar and known part accounting
succeed: used normal definitions metadata/read, unused normal definitions excluded
unreferenced_note, nonnormal definitions excluded special_note. Unknown content in
unused/special payload is not interpreted, but its raw XML has been counted. Until
then note usage is unproven; no false orphan exclusion or included coverage with absent
fragments. The original note parts are known metadata only under that global proof.
Comments policy unchanged; unrelated unread parts remain blocked. Source bytes unchanged.

## Acceptance outline

Strict UTF16/custom paths, main/header/footer plus foot/end notes, same IDs/different
kinds, normal ID0 and negative; generated self labels, segment IDs/neighbors/consecutive
markers/marker-only; exact source anchors/nonBMP/tabs/breaks; normal notes once/first-use;
styles/hidden/deleted/inserted/moved refs and note runs; tables/current history/revisions/
grid inside notes; own hyperlink relationships. Missing/unbound/special/custom/native
range/foreign roots/nested refs unsupported atomic; unknown retained content disallows
orphan exclusion; unknown unused/special payload excluded only after full proof. Per-note
moves no cross-note pairing. Whole global budgets before DOM, fresh catalogs/styleproof,
parts parsed once and bounded work, no I/O. Rebuild once per batch incl empty; forged/
stale/foreign profile/link/anchors rejected even with new digest. Old profiles unchanged.
