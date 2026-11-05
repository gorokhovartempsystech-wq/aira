# D03-17A2b2b1 — структурный каталог перемещений Word

4 ноября 2026, после D05-06B/453fb30. Возвращение к обязательной DOCX матрице F06/F08/
F11 и ранее согласованному [разбиению](d03-17a2b-design.md). Один bounded цикл:
pure source-pinned каталог main-part inline move ranges. Это ещё не reader итогового
текста, не Word parity и не разрешение анализировать/редактировать moves.

Allowed только новые `src/ara/docx_analysis/moves/`,
`tests/acceptance/test_docx_move_catalog.py`,
`tests/docx_documents/test_move_catalog_edges.py`, этот contract/result/guide/queue.
Все прежние source/tests/profiles/API/ML/DDL, runner/tasks/progress/dependencies
unchanged. Ни один existing complete/unknown/native boundary guard не ослабляется.
Main V8/read-only user archive не меняются. Fixture только synthetic.

## Основание

Range start/end связываются по id, группы source/destination — по точному name.
ID revision wrapper не служит идентификатором пары, сравнение текста не требуется.
[Microsoft MoveFromRangeStart](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.movefromrangestart?view=openxml-3.0.1).

Run-level moveFrom должен находиться в source container с парным destination.
[Microsoft MoveFromRun](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.movefromrun?view=openxml-3.0.1).
Paragraph mark move относится к существованию абзаца, отдельно от содержимого.
[Microsoft MoveFrom](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.movefrom?view=openxml-3.0.1).
Прочитано4ноября. Ниже — сознательно узкий structural profile, не полная XSD/Word
conformance. Никакого accept-all/mutation исходного файла.

## Pure API

`read_move_catalog(data: bytes, *, source_sha256: str, limits=None) -> MoveCatalog`.
Exact bytes, lowercase hex64 SHA, совпадение с фактическим SHA; DocxLimits сначала
ограничивает archive size. Existing open_docx/ZIP boundary/DTD/entity rejection
используются без изменений. Ни файлов, сети, Word, settings/env, SQL при import/call.
`MoveCatalogError`: invalid_input,source_mismatch,move_limit_exceeded; только fixed
messages. Malformed package остаётся existing DocxError, без parser diagnostics.

Frozen slots DTO:
- MoveMember: kind("from"/"to"),revision_id(int),anchor,paragraph_anchor.
- MoveRange: kind,range_id(int),name,start,end,paragraph_anchor,members(tuple).
- MovePair: name,source(MoveRange),destination(MoveRange).
- MoveIssue: code,anchor.
- MoveCatalog: source_sha256,profile,status,main_part,pairs(tuple),issues(tuple),
  catalog_sha256. Profile `docx-moves/main-inline-catalog-v1`.

Names/IDs/anchors/collections/main_part repr-hidden. No XML text/author/date payload.
Canonical digest: dataclasses.asdict, remove catalog_sha256, JSON sort_keys,
ensure_ascii=False,separators=(',',':'),allow_nan=False, UTF8 SHA256. Deterministic
pair order by earliest range start SourceAnchor.path among its two ranges.
No map/deserialize/trusted-DTO API: future reader builds catalog from pinned bytes.

Status absent: no relevant move markup in main part. indexed: supported structural
pairs recorded. blocked: relevant unsupported/malformed structure, pairs=(), one
first deterministic issue. No complete flag. None of these statuses proves whole
package coverage, visibility, valid member run contents or ready ML input. Unrelated
unsupported structures can coexist with absent/indexed, and still block their reader.

## Структурный профиль

Support strict/transitional Word namespace, root document/body. Scan ALL main nodes,
including property history, excluded/unknown branches; relevant moved markup cannot
hide in an ignored subtree. Mixed Word namespace for move tags is blocked. Relevant
six tags: moveFrom,moveTo,moveFromRangeStart/End,moveToRangeStart/End. Other parts
are not cataloged, and absent is explicitly main-only.

Supported markers/wrappers must be direct children of an ordinary p directly in
main body. A range's start/end must be in the same p. Source and destination ranges
may belong to different p and appear in either order. Moved paragraph marks in
pPr/rPr, ranges across p, table/SDT/customXml/math/history/nested contexts blocked.
Future broader profiles implement them; no automatic conversion to insertion/deletion.

Range leaves: no child/non-whitespace text/tail, closed attributes. Start: id,name
required, author/date optional metadata. End: id only. Wrapper: id required,
author/date optional; element text/tails whitespace, children not interpreted as
visible text. Unsupported colFirst/colLast/displacedByCustomXml/dateUtc attributes
block. Attribute lengths counted by preflight. name nonempty<=255 Unicode codepoints,
no Cc controls, exact matching with no strip/case/Unicode normalization.

IDs `[+-]?[0-9]{1,20}` → int normalization, including +00/-0 aliases. This is a
technical bound compatible with existing revision grammar, not a claimed XSD limit.
Range IDs unique within each kind in this main part; from/to may share numeric ID.
Wrapper IDs are independent from range IDs; no group pairing/text equality by them.
Every wrapper must belong to exactly one same-kind range. Nested/crossing ranges,
nested wrappers, wrong kind, orphan ends/content and missing ends are blocked.
Each range has at least one matching wrapper in this profile. Ordinary runs between
endpoints do NOT become moved members; the range container is not moved text itself.
Exactly one source and one destination range per exact name; duplicate same-kind
name or unmatched group blocked. No source/destination text equality requirement.

Fixed issue codes: unsupported_move_context,invalid_move_markup,duplicate_range_id,
duplicate_move_name,nested_or_crossed_range,unmatched_range,unmatched_move_content,
empty_move_range,unmatched_move. Anchor points to relevant original XML node;
when final matching fails, choose earliest unmatched range start.

## Bounds

MoveLimits defaults: max_xml_nodes100000,max_xml_depth128,max_xml_characters8388608,
max_ranges8192,max_members10000. Exact ints1..default only, bool/foreign/mutated limits
rejected. Preflight count main XML nodes/depth/characters (text+attribute values+
tails, including excluded content) BEFORE semantic DOM allocation; max_ranges counts
start markers, max_members counts moveFrom/moveTo including unsupported contexts.
Limits apply even if semantic catalog would otherwise be blocked/absent. No truncation.
Already bounded DOM can be indexed with linear scans/dictionaries; no quadratic
pair-by-text search. SourceAnchor uses original zero-based element child indices,
source SHA and actual main part. Source bytes are never rewritten.

## Acceptance

Freeze/red, strict/transitional UTF8/UTF16/nonstandard main path, names Unicode,
destination before source, source/destination in different p, same range numeric IDs
across kinds, different wrapper IDs/texts, multiple members and ordinary run inside
container, deterministic manifest and independent XML resolution of every anchor.
Malformed/nested/crossed/duplicate/orphan/empty/context/moved-mark cases, lexical ID
aliases, unsupported attrs, unknown branches and Word namespace mismatch. Bounds on
excluded nodes/text/attributes before DOM; DTD and fake EOCD ZIP corpus inherited.
Inert imports/read, frozen DTOs, content-safe repr, source mismatch/invalid input.
Existing visible reader still blocks moves (no accidental admission).

New test setup corrections may be made with written cause and unchanged semantic
assertions; old tests immutable. Review additions before full gate. Required
`bash scripts/check.sh`, previous704 hashes unchanged, readonly main V8 snapshot,
result/guide/local commit, then next independent cycle under current user command.
Native Word/reference paragraph joins and integration into new snapshot profile
remain separate; completion here is only structural catalog readiness.
