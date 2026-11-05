# D03-17A2b3a3 — source-bound catalog of neutral table styles

4 ноября 2026. F05/F06/F11 текущего scope: следующий bounded pure DOCX цикл после
b3a2. Каталог доказывает, что выбранный table style, все его basedOn ancestors и
все conditional regions содержат только известные свойства оформления. Никакого
полного style renderer, final text, Word parity, ML/application admission. Стили,
меняющие видимость/границы/сетку, остаются в прежнем полном scope для следующих
циклов, не пропускаются как безвредные. Старые styles/readers/algebra неизменны.

Allowed новые `src/ara/docx_analysis/table_styles/`,
`tests/acceptance/test_docx_table_styles.py`,
`tests/docx_documents/test_table_styles_edges.py`, этот contract/result/guide/queue.
Не менять старый source/test, public DTO/profile, зависимости, API/ML/DDL, runner,
tasks/progress. Main V8/архив/чужие изменения untouched. Synthetic fixtures only.

## API и доказательство

`ara.docx_analysis.table_styles.read_table_style_catalog(data, *, source_sha256,
limits=None)`. Exact bytes, lowercase SHA256, archive size before hashing,
open_docx/DTD/ZIP guards. TableStyleLimits exact type/ints/revalidation, defaults:
max_xml_nodes100000, max_xml_depth128, max_xml_characters8388608, max_styles4096,
max_regions16384, max_chain_depth128, max_chain_links65536, max_issues10000,
max_manifest_bytes33554432. Все положительные, можно только уменьшать. Исчезнувшее
поле, bool/subclass/mutated limits invalid_input. TableStyleError codes:
invalid_input, source_mismatch, table_style_limit_exceeded; fixed safe messages.
DocxError для broken/oversize package не становится absent.

Ровно один StyleContext из тех же bytes определяет package/styles relationship,
identities/default ambiguity и его SHA входит в proof. Перед ЛЮБЫМ styles semantic
DOM при единственном internal styles part preflight считает ВСЕ branches: nodes,
depth, attribute values/text/tails/namespace URI, обе Word namespaces style/region
counts (включая opaque/history/unknown). Source package validation может работать
до preflight без сохранения style DOM. Ambiguous relationship → global blocked,
без попытки читать внешние/произвольные источники. После context читается тот же
styles XML для собственного closed proof; fresh source only, public factory не
принимает caller catalog/DTO. No filesystem/env/network/SQL/Word/application I/O.

Frozen slots records:
- TableStyleRegion(kind, anchor), source order;
- TableStyleIssue(code, anchor|None, style_id|None);
- TableStyleDefinition(style_id, anchor, based_on|None, is_default, status,
  regions, metadata, chain, issues). status neutral/blocked. metadata — anchors
  известных formatting containers/leaves и UI metadata, без значений свойств.
  chain у neutral: self→parent→root anchors; у blocked пустая. Syntax-invalid own
  definition: based_on None, regions/metadata empty, one fixed issue at style.
- TableStyleCatalog(source_sha256, profile, status, styles_part|None,
  style_context_sha256, default_table_style|None, styles, issues, catalog_sha256).
  profile `docx-table-styles/neutral-current-v1`; status ready/absent/blocked.
  absent = no table definitions (styles part может существовать). ready допускает
  отдельные blocked definitions; unused bad style не отравляет независимый neutral.
  Global StyleContext blocked → no definitions/default, one style_context_blocked
  issue, source/styles/context identity preserved. Catalog issues только global;
  definition issues внутри records. default ID сохраняется даже если style blocked.

Никакого text/raw XML/author values в DTO, IDs/anchors/collections/part names скрыты
в repr. Deterministic lexicographic style-ID order. Hash exact sorted compact UTF8
JSON dataclasses, excluding catalog_sha256 only; streaming bytes bounded before
final result (не строить unbounded asdict tree). Immutable detached proof, не
capability доверять caller-modified object: будущий reader строит его сам.

## Closed grammar и ancestry

