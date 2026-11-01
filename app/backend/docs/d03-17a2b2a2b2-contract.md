# D03-17A2b2a2b2 — visible-main snapshot и обратные координаты

1 ноября 2026. Архитектурный проход после `e08bb8e`, по [visibility design](d03-17a2b2a2-design.md) и действующему [объёму продукта](current-product-scope.md). Контракт подготовлен для реализации на **Sol 6.1 High**. Приёмка ещё не написана/не заморожена; следующий цикл того же ID начинает с новых acceptance tests и freeze, затем red → source → targeted/full → baseline → result → локальный commit. Ещё один архитектурный проход перед этим кодом не требуется.

Результат реализации: opt-in чтение видимого текста обычных абзацев, с provenance стилей/прямых свойств и точным отображением замечаний на исходные atoms. Это законченный reader/mapper, а не ещё один самостоятельный algebra helper. HTTP/SQL/ML/editor integration остаётся D03-17B…E. Продуктовая policy прежняя: final revisions, comments исключены, hidden text исключён, исходный ZIP неизменен.

## Границы и совместимость

Allowed source: только новый пакет `src/ara/docx_analysis/visible_main/` (публичный `__init__.py`, внутренние модули по ответственности). Новая приёмка `tests/acceptance/test_docx_visible_main.py`; дополнительные собственные проверки `tests/docx_documents/test_visible_main*.py`. Документы: этот контракт до freeze, отдельный `d03-17a2b2a2b2-result.md`, ссылки/статусы в development-queue и visibility design. Результат текущего проектирования — отдельный `d03-17a2b2a2b2-design-result.md`.

Существующие source/tests/exports/package/schema/API/ML/editor/dependencies/scripts/runner/tasks/progress/AGENTS не изменяются. Main ara_dev остаётся V8. Frozen contracts/tests не переписывать ради нового профиля. Можно импортировать неизменные package primitives, SourceAnchor, StyleContext/VisibilityProperties, read_style_context и внутренний pure `visibility.rules._effective`: это явно разрешённая внутренняя зависимость, проверяемая compatibility tests. Нельзя копировать или менять toggle algebra. Старые FinalSnapshot/map_final_span не принимают новые DTO; новый API не принимает старые снимки.

## API и типы

```python
from ara.docx_analysis.visible_main import (
    build_visible_snapshot, map_visible_spans, map_visible_span,
    VisibleLimits, VisibleViewError, VisibleSpanRequest,
    VisibleSnapshot, VisibleParagraphContext, VisibleRunContext,
    VisibleFragment, VisiblePiece, VisibleCoverage,
    VisibleMappedSpan, VisibleSourceSlice,
)

build_visible_snapshot(
    data: bytes, *, document_id: UUID, storage_revision: int,
    source_sha256: str, limits: VisibleLimits | None = None,
) -> VisibleSnapshot

map_visible_spans(
    data: bytes, snapshot: VisibleSnapshot, *,
    requests: tuple[VisibleSpanRequest, ...],
    limits: VisibleLimits | None = None,
) -> tuple[VisibleMappedSpan, ...]

map_visible_span(
    data: bytes, snapshot: VisibleSnapshot, *, fragment_id: str,
    start: int, end: int, quote: str,
    limits: VisibleLimits | None = None,
) -> VisibleMappedSpan
```

Одиночный mapper — wrapper над batch из одного запроса. Source bytes обязательны: shape/hash проверки снимка не доказывают истинность source addresses. Публичного mapper только по DTO, произвольного внешнего StyleContext или query factory нет. Будущий сервис передаёт сохранённый immutable source и проверяет document/revision/SHA по своей записи; mapper не доказывает подлинность клиентского документа, если клиенту позволили подменить и source, и identity.

