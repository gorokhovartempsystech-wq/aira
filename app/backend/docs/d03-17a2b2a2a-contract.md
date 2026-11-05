# D03-17A2b2a2a — каталог текущих свойств видимости стилей

1 ноября 2026. Первый implementation cycle после [D03-17A2b2a2](d03-17a2b2a2-design.md), Sol 6.1 High. F06/F11. Одна задача: прочитать styles part из проверенного DOCX и разрешить текущие свойства внутри basedOn-цепочек. Не извлекать требования и не рассчитывать полную видимость main flow. Код ещё не реализован; приёмку заморозить до source.

## Разрешённые изменения и цикл

Только новый пакет `src/ara/docx_analysis/visibility/`, новая frozen `tests/acceptance/test_docx_visibility_styles.py`, собственные `tests/docx_documents/test_visibility_styles*.py`. Документы: этот контракт до freeze, новый d03-17a2b2a2a-result.md, статусы/ссылки d03-17a2b2a2-design.md и development-queue.md. Existing final_view/A1/A2a/top-level __init__/package/editor/HTTP/ML/БД/dependencies/scripts/old tests/AGENTS/runner/tasks/progress неизменны. Helpers существующего package можно импортировать без правок. Новый API импортируется только через submodule.

Freeze новых acceptance отдельным локальным commit → red → implementation → targeted/full `bash scripts/check.sh` → сравнение runtime baseline → result/local commit. Не менять frozen tests ради green. Main ara_dev остаётся V8, никаких migration/записей; integration tests — штатные disposable DB. Архив/секреты не читать, source packages только синтетические. Внешних вызовов/публикации нет.

## API, безопасность и лимиты

```python
from ara.docx_analysis.visibility import (
    read_style_context, StyleContextLimits, StyleContextError,
    StyleContext, ResolvedStyle, VisibilityProperties, VisibilityValue, StyleIssue,
)

read_style_context(
    data: bytes, *, source_sha256: str,
    limits: StyleContextLimits | None = None,
) -> StyleContext
```

Exact bytes, exact str lowercase64hex SHA, exact limits/None; limits повторно валидируются на входе API, а не только в constructor. Проверить размер архива до hash, затем совпадение SHA. `open_docx(data)` с неизменными default DocxLimits. Caller не передаёт source/inventory/XML/context. API/import инертны: не читают файлы/env/БД, не открывают сеть/процессы, не импортируют ML или HTTP. В памяти используется проверенная ZIP directory через существующие parsing_end/chunks, включая EOCD signature в comment. Ни raw source, ни ET/DocxSource/closures не остаются в DTO.

StyleContextLimits frozen/slotted: exact positive int, bool запрещён; default одновременно maximum, caller может только уменьшать: `max_nodes=100000`, `max_depth=128`, `max_styles=4096`, `max_chain_depth=128`, `max_issues=10000`. nodes/depth считаются по всей styles XML до pruning, включая histories/opaque definitions; root depth1. max_styles — все direct w:style, включая неподдержанные типы. Chain depth — число definitions, включая выбранный стиль; проверять весь basedOn path, даже если свойство найдено ближе. Issues считаются суммарно global + per-style до добавления сверх limit. Никакой тихой обрезки.

StyleContextError имеет только static code/message: `invalid_input`, `source_mismatch`, `style_limit_exceeded`. Неверный вход/limits — invalid_input, несовпадение SHA — source_mismatch; новые budgets — style_limit_exceeded. Existing DocxError invalid/unsupported/package limits сохраняются. Неподдержанная styles grammar — возвращаемый blocked context/record, а не exception с сырой XML diagnostic. Exceptions подавляют parser payload.

## Поиск части и состояния

Relationship type: ровно Transitional либо Strict officeDocument relationship URI + `/styles`, source_part равен настоящему main_part. MIME ровно `application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml`. Имя файла произвольное, lookup по resolved_part, внешние targets никогда не открываются. Дубликаты/несоответствие MIME/несколько candidates/осиротевший styles MIME без main link/внешний link — global blocked `ambiguous_styles_part`; styles_part=None, без чтения кандидата наугад. Ноль candidates и ноль styles links — status `absent`, не ошибка. Package-level invalid relationships могут быть отвергнуты раньше open_docx.