Проверяются ВСЕ conditional branches, даже не активируемые tblLook/cnfStyle: если
каждая нейтральна, выбор региона не меняет текст. Нет угадывания регионального
каскада. `tblStylePr` attrs only required type, unique kinds из13:
wholeTable, firstRow, lastRow, firstCol, lastCol, band1Vert, band2Vert, band1Horz,
band2Horz, neCell, nwCell, seCell, swCell. Children rPr,pPr,tblPr,trPr,tcPr unique.
Top table style those5 unique, tblStylePr repeated unique kinds, basedOn unique;
UI/name/aliases/next/link/uiPriority/rsid + existing UI_BOOL metadata grammar.
Only basedOn defines dependency; link/next не применяют другой style.

rPr: existing visibility FORMATTING only (b,bCs,i,iCs,u,strike,dstrike,color,
highlight,sz,szCs,vertAlign,lang,rFonts). pPr: existing PARAGRAPH only
(spacing,ind,jc,outlineLvl,keepNext,keepLines,pageBreakBefore).
tblPr leaves tblW,jc,tblInd,tblLayout,tblCellSpacing,tblLook,shd,
tblStyleRowBandSize,tblStyleColBandSize; boolean bidiVisual; tblBorders,tblCellMar.
trPr leaves trHeight,jc; booleans cantSplit,tblHeader.
tcPr leaves tcW,shd,vAlign,textDirection; booleans noWrap,tcFitText,hideMark;
tcBorders,tcMar. Border edges top/left/bottom/right/start/end/insideH/insideV/
tl2br/tr2bl, margin first6. Containers attrsnone/whitespace, no duplicatechildren.
Known formatting leaves no children/nonwhitespace text, Word-namespace attrs only;
boolean leaf optional val strict existing on/off grammar. No full XSD/layout claim.

Unknown property, history, rStyle/pStyle/numPr/paragraph-mark rPr, any vanish/
specVanish/webHidden (even false), geometry merge/span/gridBeforeAfter, row hidden
(even false), floating placement, mixed namespaces or malformed leaf→definition
blocked unsupported_table_style. Root styles envelope/identity/default ambiguity
handled by StyleContext and gives global blocked. UI hidden is allowed metadata,
not run vanish. No exception for style-row hidden in this conservative profile.

Each neutral definition requires neutral same-kind basedOn chain. Missing parent→
missing_base_style, other kind→base_style_type_mismatch, cycle/dependent-on-cycle→
style_cycle, other blocked parent→unresolved_base_style. Child cannot override away
non-neutral ancestor. Iterative bounded graph, no recursion through4096 styles;
chain length includes self. Budget total emitted chain links before allocating
chain tuple; issue cap across inherited context issues and own issues. Source-order
region/metadata anchors point to original styles XML; no copied/rebased nodes.

Primary research4Nov: [conditional regions](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.tablestyleproperties?view=openxml-3.0.1),
[tblLook](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.tablelook?view=openxml-3.0.1),
[Word style toggles](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oi29500/f7130225-2368-48f3-acae-a9d278d0fb25),
[style-row hidden exception](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oi29500/be9bdcbb-f5ff-45f9-9120-44d8a545773b).
Existing paragraph/character algebra не менять. Catalog не устанавливает inactive
T=defaults для application: source-backed integration и native parity отдельно.

## Acceptance / gate

Freeze→red namespace missing; literal neutral chain, conditional13regions/provenance,
strict UTF16/custom part, all grammar guards/defaults/opaque unusedstyles, missing/
wrongkind/cycle/blocked parent with attempted false override, global ambiguity,
sourcehash/digest determinism/immutability/repr, limits every unread branch before
semantic DOM (including namespace), exact chain/manifest boundaries, longgraph,
no repeated StyleContext per factory, freshprocess noI/O, originalbytes unchanged.
All old tests unchanged. New setup corrections only with written cause and no
assertion weakening; review additions before full gate. Required scripts/check.sh,
734 previous hashes unchanged, readonly main V8 snapshot, result/guide/local commit.
Then next bounded integration cycle under current autonomous user instruction.