Все новые DTO frozen/slotted; коллекции exact tuple; реквизиты source, XML anchors, style IDs, quote/text и вложенные records/коллекции имеют repr=False. Нет XML/ZIP/ET/исходных bytes в результате, author/date/comment body/URL/имена стилей не извлекаются. UUID — exact UUID с exact int .int в 0..2**128-1 (повторная проверка против повреждённого объекта); revision — exact int 1..2**63-1, bool запрещён; SHA — exact lowercase 64 hex. Строки не strip/normalize/casefold. SourceAnchor прежний: SHA всего ZIP, настоящее part_name, element-only tuple индексов от корня; root имеет path=().

Точные поля (в указанном порядке; поля без `=...` обязательны):

| DTO | Поля |
|---|---|
| VisibleParagraphContext | `paragraph_anchor:SourceAnchor`, `style_reference_anchor:SourceAnchor\|None`, `requested_style_id:str\|None`, `resolved_style_id:str\|None`, `mark_properties:VisibilityProperties` |
| VisibleRunContext | `run_anchor:SourceAnchor`, `paragraph_anchor:SourceAnchor`, `style_reference_anchor:SourceAnchor\|None`, `requested_style_id:str\|None`, `resolved_style_id:str\|None`, `direct_properties:VisibilityProperties`, `visibility:RunVisibility` |
| VisiblePiece | `kind:str`, `anchor:SourceAnchor`, `run_anchor:SourceAnchor`, `paragraph_anchor:SourceAnchor`, `start:int`, `end:int`, `source_start:int`, `source_end:int` |
| VisibleFragment | `fragment_id:str`, `story_anchor:SourceAnchor`, `flow_anchor:SourceAnchor`, `paragraph_anchor:SourceAnchor`, `text:str`, `pieces:tuple[VisiblePiece,...]`, `analysis_start:int`, `analysis_end:int` |
| VisibleCoverage | `status:str`, `code:str`, `part_name:str`, `anchor:SourceAnchor\|None`, `fragment_id:str\|None` |
| VisibleSnapshot | `document_id:UUID`, `storage_revision:int`, `source_sha256:str`, `profile:str`, `policy_version:str`, `main_part:str`, `style_context:StyleContext`, `paragraphs:tuple[VisibleParagraphContext,...]`, `runs:tuple[VisibleRunContext,...]`, `fragments:tuple[VisibleFragment,...]`, `analysis_text:str`, `coverage:tuple[VisibleCoverage,...]`, `complete:bool`, `text_sha256:str`, `snapshot_sha256:str` |
| VisibleSpanRequest | `fragment_id:str`, `start:int`, `end:int`, `quote:str` |
| VisibleSourceSlice | `kind:str`, `anchor:SourceAnchor`, `run_anchor:SourceAnchor`, `paragraph_anchor:SourceAnchor`, `start:int`, `end:int` |
| VisibleMappedSpan | `fragment_id:str`, `start:int`, `end:int`, `slices:tuple[VisibleSourceSlice,...]` |

VisibilityProperties/VisibilityValue/StyleContext и RunVisibility — существующие immutable DTO, не их копии. Прямые properties содержат значение и anchor **реального текущего** элемента; absent — (None,None), false — (False,anchor). Mark properties не подмешиваются в run properties. Paragraph resolved ID — явный либо default paragraph; run resolved ID — только explicit character ID либо None. Reference anchor указывает на pStyle/rStyle, не на definition; inherited witnesses находятся один раз в style_context. Paragraph/run tuples охватывают все retained p/r, включая пустые/hidden, в XML document order. Blocked main не выдаёт частичные context tuples.

`profile='docx-analysis/final-visible-main-v1'`, `policy_version='docx-analysis-policy/final-visible-no-comments-v2'`. Complete означает отсутствие blocker в **этом профиле**, а не native Word parity, готовность ML или всего DOCX. Нет fallback на старый reader с более широкой выдачей текста.

## Разбор и ресурсы

VisibleLimits поля/default maxima:

