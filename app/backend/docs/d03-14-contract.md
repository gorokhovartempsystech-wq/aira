# D03-14 — безопасное разбиение и склейка body paragraphs

31 октября 2026. Технический контракт подготовлен на Astra 6 по запросу Никиты, после 1b11943. **Статус: подготовка executable acceptance на Sol 6.1 High по следующей прямой команде Никиты; до её freeze реализация не начата.** Основной scope — current-product-scope.md; архитектура undo/доставки — [d03-14-design.md](d03-14-design.md). Исполнить только этот ограниченный pure цикл, затем отдельно D03-15. Не выдавать зелёную регрессию старого кода за готовность новых операций.

## Публичный Python API

Новый пакет `ara.docx_package.boundaries`:

```python
SplitParagraph(anchor: SourceAnchor, expected_text: str, offset: int)
JoinParagraphs(left_anchor: SourceAnchor, right_anchor: SourceAnchor,
               expected_left_text: str, expected_right_text: str)
BoundaryLimits(max_touched_nodes: int = 10000)
BoundaryError
export_boundary(data: bytes, command: SplitParagraph | JoinParagraphs, *,
                limits: DocxLimits | None = None,
                projection_limits: ProjectionLimits | None = None,
                boundary_limits: BoundaryLimits | None = None) -> bytes
```

DTO frozen/slotted, expected text исключён из repr. Настоящие типы, bool не int, subclasses не принимаются; повторная валидация объектов после frozen bypass. SourceAnchor/hash/path проверяются по строгому D03-11 правилу. Offset — число Unicode code points, 0..len(projected paragraph.text), включая обе границы. Expected text сравнивается целиком без trim/normalization. Лимиты — положительные int; touched nodes — объединение всех element descendants выбранных p, включая p/pPr/rPr. Лимит проверяется до создания копий этих поддеревьев. Package/projection limits применяются ко входу и результату.

Одна операция на один исходный пакет. Batch split/join не входит в этот цикл: последовательные команды требуют нового projection. Никакого I/O, логирования, env/secrets, БД, HTTP, потоков, nondeterministic IDs или новых зависимостей. Пустая строка является содержимым существующего paragraph, а не отсутствием команды.

## Доступные targets и ранние отказы

Main part берётся из package, не hardcode word/document.xml. Target — прямой p в одном body, не cell/текстовый span/opaque. Для join right должен быть следующим прямым element-child после left; таблицу, SDT, sectPr, другой p или range marker нельзя перескочить. Между p допустим только XML formatting whitespace; comments/PI на стыке дают отказ. Аннотации внутри targets также отклоняются.

Общие gates D03-11: protection/settings/signature/tracking, global field/range/bookmark markers и target opaque/hyperlinks/sectPr остаются. Не обходить global gate на том основании, что selected paragraph кажется простым. Наличие сохранённого opaque элемента в другом месте само по себе не запрещает операцию, если прежние gates его не запрещают. Сохранять непроецируемое содержимое пакета.

Контент target p: не более одного pPr в первом element position; далее только стандартные r. Контент r: не более одного rPr первым, затем t/tab/br/cr. Разрешены tab и мягкие br с absent type или textWrapping, cr как прежний мягкий break. Page/column breaks и br с clear, fldChar/instrText, drawing, footnote/endnote refs, revisions/markup-compatibility wrappers, неизвестные content nodes — unsupported_boundary. Literal CR/LF/TAB внутри t для первой реализации отклоняются: native control elements поддерживаются явно, не смешивать их с XML whitespace normalization.

Параграфные attributes: сохранить на выжившем исходном p только те, что уже были; поддержаны xmlns declarations, w:rsidR/w:rsidRDefault/w:rsidP/w:rsidRPr и w14:paraId/w14:textId. При создании второго p копировать только namespace context; revision/identity attributes не дублировать. При join ID правого p исчезает вместе с явно удаляемой границей. Любые другие p attributes (в частности xml:id/xml:base/xml:lang/xml:space и mc:*) в первой реализации отклоняются, пока для них нет отдельного правила наследования. Никакие непризнанные attributes нельзя молча выбросить.

Допустимые pPr children: pStyle, numPr, keepNext, keepLines, widowControl, spacing, ind, jc, outlineLvl, tabs, contextualSpacing, bidi, snapToGrid, suppressAutoHyphens, adjustRightInd, rPr. Только известные стандартные Word namespaces/структуры, без extension nodes, duplicate singleton properties или revisions. pageBreakBefore/framePr/sectPr/прочие неизвестные pPr дают отказ. Для tabs допускаются tab definitions. numPr — только numId и optional ilvl=0; ссылки должны быть однозначными и корректными по D03-12 level-0 правилам. Numbering.xml не изменяется. Наследуемое numbering через style без прямого numPr в первой реализации не распознавать как поддержку списков; styling resolver нужен отдельно.

