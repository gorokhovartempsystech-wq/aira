# D03-17A2b5a1 — Stored field results and source mapping

4 November 2026; F05/F06/F11, baseline b4b2 `c733fd2`, 5528 passed +24 subtests, 45 skipped, 831 hashes. Product policy remains
current-product-scope.md and cached-result boundary in d03-17a2b-design.md: never
execute/update field commands, recalculate TOC/PAGE or access external targets.
No DB/API/admission/export/UI/dependencies/runner changes in this cycle.

## Allowed paths and gates

New `src/ara/docx_analysis/visible_fields/`, own tests/acceptance/test_docx_visible_fields.py,
tests/docx_documents/test_visible_fields_edges.py, contract/result/guide/queue.
Only three old files can gain private default-preserving reuse hooks:
visible_notes/_build.py (reader_type, profile, extra_preflight), _assemble.py (profile
keyword on Output), _shape.py (profile keyword on validate). Old public APIs keep fixed
old profiles/default reader/preflight; every previous test is immutable. No copied
whole pipeline or global schema monkeypatching. All prior hashes except these three
must match. Freeze/red, implement, review additions, targeted/regression/full gate,
readonly main V8, result/local commit. No source/test edits during full gate. Documented
new-test setup corrections allowed without weaker assertions; old tests unchanged.

## Evidence and explicit semantic boundary

[FieldChar](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.fieldchar?view=openxml-3.0.1):
complex fields have begin/end, optional separate; without separate the field is codes
only, with no result. Nested fields are allowed. This first reader requires exact
closed structure; malformed/unclosed Word fallback remains an explicit gate.
[SimpleField](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.simplefield?view=openxml-3.0.1):
its instruction is w:instr, children represent stored results.
[FieldCode](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.fieldcode?view=openxml-3.0.1):
instrText is ordinary text outside a complex field's code region. Therefore the old
technical shorthand 'instrText not requirements' applies only to a proven code region;
it does not authorize deleting literal instrText outside that context.