| Поле | Максимум включительно |
|---|---:|
| max_xml_nodes | 100000 |
| max_xml_depth | 128 |
| max_xml_characters | 8388608 |
| max_paragraphs | 10000 |
| max_runs | 10000 |
| max_pieces | 100000 |
| max_text_characters | 1000000 |
| max_coverage_items | 100000 |
| max_span_requests | 10000 |
| max_requested_characters | 1000000 |
| max_mapped_slices | 100000 |
| max_manifest_bytes | 33554432 |
| styles | StyleContextLimits(), default_factory |

Exact int >=1, только уменьшение, exact nested StyleContextLimits, повторная проверка в API после constructor. max_text_characters ограничивает итог с synthetic separators; max_requested_characters — сумму len(quote) во всём batch, включая повторные запросы. max_mapped_slices — суммарную выдачу, тоже с повторами. Нет truncation/частично успешного batch.

max_manifest_bytes — размер canonical UTF-8 snapshot без snapshot_sha256, с повторным учётом каждого вхождения strings/anchors. Проверяется streaming canonical traversal после bounded type validation и до создания полной JSON-строки/копии asdict; builder также обязан соблюсти этот предел. Это закрывает раздувание повторяющихся part names/paths в foreign DTO и в допустимом входном пакете. Размер ровно MAX допустим, MAX+1 — view_limit_exceeded; malformed schema по-прежнему invalid_snapshot. Индексы anchor.path — exact int 0..max_xml_nodes-1, длина <=max_xml_depth; нет огромных int или произвольной рекурсии. Порядок ключей и JSON escaping остаются canonical, chunk boundaries на SHA не влияют.

1. Проверить inputs/limits, archive byte cap до SHA, затем exact source SHA и open_docx. Использовать прежние ZIP directory/parsing_end/chunks; не выбирать другой EOCD из комментария архива. Package limits/DTD/entity/external-link запреты не ослаблять.
2. До построения новых main/styles ET деревьев — streaming preflight с count-only XML target для main и всех частей с точным styles MIME, каждая часть один раз, отсортированные имена. Общие nodes и characters, depth отдельно в каждой части. Счётчики включают excluded/history/opaque ветки. Characters — сумма Unicode code points из data callbacks и значений атрибутов, включая whitespace/tails; names не включаются, их размер ограничен package bytes. Проверка до сохранения текста/создания ET nodes; parser может держать один ограниченный package chunk. Invalid XML→DocxError.invalid_package. Двукратный проход XML (preflight, затем DOM) допустим; удвоение resolved catalog недопустимо.
3. Прочитать read_style_context ровно один раз на build с limits.styles. Дополнительные открытия/валидации ZIP внутри существующего catalog допустимы, постоянное число проходов; не monkeypatch каталог и не удерживать его parser. Подготовить один ID index. Global blocked catalog блокирует main даже без runs; ambiguous part не превращается в absent. Main DOM также строится bounded parser; общий preflight не отменяет локальные limits.
4. Распознать main grammar, selectors и прямые values из этих же bytes. Считать все main w:p/w:r по дереву в max_paragraphs/max_runs до исключений. max_pieces ограничивает число main t/tab/br/cr candidates до удаления/hidden исключения, а затем output pieces. Builder и mapper не получают selector/provenance от caller. Только после распознавания whole run вызвать неизменный _effective с доверенным catalog/index/query. Один вызов на retained run, без нового catalog на каждый run.
5. Проверить все границы и selected style contexts, затем собрать output. При любом semantic main blocker полностью убрать paragraphs/runs/fragments/text и события частичного main traversal. Package ledger и catalog остаются; main получает один deterministic blocked event. Техническое превышение limit — исключение, не coverage с partial success.

Память bounded входными package/XML и output limits, без квадратичного копирования basedOn chains в каждом контексте. Mapping индексирует fragments и piece intervals один раз на batch; binary search + пересекающиеся pieces, а не scan всех pieces для каждого запроса. Parsing/resolve выполняются один раз на batch. Import/API без application I/O, секретов, env, сети, процессов, БД и модели.