Допустимые run/paragraph-mark rPr children первой версии: rStyle, rFonts, b, bCs, i, iCs, caps, smallCaps, strike, dstrike, outline, shadow, emboss, imprint, noProof, snapToGrid, vanish, webHidden, color, spacing, w, kern, position, sz, szCs, highlight, u, vertAlign, rtl, cs, em, lang, specVanish. Только стандартные Word nodes без вложенного контента/unknown attrs; значения сохраняются дословно, никакой оценки theme/font по умолчанию. Неизвестные/сложные свойства, включая eastAsianLayout с групповым id, требуют отказа, не удаления. Это ограничение безопасного копирования, не полный XSD-validator Word и не resolver наследования.

Разрешённые attributes свойств (expanded names в namespace родительского Word element; xmlns декларации учитываются отдельно). Другие attributes дают unsupported_boundary. В pPr/rPr/tabs/numPr самих обычных attributes нет. Все property children singleton, кроме нескольких tab внутри tabs; внутренние rPr children также singleton.

| Property | Attributes |
|---|---|
| pStyle, numId, ilvl, outlineLvl, jc, rStyle, run spacing, w, kern, position, sz, szCs, highlight, vertAlign, em | val |
| keepNext, keepLines, widowControl, contextualSpacing, bidi, snapToGrid, suppressAutoHyphens, adjustRightInd; b/bCs/i/iCs/caps/smallCaps/strike/dstrike/outline/shadow/emboss/imprint/noProof/vanish/webHidden/rtl/cs/specVanish | optional val |
| paragraph spacing | before, beforeLines, beforeAutospacing, after, afterLines, afterAutospacing, line, lineRule |
| ind | left, leftChars, right, rightChars, start, startChars, end, endChars, firstLine, firstLineChars, hanging, hangingChars |
| tab в tabs | val, pos, leader |
| rFonts | ascii, hAnsi, eastAsia, cs, hint, asciiTheme, hAnsiTheme, eastAsiaTheme, cstheme |
| color | val, themeColor, themeTint, themeShade |
| u | val, color, themeColor, themeTint, themeShade |
| lang | val, eastAsia, bidi |

Названия сверены по первичным описаниям [rFonts](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.linq.w.rfonts?view=openxml-3.0.1), [ind](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.linq.w.ind?view=openxml-3.0.1), [spacing](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.linq.w.spacing?view=openxml-3.0.1). Не смешивать paragraph spacing с run spacing. Синтетическая positive acceptance должна содержать каждую группу свойств; отдельные negative cases проверяют неизвестный attribute/child, вложенный content и duplicate singleton. Значения не пересчитываются; явные pStyle/rStyle references и тематические значения сохраняются как исходные строки.

Run attributes: только xmlns, w:rsidR/w:rsidRPr/w:rsidDel. Text attributes: только xmlns/xml:space. Для native controls — только известные Word attributes описанного мягкого break. Нестандартные attrs отклонять. Local namespace declarations внутри property subtrees поддерживать, сохраняя их значение. Префикс не является namespace identity.

Word elements и Word attributes внутри выбранного paragraph должны принадлежать тому же Word namespace, что и p: не смешивать Transitional и Strict в одном target. Alias prefixes с тем же URI допустимы. br может иметь только type=textWrapping (или отсутствующий type); у content tab/cr обычных attributes нет. Element xml:space допустим только у t по правилу выше. Это не относится к табулятору в pPr/tabs, у которого своя строка attributes в таблице.

## Split

Для исходного T и offset k ожидаемые тексты: T[:k], T[k:]. Никакой добавленной/удалённой пробельной строки; количество body paragraphs +1. Offset 0/end и пустой p допустимы и всегда создают настоящий structural change.

Левый p сохраняет исходный opening/closing tag, attributes и точный pPr. Правый p новый, с тем же expanded Word namespace, эффективным namespace context исходного p и семантически тем же pPr. Полный прямой формат обеих частей сохраняется; w:next здесь не применяется. Если был прямой list ID, обе части ссылаются на него: номер следующего пункта — обычный результат Word numbering, без новых definitions/ID.

Последовательность видимых атомов из t/tab/br/cr соответствует source projection: TAB/LF имеют длину 1. Целые runs и целые t/control elements, попавшие на одну сторону, копируются точными bytes. Если k проходит внутри run, расколоть только его content sequence и создать оболочку run для второй части, скопировав разрешённые rPr/attributes. Если k проходит внутри t, разделить decoded Unicode text; обе изменённые t части безопасно XML-экранировать и задать xml:space=preserve. Не делить байты UTF-8/UTF-16 и не резать XML entity по сырой позиции.