Один корректный target → bounded parse. Root ровно Word `styles`; Transitional и Strict, UTF8/UTF16 обязательны. Namespace определяется root; внутри не смешивать Word namespaces. Anchors используют SHA исходного ZIP, реальное part_name и element-only path (root `()`, comments/PI не добавляют индексы). Учитывать namespace, не один local-name. Неверный root/неизвестный root child/непустой container text или child.tail — global blocked `unsupported_style_structure`. XML/DTD/entities проверяются existing validator до дерева.

## Точные DTO и fingerprint

Все DTO frozen/slotted, collections tuple; типы без произвольных attrs. Значения из документа (style IDs, part names, anchors, basedOn и содержащие их aggregates) repr=False. Static status/code/profile/hash/bool допустимы. Имена стилей, author/date, UI metadata и literal text в DTO не переносить.

| DTO | Поля |
|---|---|
| VisibilityValue | value (`bool\|None`), anchor (`SourceAnchor\|None`) |
| VisibilityProperties | vanish, spec_vanish, web_hidden (все VisibilityValue) |
| StyleIssue | code, anchor (`SourceAnchor\|None`), style_id (`str\|None`) |
| ResolvedStyle | style_id, style_type, anchor, based_on (`str\|None`), is_default (`bool`), status (`resolved\|blocked\|opaque`), properties (`VisibilityProperties\|None`), issues (`tuple[StyleIssue,...]`) |
| StyleContext | source_sha256, profile, status (`ready\|absent\|blocked`), styles_part (`str\|None`), defaults (`VisibilityProperties\|None`), default_paragraph_style (`str\|None`), default_character_style (`str\|None`), styles (`tuple[ResolvedStyle,...]`), issues (`tuple[StyleIssue,...]`), context_sha256 |

Profile ровно `docx-visibility/styles-context-v1`. Этот DTO не имеет `complete`, document_id, analysis_text или новой policy: он не является snapshot результата анализа. Absent: styles_part=None, defaults=три absent values, default IDs=None, styles/issues=(). Global blocked: defaults=None, default IDs=None, styles=(), один global issue; styles_part известен только после однозначного выбора target. Ready: defaults определён, global issues=(); отдельные styles могут быть blocked/opaque. Consumer обязан проверять выбранный record, одного ready недостаточно.

Absent property — value=None/anchor=None; false и true всегда имеют anchor конкретного current property leaf, в том числе при наследовании. Anchor не подменять корнем стиля. Properties=None у blocked/opaque: неизвестное нельзя кодировать как три absent значения. Source SHA/part/path согласованы во всём context. В ready styles отсортированы по style_id, без Unicode/case normalization; issues внутри record сортируются по `(code, anchor.path либо (), style_id либо '')`, без дублей. У global issue style_id=None; anchor=None при неоднозначной части, иначе root выбранной styles part. У per-style issue anchor самого style и его style_id. Root/default errors не включают document payload.

context_sha256 = SHA256 canonical JSON всех перечисленных полей StyleContext кроме самого context_sha256, вложенные records со всеми перечисленными полями; ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False, UTF8. Anchors — source_sha256/part_name/path; tuple как array, None как null. Не хранить дополнительный canonical payload. Independent acceptance пересчитывает fingerprint. Digest — consistency, не доверенная подпись: будущий builder получает context из этих же pinned bytes, не от клиента.

## Grammar styles и текущих свойств

Контейнеры только whitespace text/tails; leaf без children и без non-whitespace text. Duplicate singleton children запрещены. У nodes допускаются только перечисленные Word attrs; XML namespace declarations не являются attrs ElementTree. `mc:*`, foreign attrs/elements, неизвестные Word attrs в прочитанных containers дают unsupported; не вычищать их автоматически. Это начальная ограниченная grammar, не обещание открыть произвольный styles.xml Word. Opaque table/numbering subtree и previous-property subtree отдельно описаны ниже.