## Узкая main grammar

Это новая самостоятельная grammar, а не включение всех разрешений старого reader через наследование. Strict/Transitional namespaces, UTF-8/UTF-16, переименованные parts поддерживаются package primitives. Foreign/MC attributes/elements в retained main запрещены, кроме перечисленного r:id/xml:space. Namespace declarations не являются атрибутами ET. Отсутствующий/неверный current value нельзя исправлять historical value.

Общее правило: container.text и child.tail — только whitespace, кроме leaf w:t. Properties встречаются не более одного раза по имени; pPr/rPr — первые и единственные children своего владельца. Все retained leaf nodes без children; все leaf кроме t без non-whitespace text. Неизвестные атрибуты блокируют. Исключения для opaque deleted/history interiors описаны ниже.

| Контекст | Разрешено |
|---|---|
| document | attrs отсутствуют; ровно один body, других children нет |
| body | attrs отсутствуют; прямые p и optional единственный последний sectPr |
| p | attrs только w:rsidR,rsidRDefault,rsidP,rsidRPr,rsidDel (8 hex); optional pPr, затем inline |
| inline | r, hyperlink (не вложенный, в том числе через ins), ins, del, bookmarkStart/End, commentRangeStart/End |
| r | attrs только w:rsidR,rsidRPr,rsidDel (8 hex); optional rPr, затем t/tab/br/cr/commentReference |
| t | только optional xml:space=default/preserve; текст читается буквально, без trim/normalization |
| tab/cr | attrs отсутствуют; output TAB/LF |
| br | optional w:type=absent/textWrapping/page/column, w:clear=none/left/right/all; output LF, source kind=break |
| hyperlink | attrs w:anchor/docLocation/tooltip/tgtFrame (строки), w:history (on/off), r:id в соответствующем relationship namespace; r:id при наличии непустой и разрешён в source.main_part relationship типа hyperlink. Target не читается. Без r:id нужен непустой w:anchor. Только retained inline contents |
| pPr | attrs отсутствуют; pStyle, spacing/ind/jc/outlineLvl/keepNext/keepLines/pageBreakBefore, mark rPr, pPrChange |
| run rPr | attrs отсутствуют; rStyle, vanish/specVanish/webHidden, formatting leaves ниже, rPrChange |
| mark rPr | attrs отсутствуют; vanish/specVanish/webHidden, formatting leaves, rPrChange, optional один ins. Любой rStyle/del/move или несколько revision markers блокируют boundary |
| formatting leaf | b/bCs/i/iCs/u/strike/dstrike/color/highlight/sz/szCs/vertAlign/lang/rFonts; только атрибуты текущего Word namespace. Их визуальные значения не вычисляются и не используются для скрытия текста |
| paragraph formatting leaf | spacing/ind/jc/outlineLvl/keepNext/keepLines/pageBreakBefore; только атрибуты текущего Word namespace, без children/text |
| pStyle/rStyle | ровно w:val, exact string 1..253 code points, без casefold/strip |
| vanish/specVanish/webHidden | только optional w:val, absent/true/1/on→True, false/0/off→False; остальные варианты unsupported |
| sectPr | attrs отсутствуют; только pgSz/pgMar/cols/docGrid, каждый максимум один, leaf с Word namespace attrs. Только технический tail всей body; references/изменения/дополнительные секции блокируют |

Revision wrapper ins/del: required w:id `[+-]?[0-9]{1,20}`, optional w:author/date, других attrs нет; значения author/date не сохранять. Inline ins traversed, inline del исключается целиком (включая nested ins и неизвестный payload), tail всё равно проверяется родителем. Нельзя переносить правило inline del на mark. Mark ins — leaf, boundary сохраняется.