Zero-width t/r nodes имеют явное владение: позиция < k относится к левой стороне, позиция ≥ k — к правой. Внутри разрезаемого run rPr копируется на обе непустые по XML content стороны. Оболочку без content не сохранять как лишний run; пустой paragraph без run допустим. Весь исходный content node переносится ровно один раз, кроме необходимого клонирования format properties/оболочки разрезанного run. Не добавлять zero-width текст ради старого span-only UI — этот цикл не меняет UI.

XML formatting whitespace вне content nodes сохранять там, где остаются исходные tags; внутри переписываемого target допустимо канонизировать только незначимые межэлементные gaps. Непробельный mixed character content вне t запрещён. Слова/пробелы внутри t всегда значимы для проверки инварианта.

## Join

Результат текста строго left.text + right.text, без автоматического пробела/переноса. Количество p −1, хотя бы один p остаётся. Пустой левый/правый/оба — допустимы при тех же gates. Backspace/Delete используют одинаковый primitive; направление клавиши не меняет правило сохранения стиля.

Первый релиз требует одинаковой canonical structural signature всего pPr обоих paragraphs: expanded element/attribute names, точные attribute values, порядок children; без сравнения namespace prefix/attribute order/XML formatting whitespace. Отсутствующий pPr и пустой pPr считаются одинаковыми. Не сравнивать только style_id: прямые spacing/ind/rPr/numPr тоже имеют значение. Один отсутствующий pStyle и явный Normal не объявляются равными без resolver. Одновременно required effective Word namespace обоих p одинаков. Неподдержанные QName-valued/extension properties уже исключены allowlist.

При различии signature вернуть incompatible_paragraph_format до patch. Это включает Heading1+Normal, два разных list IDs/levels, разные прямые свойства. Одинаковые references в одном document/body сохраняют общий контекст наследования. Различное прямое inline rPr внутри отдельных runs разрешено и сохраняется.

Сохраняются левый p opening/closing/attributes/pPr; весь content правого p добавляется после левого content, правый pPr и контейнер удаляются. Содержимое runs и rPr не переписывается кроме недостающих namespace declarations на перемещаемых оболочках. Нельзя вставить right p внутрь left p или оставить два pPr. Новый источник после join заново проецируется.

## Namespace/encoding и сохранение пакета

Поддержать UTF-8 и UTF-16 LE/BE, Strict/Transitional WML и локальные xmlns по прежним validators. Namespace context считать bounded stream scan со stack, сохранять полные maps только для выбранных перемещаемых boundaries, не копировать весь ancestor-map для каждого node документа. Переносимое поддерево сохраняет исходные prefix→URI bindings, включая default namespace и локальные redeclarations; в новой оболочке добавить необходимые declarations, не менять bindings существующего левого p. Сохранить внутренние shadowing declarations. Имена новых tags выбирать без конфликта с исходными prefixes.