Root attrs отсутствуют; children: не более одного docDefaults, не более одного latentStyles, любое bounded число style. docDefaults без attrs: optional single rPrDefault/rPr и pPrDefault/pPr; промежуточные containers без attrs и с не более одним соответствующим child. Отсутствие любого default container даёт отсутствующие свойства. Defaults rPr читается по grammar ниже; pPr — по узкой grammar ниже. Unsupported defaults блокируют весь context с `unsupported_defaults`.

style attrs: required w:styleId, w:type; optional w:default,w:customStyle. ID и basedOn reference — непустая строка до253 code points, без normalization/strip; arbitrary names не попадают в ошибки. type ровно paragraph/character/table/numbering; неизвестный type/отсутствующий ID/повторный ID/невалидные identity attrs — global `invalid_style_identity`. Default/customStyle имеют ту же lexical on/off grammar, что properties; отсутствие=false. Более одного default paragraph или character — global `duplicate_default_style`. Для first-cycle неоднозначные defaults прочих типов также блокируют с этим кодом. Порядок global проверки: однозначный target → bounded parse/root envelope (root attrs/children/singletons/text/tails) → identities → duplicate defaults → defaults grammar → latentStyles grammar. Один статический диагноз, никакие partial records при global blocker не выпускаются. Per-style grammar/graph проверяются только после этого.

Для paragraph/character style разрешены optional singleton basedOn (required w:val) и rPr; pPr — только для paragraph. Optional style metadata leaf: name/aliases/next/link (только required w:val), uiPriority (required w:val, ASCII decimal 0..2147483647), rsid (required w:val, ровно8 hex), autoRedefine/hidden/semiHidden/unhideWhenUsed/qFormat/locked/personal/personalCompose/personalReply (optional on/off w:val). Metadata не возвращается, link/next не обходятся как inheritance. Значение UI hidden не влияет на properties. Unknown current child/context/attribute/duplicate или malformed metadata делает **этот** style blocked `unsupported_style_structure`.

table/numbering с валидной identity/default оболочкой дают opaque record, properties=None, based_on=None и один `opaque_style_type` issue на style. Их descendants не интерпретируются, но XML/size/nodes/depth budgets применяются целиком. Это не доказательство безопасности/неиспользования этой части. Отдельные tables/numbering readers понадобятся позднее.

latentStyles — только UI metadata: attrs w:defLockedState/defSemiHidden/defUnhideWhenUsed/defQFormat (on/off), w:defUIPriority/w:count (ASCII decimal 0..2147483647); children lsdException leaf с required w:name, optional w:locked/semiHidden/unhideWhenUsed/qFormat (on/off), w:uiPriority (такой же decimal). Не создаёт material style IDs или visibility properties. Unsupported latentStyles блокирует context `unsupported_style_structure`.

Current rPr без attrs, optional singleton каждого: **vanish/specVanish/webHidden**, leaf formatting b/bCs/i/iCs/u/strike/dstrike/color/highlight/sz/szCs/vertAlign/lang/rFonts, и один rPrChange. У visibility leaf только optional w:val: отсутствие/`true`/`1`/`on` → true; `false`/`0`/`off` → false; другой регистр/пробелы/значения запрещены. Formatting leaf допускает любые attrs в текущем Word namespace, но не foreign/unqualified attrs/children/text; значения не вычисляются и не возвращаются. Это явное исключение из проверки списка атрибутов, не полная schema-валидация оформления. Unknown properties (включая rStyle в style definition, numbering/moves/fields/SDT) остаются unsupported, не сканировать их потомков в поиске vanish.

Current pPr без attrs, optional singleton spacing/ind/jc/outlineLvl/keepNext/keepLines/pageBreakBefore: leaf с любыми attrs в текущем Word namespace, без foreign/unqualified attrs/children/text, значения не вычисляются. Один pPrChange разрешён. Другие children, включая numPr/pStyle/mark rPr, делают definition/defaults unsupported: first-cycle не обещает resolve numbering/mark context через pPr. Не молча игнорировать потенциально влияющую на context структуру.