Property history: pPrChange только внутри current pPr, rPrChange только внутри current run/mark rPr; те же revision attrs, whitespace wrapper, ровно один соответствующий old pPr/rPr без требования распознать его interiors. Не обходить old contents как current, но считать входные XML limits. Истории styles покрывает уже существующий catalog.

Bookmarks: required w:id decimal как revision; bookmarkStart дополнительно required непустое w:name, bookmarkEnd без name; другие attrs blocked. Comment markers/reference: только required w:id того же формата. Comments исключены из анализа; text внутри такого leaf недопустим. В этом профиле нет проверки редакторской семантики paired bookmarks/comments: они не меняют retained text. Связь comments parts с thread extension не угадывается, unknown parts остаются blocked.

Active numPr (даже numId=0), таблицы, paragraph sectPr, moves/ranges, fields/instrText, SDT/customXml/AlternateContent, drawings/textboxes/math/sym, background и другие активные структуры — unsupported main. Hidden run с field/drawing/unknown child также блокирует весь main: visibility не разрешает пропустить неизвестный смысл. Тот же payload внутри корректной inline del/history исключён по final policy. Простые section size/margins не равны поддержке sections/stories. Перечень — reader capability, не новое сокращение продуктового scope.

## Отбор стилей и границ

Для runs применяются b1 paragraph/character selection и algebra без изменений; errors b1 не перекрываются direct false. Selected paragraph style проверяется также у пустого p. Unused blocked/opaque styles не применяются только если whole main grammar и все contexts распознаны; наличие одного неизвестного flow не доказывает их неиспользование.

**Усиленный guard implicit character:** default character отсутствует либо resolved и все три resolved visibility values равны None. Любое заданное значение, включая false, или unresolved default блокирует этот профиль с `implicit_character_style`. Guard действует на весь распознанный main, поскольку у paragraph mark здесь нет explicit rStyle. Это сознательно более узкий допуск, чем standalone b1; b1 convention/tests не меняются. В частности, docDefaults=true + implicit default character=false не объявляется подтверждённой Word семантикой.

**Conservative boundary guard:** нет deleted/moved mark и explicit mark rStyle; для каждого retained p значения vanish и specVanish в docDefaults, resolved paragraph style и direct mark properties должны быть только None/False. Любое True на любом из этих уровней → `unresolved_paragraph_boundary`, даже если дальнейший override мог бы его отменить. WebHidden не участвует в этом guard. Mark ins остаётся границей. Empty/полностью hidden p проходят тот же guard. Не вычислять mark посредством ordinary-run XOR и не добавлять joins в новый DTO.

Из этого следует намеренное ограничение первого main profile: direct/explicit-character hidden runs поддержаны; hidden через paragraph style/defaults может блокировать весь main из-за неразрешённой границы. Все восемь D/P/C сочетаний остаются проверены в algebra b1, но не все означают допускаемый whole document в b2. Boundary resolver b2a2c расширит capability **отдельным profile/контрактом** после native evidence; сейчас не угадывать joins или отмену hidden mark.

Основания: [rStyle](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.runstyle?view=openxml-3.0.1) описывает explicit character-style selection; [paragraph-mark properties](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.paragraphmarkrunproperties?view=openxml-3.0.1) относятся к самому знаку; [specVanish](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.specvanish?view=openxml-3.0.1) может подавить отображаемую границу. Guards выше — наш временный ограниченный допуск, не утверждение, что Word запрещает эти документы. Native сравнение здесь не выполнено.

Порядок semantic blocker: global catalog → whole-main grammar (первый unsupported в XML traversal) → implicit default guard → для каждого p по порядку paragraph selection, boundary guard, затем run selection/rules по порядку. На failure используется код причины и anchor body; ни цитаты, ни IDs, ни свойства автора в error. Неподдержанный mark syntax/numPr получает `unsupported_main_flow`; guard разрешённой структуры с True — `unresolved_paragraph_boundary`.