Это требуется правилами [W3C namespace scoping/defaulting](https://www.w3.org/TR/xml-names/#scoping): декларации действуют в области XML-элемента. Наше правило rehoming — способ сохранить эту область при переносе, не заявление, что ElementTree serialization гарантирует визуальную эквивалентность DOCX. Не делать prefix replacement по строке и не сериализовать main XML целиком.

Изменяется только main part в lexical ranges выбранных p; bytes вне этих ranges, прочие ZIP parts/order/metadata сохраняются через прежний repack. Разрешены необходимые изменения text lexemes/xml:space/namespace declarations внутри selected nodes; обещание «всё внутри target побайтово прежнее» неверно. Стандартные package/projection/settings gates не переписывать. Проверить output text/order, наличие обоих/одного p, сохранение свойств и отсутствия дубликатов IDs. Join(split(source)) обязан сохранить текст/оформление в разрешённых границах, но не обязан вернуть исходный ZIP hash; точный возврат — undo snapshot.

## Диагностика

BoundaryError.code: invalid_input, boundary_limit_exceeded, stale_source, invalid_anchor, invalid_position, text_mismatch, nonadjacent_paragraphs, incompatible_paragraph_format, unsupported_boundary. Постоянные content-free сообщения, str=message. Дубликат left/right — nonadjacent_paragraphs. Foreign part/span/cell anchor — invalid_anchor. Range outside string — invalid_position. Отсутствие поддержки/защита/unknown properties/семантически небезопасный XML — unsupported_boundary. Ошибки DocxError/ProjectionError сохраняют класс и code. Приоритет: validation/limits → input package → source hash → anchors/order/position/text → compatibility/support gates → patch/output validation. Ни одна ошибка не возвращает частичный пакет.

Если прежний projector из-за complex fields делает весь body opaque, projected paragraph target отсутствует и по этому порядку получается invalid_anchor. Такой negative fixture проверяется как отказ, без индексации несуществующего Paragraph в тестовом builder. Для валидно проецируемых targets с global blocked markers ожидается unsupported_boundary. При сравнении pPr сначала проверить допустимость структуры/attributes, затем signature: неизвестные свойства не должны маскироваться кодом incompatible_paragraph_format.

## Приёмка перед кодом

Подготовить `tests/acceptance/test_docx_boundaries.py` и `test_docx_boundary_preservation.py` с синтетическими валидными fixtures, проверить fixtures прежним projector, заморозить acceptance отдельным коммитом и выполнить red. Не помещать необоснованные новые ограничения в тесты после реализации ради green. В этом design-цикле executable acceptance не создаётся и не объявляется уже пройденной.

| ID | Обязательный сценарий | Что доказать |
|---|---|---|
| B01 | Split середина/начало/конец/пустой p, selfclosing p/pPr/t | Точные две строки, +1 p, сохранение attributes/format |
| B02 | Внутри t, между t, внутри/между runs с bold/italic/rStyle | Формат каждого исходного символа и отсутствие лишних символов |
| B03 | Leading/trailing spaces, XML entities, кириллица, emoji, combining marks, UTF16 | Code-point offset, escaping, xml:space; никакой normalization |
| B04 | TAB/br/cr перед/после cut; page/column/clear и literal controls в t | Мягкие controls сохранены; неподдержанное отклонено |
| B05 | Heading и level-0 list split | pPr обеих частей, тот же numId, numbering/styles exact; next не применяется |
| B06 | Join одинаковых pPr, mixed inline runs, пустые p | Конкатенация без разделителя, один pPr, все run properties |
| B07 | Heading+body, direct props mismatch, разные numId, missing vs explicit style | incompatible_paragraph_format и исходные bytes неизменны |
| B08 | Не соседние p, таблица/section между, reverse/duplicate/foreign/cell anchors | Точный отказ; не перескакивать через структуру |
| B09 | Local/default namespaces, prefix collision/rebinding в p/r/rPr/t, Strict | Expanded names/attrs до/после эквивалентны; вывод не только parseable |
| B10 | p IDs/rsids, unknown attributes/properties, XML comments/PI, mixed content | Новый p без duplicate IDs, исходный ID сохранён, безопасные отказы |
| B11 | Защита/подписи/tracking/fields/bookmark/comment ranges/hyperlinks/opaque | Прежние gates сохраняются, сложные элементы не исчезают |
| B12 | Synthetic rich package с таблицей/рисунком/headers вне targets | Остальные parts и ranges точные, состав/order/metadata ZIP прежние |
| B13 | Corrupt input/frozen bypass/bool offset/negative/out-of-range/stale/mismatch | Безопасные ошибки до результата; никакой coercion |
| B14 | Touched-node/package/projection limits на входе/росте output | Инклюзивные границы, один менее — отказ без результата |
| B15 | Inert imports/API, повтор одинаковой команды на одинаковых bytes | Нет I/O/log/secrets; детерминированный результат |
| B16 | Split→fresh projection→compatible join | Исходный текст и оформление; не требовать ZIP-byte inverse |

Визуальный QA реализации: existing rich fixture + AIRA heading/list/inline formatting, результат split и join отрендерить bundled LibreOffice, просмотреть все страницы; исходник и изменённые runs/нетронутые parts проверить структурно. Отдельно зафиксировать отсутствие проверки целевого Word, пока его действительно не запускали. Рендер не заменяет namespace/metadata/ID tests. История exact undo проверяется в D03-15, не заявляется готовой в D03-14.

## Разрешённые пути и завершение

Подготовка: этот контракт, два новых acceptance файла выше. Код: только `src/ara/docx_package/boundaries/**`; собственные проверки `tests/docx_package/test_boundary_*.py`; отчёт `docs/d03-14-result.md`. Разрешено вызывать существующие private readers/repack, но не менять их в этом цикле. Если доказан необходимый shared fix — вынести конкретное изменение в отдельную задачу до правки frozen контрактов. Не менять session/HTTP/DB/ML/UI/dependencies/runner/tasks/progress/AGENTS или старые tests. QA — ignored .runtime, исключительно synthetic.

После реализации: целевые frozen tests, `bash scripts/check.sh`, визуальный QA, сохранность основной БД, локальный commit/result. Только затем отдельный D03-15 контракт и реализация общей истории. Следующий рекомендуемый режим — Sol 6.1 High. D03-14 не должен расширяться до всех последующих циклов для объявления редактора готовым.