Histories: rPrChange ровно в current rPr, pPrChange ровно в current pPr, namespace совпадает. Wrapper attrs required w:id (`[+-]?[0-9]{1,20}`), optional w:author/w:date, без возврата значений. Ровно один child того же вида properties, whitespace container text/tails. Previous subtree исключается целиком из интерпретации: hidden/foreign text/old refs не становятся current. Input budgets включают всё subtree. Wrong context/ID/child/duplicate/tail → unsupported definition/defaults. Сведения об old text не возвращаются; current provenance никогда не указывает внутрь history.

## Разрешение basedOn

Индекс по exact style_id после проверки глобальных identities. Разрешить paragraph/character separately; self-cycle/длинный цикл, missing parent, parent другого типа и blocked parent дают blocked, properties=None. issue коды соответственно `style_cycle`, `missing_base_style`, `base_style_type_mismatch`, `unresolved_base_style`; anchor текущего style (не payload), style_id текущего style. Для участника цикла и стиля, достигающего цикла, code style_cycle; chain limit в любом случае exception, без выбора частичного ответа. Missing-parent — намеренный stricter admission, не заявление о поведении Word.

Для каждого из трёх свойств выбрать ближайший заданный current leaf: собственный, иначе parent, иначе absent. False — заданное значение, не повод продолжать поиск. Внутри basedOn-цепочки **нет XOR**. Не подмешивать docDefaults в properties каждого style; они возвращаются отдельно, отсутствие сохраняет None. Никакого выбора paragraph/character style для main runs, применения implicit default или определения hidden в этом цикле. Default IDs могут ссылаться на blocked record, поэтому consumer обязан проверять status. DocDefaults visibility values возвращаются напрямую с anchors.

Полный граф validate один раз: iterative DFS/memoization, без рекурсивного Python stack и без повторного полного обхода длинной цепочки для каждого record. Вычислить максимальную глубину пути для limit, даже когда properties уже заданы. O(XML nodes + styles + edges) плюс сортировки; output provenance занимает O(styles), не копии ancestor chains. Если base blocked, сохранять статический unresolved issue без рекурсивной копии всех его issues. У каждого blocked/opaque style ровно один issue, resolved issues=(). Для нескольких причин приоритет: own grammar → cycle → missing/type/blocked base по ближайшему ребру. Cycle detection выполняется среди грамматически валидных definitions; при встрече own-unsupported ancestor — unresolved_base_style.

## Независимая приёмка

До source зафиксировать synthetic packages и literal expected values/paths. Покрыть: отсутствующий styles; renamed/Strict/UTF16 parts; default и explicit false; цепочки true→true, true→false, absent→true, отдельные paragraph/character roots; docDefaults не встроены в style; style UI hidden/latentStyle не скрывают текст; current-vs-old histories; exact source leaf anchors; deterministic canonical fingerprint; frozen/slots/repr/no retained bytes/ET. XML anchors проверять независимо, не helper-ом реализации.

Отрицательная матрица: MIME/relationships/extra/orphan/external candidates; root/current foreign namespace и mc attrs; invalid identity/default duplicates; bad lexical booleans/containers/tails/history shape; missing/wrong-type/blocked parent/cycle; opaque table style не разрешается как paragraph; unsupported numPr/mark context; None не используется для маскировки unknown. Exact/+1 каждого лимита, длинная цепочка с property в каждом узле, широкое дерево с общим предком, budgets по исключённым histories/opaque content; неизменность source bytes, EOCD/DTD/entity guards.

Fresh subprocess запрещает файловую/env/network/process активность и unwanted imports; DOCX подаётся через stdin до guard, как в прежней приёмке. Regression A1/A2a/final_view/property_history; полный gate и runtime baseline обязательны. Это технический styles catalog, не Word/render/ML QA и не реализованная пользовательская проверка hidden text. Следующий цикл b2a2b получает собственный exact contract/приёмку до реализации.