## Output, coverage и manifest

На успешном main каждый p независим. Видимые непустые atoms образуют pieces (kind=text/tab/break), hidden runs не дают pieces. Весь atom сохраняется с source_start=0 и source_end=len(atom_text); empty t не даёт piece. Внутри p текст конкатенируется без вставок взамен hidden/deleted/comments. `ab` + hidden `secret` + `cd` → `abcd`, две отдельные source pieces. Whitespace сохраняется буквально, в том числе вокруг hidden gap.

Один fragment на p с хотя бы одним non-whitespace символом. Полностью пустые/whitespace-only p не дают fragment, получают empty coverage; hidden runs получают exclusion независимо от этого. Между выданными fragments — ровно два LF в analysis_text; эти separators не имеют source slice. Hidden/пустой отдельный p не соединяет соседние p в один fragment. Fragment offsets — Python Unicode code points [start,end), никакого UTF-16/grapheme пересчёта. Каждый fragment ссылается на один p, story=flow=body.

Coverage детерминированна; один package record на каждую entry, anchor=None/fid=None. Main part→metadata/main_part; package metadata и прежние core/custom/extended properties MIME→metadata/package_metadata; comments MIME→excluded/comments_policy. Единственная доказанная styles part→metadata/style_context_accounted **только если catalog ready и весь main успешно распознан**. Если styles part не accounted — blocked/style_usage_unproven. Все остальные parts, включая settings/numbering/theme/fonts/media/прочие stories, →blocked/unread_part. Не снимать их blockers автоматически по отсутствию прямой text-ссылки. При orphan/ambiguous styles все соответствующие MIME parts blocked. Absent catalog не создаёт выдуманный part.

Успешный main: metadata/main_flow_read на body; included/paragraph с fid для каждого выданного p либо empty/empty_paragraph без fid. Дополнительные события: metadata/inserted_content (ins), excluded/deleted_content (del), metadata/inserted_boundary (mark ins), excluded/historical_properties (current history wrapper), metadata/supported_properties (каждый current pPr/run rPr/mark rPr), metadata/bookmark, excluded/comments_policy (markers/reference), excluded/hidden_run (каждый retained hidden r). Для дополнительных событий fid=None. Descendants excluded del/history не получают отдельных событий. Hidden run проверен целиком, поэтому может иметь собственные history/comment events; они не дают текстовых slices.

Main failure: ровно один blocked event на body без fid, code из `unsupported_main_flow`, `style_context_blocked`, `implicit_character_style`, `unresolved_paragraph_boundary`, `missing_paragraph_style`, `paragraph_style_type_mismatch`, `unresolved_paragraph_style`, `missing_character_style`, `character_style_type_mismatch`, `unresolved_character_style`. Никаких main_flow_read/paragraph/hidden events или partial contexts/text при failure. Невалидный пакет, где невозможно найти body, обрабатывается package/parse error, а не выдуманным body anchor.

Все records сортируются по `(part_name, 0 if anchor is None else 1, () if anchor is None else anchor.path, code, fragment_id or '')`, duplicates запрещены. Complete exact bool равен отсутствию blocked records. Auxiliary blocker может сохранить корректные main fragments/contexts; main blocker обнуляет их. complete=True + пустой output допустим как учтённый документ, но будущий service должен вернуть no checkable text вместо запуска ML.

Canonical JSON: все поля dataclass по schema, SourceAnchor как object, tuples как arrays, UUID строкой, storage_revision десятичной строкой, None как null; UTF-8, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False. `text_sha256=SHA256(analysis_text UTF-8)`; `snapshot_sha256=SHA256(canonical(snapshot без snapshot_sha256))`, включая весь catalog со своим digest, contexts и coverage. Existing catalog digest остаётся прежним.

