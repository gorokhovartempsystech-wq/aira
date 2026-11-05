# D03-17A2b4b1 — Original footnote/endnote definitions

4 November 2026, F05/F06/F11. Baseline: a2 completed in `3e39d61`, full gate
5429 passed +24 subtests, 45 skipped. This cycle provides a pure, source-bound
catalog of note definitions and their main-part relationships. It does not identify
retained visible references, emit analysis text or authorize exclusion of orphan
notes. The next reader must preserve marker boundaries and links to note contents.

## Allowed changes and workflow

New namespace `src/ara/docx_analysis/notes/`; own acceptance test
`tests/acceptance/test_docx_note_catalog.py`, edge tests
`tests/docx_documents/test_note_catalog_edges.py`, this contract, result, guide and
queue. No old source/tests, dependencies, schema, runner or tasks changes. Freeze
contract/tests, record red, implement, review and add cases, targeted/regression/full
gate, readonly main V8 snapshot, local commit. All previous 808 hashes stay unchanged.
New-test setup corrections require a recorded explanation and unchanged assertions;
this does not permit weakening the acceptance criteria or changing old tests.

## Primary evidence

[Note type](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.footnoteendnotetype.type?view=openxml-3.0.1)
defaults to normal when omitted; nonnormal definitions cannot be referenced as normal
notes. Classification uses the actual type, not magic IDs -1/0/1. The official
[ECMA-376 Part 1](https://ecma-international.org/publications-and-standards/standards/ecma-376/)
Strict XSD CT_FtnEdn, CT_Footnotes/CT_Endnotes and ST_FtnEdn was inspected: required
ID, optional type, at least one content child per note, possibly empty part roots,
four types normal/separator/continuationSeparator/continuationNotice.
[FootnoteReference](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.footnotereference?view=openxml-3.0.1)
distinguishes a generated number from the target identifier. Reading that marker is
outside this physical catalog; no native Word parity is claimed here.

## Public interface and immutable records

`read_note_catalog(data, *, source_sha256, limits=None)` requires exact bytes and a
lowercase SHA-256; check archive size before hashing, then freshly open_docx. Package
malformation/DTD/entities preserve DocxError. NoteCatalogError has fixed codes
invalid_input, source_mismatch, note_limit_exceeded. No application I/O, environment,
DB, model access or network. No source rewriting.

NoteLimits: frozen slots, exact integers in 1..default, revalidated on every call
including mutated/deleted fields. Defaults: max_xml_nodes=100000, max_xml_depth=128,
max_xml_characters=8388608, max_parts=128, max_notes=10000,
max_manifest_bytes=33554432. Aggregate every candidate note XML part before any
semantic DOM, including unbound/special/nested opaque payload, namespace URIs and
attributes. max_notes counts every footnote/endnote element in either Word namespace,
including nested ones. Check max_parts before semantic parsing. These are technical
bounds, not an agreed product size limit.

Fixed profile `docx-notes/original-definitions-v1`:

- NoteCatalog(source_sha256, profile, status, main_part, parts, issues, catalog_sha256).
  indexed if typed parts exist (including empty roots), absent if none; atomic blocked
  with parts=() on unresolved relationship or invalid part/root/definition.
- NotePart(kind, part_name, root_anchor, linked, definitions); kind is footnote/endnote.
  linked means a matching main relationship, not visible use or permission to exclude.
- NoteDefinition(note_id, note_type, anchor), canonical integer ID and actual type.
- NoteIssue(code, anchor optional).

All records are frozen slots; part names, IDs, addresses and collections are hidden
from repr. Do not retain text, author/date/r:id, ET nodes, DocxSource or source bytes.
SourceAnchor uses actual part root () and direct-child index; definitions retain
physical order, parts sort by canonical name. Streaming sorted compact JSON digest
excludes catalog_sha256 and respects the exact manifest byte bound. No complete or
analysis_text field, reference visibility or native layout claims.

## Relationships and physical grammar

Candidate MIME types are exactly
`application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml` and
`application/vnd.openxmlformats-officedocument.wordprocessingml.endnotes+xml`.
Main-part relationships use the exact transitional/strict standard URI with plural
footnotes/endnotes. At most one per kind, even if duplicate links target the same
part. A present link must be Internal and resolve to a candidate of matching kind;
otherwise blocked/unresolved_note_relationship. Another part's relationship does
not bind main notes. Never guess `word/footnotes.xml` or fetch external targets.

Unlinked candidate parts are retained with linked=False. Additional unbound typed
parts and duplicate IDs across separate parts are allowed as independent metadata.
These facts do not authorize orphan exclusion; retained reference resolution is
future work, where the main-bound part will be the sole target for its kind.

Each original root must be footnotes/endnotes in either known Word namespace,
matching the MIME, without attributes, with whitespace outside children and only
direct same-namespace singular note children. Each definition requires w:id and
allows only w:type in addition. IDs match `[+-]?[0-9]{1,20}` and normalize to integers.
Duplicate canonical IDs in one part, including -0/+00 aliases, cause atomic
blocked/duplicate_note_id; no first/last wins. Missing type means normal; explicit
type must be one of the four types above.

Unknown attributes/root children/type, foreign namespace or malformed definition
cause blocked/invalid_note_markup. Each definition contains at least one child and
whitespace wrapper text/tails. Inner payload remains opaque and may include tables,
fields or unknown structures. Nested fake definitions are never part-level records,
but the preflight counts them. The later selected-story reader must prove the content
before analysis. Agreement between a part's namespace and the main document belongs
to that reader, not this physical index.

## Acceptance and completion

Synthetic strict UTF-16/custom parts; both kinds/all types/omitted type/nonmagic
negative and zero IDs; actual anchors/order/digests/frozen records; absent/empty,
bound/unbound/other-owner relationships; duplicate IDs and links, wrong MIME/kind,
external links; malformed/foreign roots/attributes/types and atomic failure after a
valid prefix; nested opaque payload; aggregate XML/node/depth/namespace/attribute,
part/note/manifest limits before DOM; exact input/hash, archive before hash, inert
fresh process. Then regression, `bash scripts/check.sh`, 808 previous hashes and
readonly main V8, result/guide/commit; continue under current user authorization.