Official [ECMA-376 Part 1](https://ecma-international.org/publications-and-standards/standards/ecma-376/)
2016 Strict XSD CT_SimpleField/CT_FldChar/CT_Text/ST_FldCharType inspected: fldSimple may
be empty, instr is required ST_String (possibly empty), flags optional; fldChar type
begin/separate/end required; ffData child exists but needs its own content proof;
CT_Text allows xml:space. Empty simple wrapper is a known empty stored result, not a
fabricated requirement. No instruction syntax evaluation is needed to read its cache.

[FieldChar.Dirty](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.fieldchar.dirty?view=openxml-3.0.1)
and [SimpleField.Dirty](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.simplefield.dirty?view=openxml-3.0.1)
mark invalidated results. True stays an explicit invalidated_field_result gate in this
cycle, including hidden markers and locked fields; false/missing accepted. This is a
conservative capability boundary, not deletion or execution of invalidated content.
[updateFields](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oi29500/d8bc14c0-5eeb-49c1-9ba7-8edf4c33976f)
does not authorize recalculation by AIRA. Output is the saved source result, not a
promise of refreshed field values, Word layout, display numbering or native parity.

## API, shared pipeline and snapshot

build_field_snapshot(data, *, document_id, storage_revision, source_sha256, limits=None)
and map_field_spans/span. Same exact bytes/identity/SHA, VisibleLimits and fixed errors,
archive-before-hash boundary; no application I/O. Result exact NoteSnapshot with fixed
profile `docx-analysis/final-visible-field-results-v1`, same policy, all note links and
old source-slice DTOs. Reuse fresh section/note/style proofs, table-style cache, actual
story roots/relationships/coverage and note activation. Field commands/ET/source objects
never appear in returned metadata/repr/errors. New profile selects FieldReader via
private builder hooks; Output profile controls both fragment IDs and snapshot digest.
Old public field-free profiles stay behaviorally identical and reject the new profile.

Validator checks the same exact NoteSnapshot schema under a fixed new profile. Batch
mapping rebuilds from original source once, including empty batch, compares every
field including references/coverage and maps exact intervals. instrText outside code
maps as ordinary text to that actual instrText node, code-point offsets unchanged.
Rehashed forged text or different profiles/parts/links cannot authorize mapping.

## Closed grammar and final-state ordering

FieldReader extends NoteReader's run/inline hooks. fldSimple: required w:instr, optional
w:fldLock/w:dirty, no other attrs, whitespace outside inline children, same supported
inline final grammar in children. Nested simple/complex fields supported. fldChar:
empty leaf, required w:fldCharType in begin/separate/end, optional fldLock/dirty flags;
ffData/fldData/unknown retained children or attrs stay blocked. instrText: leaf text,
only optional xml:space preserve/default. Flags use current exact six OnOff spellings;
invalid forms fail even when a run is hidden. Properties and histories keep old rules.

Interpret field structure after the retained plans are collected, BEFORE effective
run visibility. Hidden begin/separate/end still delimit fields; hidden result runs
remain excluded by existing visibility rules. Deleted/history/moveFrom/deleted-cell
branches do not contribute field tokens; insertion/moveTo retained plans do. Unknown
retained markup cannot be skipped just because it occurs in a code or hidden region.

Private event sequence contains paragraph start/end, real Run plans, and simple
wrapper enter/exit. No fake public runs/paragraphs or XML rewriting. Build flow maps
first; then one linear stack pass filters atoms. Simple frames have implicit result;
complex begin enters code, separate transitions the top complex frame exactly once,
end closes the top complex frame. A simple exit must match the top simple frame;
complex fields cannot escape/cross it. All frames must close before story end. Duplicate
separator, missing begin/end, mismatched wrapper or unknown marker type gives blocked,
not Word fallback guessing. Any ancestor complex code suppresses all known content,
including a nested field's cache and ordinary main note-reference atoms. No note
activation from code. instrText in code becomes excluded/field_code_content; outside
all code regions it becomes literal text. Nonempty ordinary atoms in code are also
excluded; markers never become VisiblePiece.

Known empty simple wrappers and code-only closed complex fields emit field_without_result
metadata and no characters. A complex field with separator has cached_field_result
metadata, even if the stored result is empty or hidden. fldSimple with content emits
cached_field_result. Markers emit source-anchored metadata; instruction values remain
opaque and are never executed, copied into DTOs or used to fetch links. Literal pieces
before/result/after concatenate as the saved display does; no invented field number or
source character. Existing note markers still create their separate segment boundaries.

## Flow and section barriers

A field may span paragraphs only within the SAME actual physical flow (body or one
cell). While a frame is open, changing body/cell/nested-cell/another-cell flow is blocked,
including empty paragraphs/cells. Per-story readers prevent cross-main/header/footer/
note pairing. A current section boundary belonging to a paragraph is checked at its
END, not when its pPr is parsed. An open field crossing it remains unsupported. Final
body section/end of story cannot silently repair an unclosed field. Known section/table
properties and all old unsupported paragraph/table/move grammar retain their gates.

## Bounds and atomicity

Reuse aggregate whole-source note/story/XML budgets. Extra SAX field preflight runs
before ANY semantic DOM: all main/style/settings/header/footer/note parts, including
excluded and unused branches, count every fldSimple and declared fldChar begin. Fixed
technical count maximum min(10000, VisibleLimits.max_pieces); instruction characters
remain under aggregate XML char budget. Active field stack depth max min(64,max_xml_depth),
checked before pushing. Private token/atom processing is linear in bounded source.
Output paragraph/run/fragment/piece/text/coverage/reference/manifest budgets stay global.
No new product size limit and no truncation.

As in b4b2, any active grammar failure or unread part makes the entire new snapshot
incomplete with empty text/fragments/paragraphs/runs/references. No orphan-note/story
exclusion without full reference/content proof. Source DOCX bytes remain unchanged.

## Acceptance

Strict UTF16/custom parts, both field syntaxes, nested field in code/result, literal
instrText outside code, same-flow cross-paragraph result, legitimate empty/code-only
fields, hidden markers versus hidden result, final deleted/history branch isolation,
notes activated only from retained result, fields in main/header/table/note, original
pieces/digests and exact Unicode/tab/break mapping. Atomic malformed structures,
wrapper/cell/section/story crossings, invalidated cache/flags/unknown attributes/ffData,
raw field count before DOM including excluded/unused branches, shallow XML with deep
semantic stack, manifest bounds, old API unchanged, one rebuild per batch incl empty,
forged/stale profile/content refusal and inert process/no command execution. Full gate,
prior hashes/main V8, local commit and continue the next bounded cycle.