Fragment ID: `vf-` + SHA256 canonical object с ключами `domain='docx-visible-fragment/1'`, profile, policy_version, source_sha256, story_anchor, flow_anchor, paragraph_anchor. Source SHA связывает context/styles и текст даже если main XML неизменен. Document ID/revision остаются в snapshot identity, но не входят в fragment ID; никакого переноса результатов между revisions только по совпадению ID. Любая смена source/profile/policy меняет identity и требует новой проверки. Нет исторических joins/boundaries в manifest v1.

## Проверка mapping по исходнику

Batch mapper в следующем порядке:

1. Проверить limits и exact requests tuple/count, exact request DTO/строки/int (bool исключён), positive span, размеры quote и aggregate budgets. Bad shape→invalid_input, nonpositive/out-of-range/quote mismatch→invalid_span (range/quote относительно fragment проверяются позже). Empty batch всё равно проверяет source/snapshot. Не сериализовать неизвестный DTO через asdict, не вызывать его repr/equality.
2. Проверить snapshot exact schema recursively до canonical JSON: только ожидаемые exact DTO/tuple/primitives, bounds всех collections/strings/anchor paths, depth, enum fields, hash shape/identity; никаких arbitrary iterables/objects/subclasses. Общие размеры bounded теми же output limits, catalog — StyleContextLimits плюс XML characters; суммарные строки metadata/anchors не раздуваются из-за многократного source path (max 65535 на part name, max128 path, max253 на style ID). Неверный snapshot→invalid_snapshot. Проверка выполняется без пользовательских hooks и без quadratic concatenation. Контроль порядка/связей может делегироваться последующему authoritative rebuild, но type/size checks — до него и сериализации.
3. Построить expected через build_visible_snapshot **ровно один раз** из data и identity snapshot с теми же limits. SHA проверяется самим builder; source_mismatch/package/limit errors сохраняют codes. На immutable exact snapshots после shape checks сравнить все поля с expected, включая catalog/coverage/contexts/pieces/text/hashes. Любое расхождение→invalid_snapshot, даже при пересчитанном атакующим manifest. Контрольные суммы не заменяют это сравнение. Если caller снизил limits ниже фактического source/output, вернуть limit error, не менять snapshot.
4. Создать indexes ожидаемого снимка один раз. Для каждого request найти exact fragment_id, проверить 0<=start<end<=len(text) и text[start:end]==quote. Нет fuzzy match/поиска похожего текста/первого совпадения. Unknown ID→unknown_fragment. Все запросы проверяются атомарно; ни одного partial mapped result при ошибке.
5. Отдать пересечения с pieces в source order. Slice start/end — смещения внутри original atom, `piece.source_start + intersect_offset`; tab/break имеют только [0,1). Не объединять соседние atoms/runs в enveloping range, даже если XML соседний. Никогда не возвращать hidden/deleted/history/comment/style anchors как текст. Повторные запросы сохраняют порядок и каждый получают собственный результат; total slice budget проверяется до append.

Пример adversarial gate: сдвиг visible piece на hidden run, удаление hidden coverage, подмена paragraph style/direct property anchor, присвоение styles witness из другого source, и пересчёт **всех** доступных digests не должны пройти source-backed rebuild. Подмена файла с сохранённым старым SHA→source_mismatch. Подмена полного source+identity требует проверки trusted saved record у будущего сервиса — это отдельная граница, не решаемая самоподписанным manifest.

VisibleViewError статические code/message: `invalid_input`, `source_mismatch`, `view_limit_exceeded`, `invalid_snapshot`, `unknown_fragment`, `invalid_span`. DocxError/StyleContextError сохраняются без сырых parser exceptions/content; ProjectionError.projection_limit_exceeded, если использован прежний parser, переводится в view_limit_exceeded. Строки сообщений без пользовательских данных. Не оборачивать произвольные programming bugs в success/empty snapshot.

## Независимая приёмка перед source

Новые tests строят только synthetic DOCX. Expected texts/paths/offsets/coverage и canonical digests задаются независимо от production helper; fixture helper не вычисляет ожидаемую видимость через _effective. Freeze отдельным локальным commit, затем доказанный red отсутствующего visible_main, не искусственный fail. Frozen old/new tests после freeze не менять без конкретного основания/разрешения пользователя.

1. Plain/explicit character hidden/direct hidden/override false, exact gaps и Unicode (emoji, combining marks, mixed script), tab/br/cr, multiple runs и identical text с разными anchors. Literal `abSECRETcd`→`abcd`, quote `bc`→последний символ первого visible atom и первый второго, без SECRET.
2. Direct specVanish/webHidden ordinary run не скрывают текст; mark true/default true/paragraph style true не обходят boundary guard. None/False guards, mark ins retained, deleted/moved mark/rStyle и mixed boundaries blocked. All-hidden/empty/whitespace-only p; сохранённые границы независимых fragments.
3. Real XML-derived pStyle/rStyle/direct anchors, default paragraph, nearest basedOn, false inheritance; implicit default any explicit false/true blocked (включая D=true case). Missing/wrong type/cycle/unsupported selected styles blocked даже direct=false; unused bad/opaque styles не влияют на успешно распознанный ordinary flow. No style catalog vs ambiguous catalog отличаются.
4. Final inline ins/del nesting, direct properties vs old history, comments сохраняются в source/не попадают в text. Unsupported retained payload внутри hidden run blocked; тот же payload в excluded deletion/history не интерпретируется. Unknown attributes/duplicate properties/non-whitespace tail, MC/foreign namespace, unsafe hyperlink references, active numPr/table/field/section всегда fail closed.
5. Package ledger для main/styles/metadata/comments/непрочитанных parts; styles accounted только после whole-flow proof. Main failure не отдаёт частичную выдачу; auxiliary failure сохраняет main, complete=false. Source bytes/hash неизменны; renamed Strict/Transitional/UTF-16 packages; style-only change меняет snapshot/fragment identity.
6. Все shape/hash/enum/bool/subclass errors, lower limits и повторная validation изменённых frozen records; max/exact+1 по каждому budget, включая aggregate main+styles, hidden/history, duplicate mapping quotes/slices. Invalid ZIP/DTD/entities/EOCD comments, прежние legacy regression tests неизменны.
7. Rehashed forged piece/coverage/context/whole catalog против original bytes, wrong source, wrong quote/range/ID и request order/duplicates/empty batch. Mixed valid+invalid batch атомарен. Single wrapper равен batch из одного. Batch из множества запросов строит expected/catalog ровно один раз (spy), общий style index и bounded mapping не растут как Q×все pieces.
8. DTO без ET/bytes/secrets/content в repr/errors; fresh process import/API без app/network/files/env/model I/O. Whole source/policy/main identity проверяется и при empty output/empty requests. Targeted catalog/rules/final-view/projection regressions, полный `bash scripts/check.sh`, read-only runtime baseline и локальный commit без push.

Буквальный source fixture для пункта 1: document/body/p без pPr, три r: первый t=`ab`, второй rPr/vanish и t=`SECRET`, третий t=`cd`. Body — первый child document, p — первый child body. Expected quote `bc` на [1,3) даёт text slices: atom path `(0,0,0,0)` [1,2) и `(0,0,2,0)` [0,1). Hidden atom `(0,0,1,1)` не возвращается. Это независимые ожидаемые координаты; тест не получает их из production projection/mapper.

После реализации — b2a2c и остальные readers по очереди; перед каждым новый bounded contract/freeze. Native Word hidden-boundary evidence, settings/numbering/MC/font/theme admission, full DOCX editing/export matrix и реальные ML/platform tests остаются явными последующими работами. Не останавливать независимые задачи из-за отсутствующих весов/фронта, но не выдавать текущий narrow profile за полный импорт/анализ Word.
