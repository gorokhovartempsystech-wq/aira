# D02-02 — структурное чтение DOCX и привязки к исходнику

28 октября 2026. Следующий ограниченный цикл после D02-01. Основание — [текущий объём продукта](current-product-scope.md): импортированные DOCX сохраняют оформление, замечания привязываются к тексту. Здесь создаётся read-only представление содержимого для будущего редактора и адаптера анализа. Это не готовый импорт в интерфейсе, не анализ и не редактирование DOCX.

## Границы

Добавить `ara.docx_package.projection` только в `src/ara/docx_package/projection/**`, собственные тесты — `tests/docx_projection/**`. D02-01, прежние Markdown/blocks/drafts, API, БД, ML-контракты, зависимости и runner не менять. Исходные bytes остаются источником истины. Не переводить документ в Markdown и не назначать случайные UUID.

Использовать только стандартную библиотеку. Импорты и вызовы не читают файлы/секреты, не обращаются к сети/БД, не запускают процессы и не логируют содержимое. Весь ввод — bytes. Не открывать гиперссылки, не исполнять поля/объекты, не выбирать варианты tracked changes. Уточнение пользователя о непринятых замечаниях AIRA не является решением о старых исправлениях внутри Word: эти две сущности различны.

## API и DTO

```python
project_docx(data: bytes, *, limits: DocxLimits | None = None,
             projection_limits: ProjectionLimits | None = None) -> DocxProjection
```

Модуль экспортирует `project_docx`, `ProjectionLimits`, `ProjectionError`, `SourceAnchor`. Имена остальных DTO не фиксируются, их атрибуты фиксированы ниже. Все возвращённые DTO неизменяемы, коллекции — tuples; не возвращать XML-деревья, dict/list или handles.

- `ProjectionLimits(max_nodes=100000, max_depth=128)`: frozen, строгие положительные int, не bool/float/str. Границы включительны. max_nodes считает все XML-элементы main part, включая свойства и неизвестные ветки. max_depth: корень имеет глубину 1. Проверять во время разбора, до построения неограниченного дерева. Это технические лимиты проектора, не продуктовый предел текста.
- `ProjectionError`: code=`invalid_input` либо `projection_limit_exceeded`, постоянный безопасный непустой message; str==message, нет содержимого документа/путей/сырой цепочки исключений. Неправильный projection_limits или его поля дают invalid_input. Валидацию data и limits, ZIP/OPC/XML выполнять существующим `open_docx`; его `DocxError` сохраняет значение и безопасность.
- `SourceAnchor`: `source_sha256`, `part_name`, `path: tuple[int, ...]`. part_name — фактическое ZIP-имя main part. Корень XML имеет path=(); каждый шаг — индекс среди **всех дочерних XML-элементов**, включая pPr/rPr, без comments/PI. Не предполагать body первым дочерним элементом. Адрес стабилен только в идентичном исходном файле, не переносится автоматически на изменённый файл.
- `DocxProjection`: `source: DocxSource`, `body_anchor`, `blocks`, `notices`, `has_unprojected_content: bool`, `coverage_scope="main-body-structural-v1"`. source — результат open_docx; export_original(source) побайтово равен входу. repr не содержит исходного ZIP. has_unprojected_content == bool(notices), это признак непроецируемого содержимого в данном техническом представлении, не оценка качества/полноты анализа или отображения Word.
- `Paragraph`: kind="paragraph", anchor, `text: str`, `spans: tuple`, `properties_anchor: SourceAnchor | None`, `style_id: str | None`, `numbering_id: str | None`, `numbering_level: str | None`, `has_opaque: bool`. Текст и spans описаны ниже.
- `Span`: kind="text"/"tab"/"break"/"opaque", anchor, `run_anchor: SourceAnchor | None`, `text: str`, `start: int`, `end: int`, `xml_space: str | None`, `break_type: str | None`, `hyperlink: Hyperlink | None`, `reason: str | None`. start/end — полуинтервал в text абзаца в Unicode code points (не bytes/UTF-16). Разные w:t одного run остаются разными spans. Для opaque reason непустой, для остальных None.
- `Hyperlink`: anchor, `relationship_id: str | None`, `bookmark: str | None`. Только буквальные r:id/w:anchor, без вычисления URL или сетевых обращений. Сам объект ссылки не потребляет текстовую позицию.
- `Table`: kind="table", anchor, `rows: tuple`, properties_anchor. `Row`: anchor, `cells: tuple`, properties_anchor. `Cell`: anchor, `blocks: tuple`, properties_anchor, `grid_span: str | None`, `vertical_merge: str | None`. Значения берутся из прямых свойств как строки; для присутствующего vMerge без val вернуть "continue", при отсутствии None. Не строить визуальную сетку и не дублировать текст объединённых ячеек.
- `OpaqueBlock`: kind="opaque", anchor, `reason: str`, `element_name: str` (expanded XML name). Ни text, ни рекурсивно извлечённое содержимое этого subtree не выдавать как обычный текст.
- `Notice`: `code: str`, `part_name: str`, `anchor: SourceAnchor | None`. Порядок детерминирован: main-part notices в порядке XML-элементов, затем notices других частей по part_name. Один notice на opaque block/span, дополнительные правила ниже. Дубликаты одного code/part/path не создавать. Notice не содержит пользовательского текста.

## Абзацы, текст и таблицы

Работать в Transitional и Strict WML namespace из D02-01, включая UTF-16. Читать только основную часть, найденную open_docx. Body содержит ordered blocks: прямые p, tbl и opaque для остальных элементов; прямой sectPr — свойства секции, сохраняются в source и не создают блок/notice. Не интерпретировать неизвестные обёртки рекурсивно как обычные абзацы.

Paragraph: сохранить пустые абзацы. Прямые pPr не дают текста; properties_anchor указывает на этот элемент. style_id — прямой pPr/pStyle/@val; numbering_id и numbering_level — прямые pPr/numPr/numId/@val и ilvl/@val. Не определять heading по английскому имени стиля, не вычислять наследование/эффективные стили и номера списков.

Обходить прямые runs и hyperlinks с прямыми runs в исходном порядке. Прямой rPr — свойства run, не текст. `w:t` даёт декодированный XML text без trim/normalize, сохраняется xml:space; ET/XML decoding может нормализовать переводы строк по стандарту XML, это не буквальная копия XML bytes. `w:tab` → "\t". `w:br` → "\n" с break_type из @type либо "textWrapping"; `w:cr` → "\n" и break_type="textWrapping". Для остальных spans xml_space и break_type равны None. run_anchor указывает на содержащий run; для неизвестного прямого элемента p он None. Пустой w:t остаётся zero-length span. start/end идут подряд, paragraph.text == concat(span.text).

Неизвестный/сложный элемент внутри paragraph/run/hyperlink становится **одним opaque span** с text="\uFFFC", точным anchor и reason="unsupported_element"; его subtree не разворачивается. Это включает рисунки, embedded objects, формулы, smartTag/sdt/customXml, MC AlternateContent и простые поля fldSimple. Не склеивать текст по сторонам пропуска без маркера. has_opaque == наличию opaque span; такой абзац нельзя позднее молча выдавать за полностью разобранный для ML.

D02-01 проверяет XML, но не полную WML-схему: известный leaf w:t/tab/br/cr с дочерними XML-элементами становится одним opaque span с reason="unsupported_structure". Не брать только .text и не разворачивать .itertext() неизвестных потомков.

Распознавать bookmarkStart/bookmarkEnd как нулевые служебные маркеры, не spans/notices; исходник их сохраняет. Word commentRangeStart/commentRangeEnd/commentReference, footnoteReference/endnoteReference, tab-объекты с неизвестной семантикой и прочие неподдержанные элементы остаются opaque. Комментарии Word не являются замечаниями AIRA.

Table: прямые tblPr/tblGrid — сохранённые свойства, не пользовательский текст. rows следуют по прямым tr; Row.cells по прямым tc; прямые trPr/tcPr — свойства. Содержимое cell — ordered blocks p/tbl/opaque, как body (без специального исключения sectPr). Вложенные таблицы поддерживаются. Пустые row/cell сохраняются, физические ячейки не размножаются. Если table имеет неизвестный прямой ребёнок кроме tblPr/tblGrid/tr, либо row — кроме trPr/tc, вернуть всю table как OpaqueBlock reason="unsupported_structure", а не терять неизвестный элемент вне DTO. Не выдавать неизвестный wrapper с вложенной table за простую table.

Не выбирать первый/последний из повторных одиночных свойств. Paragraph целиком opaque с reason="unsupported_structure" при нескольких прямых pPr, повторных pStyle/numPr внутри pPr, numId/ilvl внутри numPr либо rPr внутри любого проецируемого run. Table целиком opaque с той же причиной при повторных прямых tblPr/tblGrid, trPr в её row, tcPr в её cell либо gridSpan/vMerge в tcPr. Проверка касается этих конкретных путей, а не полной WML-схемы. Повторные свойства вложенной table блокируют её, а не автоматически внешнюю table. При совпадении причин приоритет: complex_field, затем tracked_change, затем unsupported_structure.

## Исправления и поля: консервативная граница

Непринятые исправления не выбирать автоматически. Если paragraph содержит в своём subtree WML ins/del/moveFrom/moveTo, *PrChange, tblGridChange, numberingChange, cellIns/cellDel/cellMerge либо move*RangeStart/move*RangeEnd — весь paragraph становится OpaqueBlock reason="tracked_change". Если такие элементы найдены в прямых свойствах table/row/cell (включая tblGrid), вся table становится opaque с той же причиной. Это не полная нормализация всех возможных Word revisions; неизвестные элементы остаются opaque по общим правилам.

Сложные поля fldChar/instrText могут пересекать paragraphs. Для данного цикла применяется намеренно широкое правило: **если любой такой WML-элемент найден в body subtree, весь body представлен одним OpaqueBlock с anchor body, element_name body и reason="complex_field"**. Инструкции, сохранённый результат и текст соседних абзацев не становятся молча окончательной версией. Сначала это правило, затем обычная структурная проекция. Это временная техническая граница D02-02; полноценная поддержка полей остаётся обязательной отдельной работой по текущему scope.

Для opaque блоков/сегментов notice.code равен reason. Для главной части вне body каждый прямой элемент кроме body/background даёт notice code="unprojected_root_element" с anchor; descendants не склеивать с body. background — оформление, сохраняется в source. XML comments/PI не считаются содержимым для этой проекции.

## Другие части и покрытие

Каждый файл source.entries кроме main part, таблицы типов и relationship parts перечислить в notices с anchor=None, **за исключением** известных вспомогательных типов:

- application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml
- application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml
- application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml
- application/vnd.openxmlformats-officedocument.wordprocessingml.webSettings+xml
- application/vnd.openxmlformats-officedocument.wordprocessingml.fontTable+xml
- application/vnd.openxmlformats-officedocument.theme+xml
- application/vnd.openxmlformats-package.core-properties+xml
- application/vnd.openxmlformats-officedocument.extended-properties+xml
- application/vnd.openxmlformats-officedocument.custom-properties+xml

Следующие точные content types дают code="unprojected_story":

- application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml
- application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml
- application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml
- application/vnd.openxmlformats-officedocument.wordprocessingml.endnotes+xml
- application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml
- application/vnd.openxmlformats-officedocument.wordprocessingml.document.glossary+xml

Остальные неизвестные XML/бинарные файлы → "unprojected_part". Использовать content type, не имя word/header1.xml. Это техническая ведомость, не удаление частей и не готовое предупреждение UI. Source сохраняет все файлы, включая вспомогательные.

## Матрица этого цикла и дальнейшего подключения

| Элемент | D02-02 читает | Сохраняет оригинал | Отображение/редактирование/экспорт правок |
|---|---|---|---|
| Абзацы, текст, runs, табуляции/разрывы, подписи ссылок | Структура, spans, anchors; XML-текст, не расчёт Word layout | Да, через D02-01 | Следующие циклы |
| Стили, заголовки, списки | Прямые ID свойств и anchors, без вычисления стилей/нумерации | Да | Следующие циклы |
| Таблицы и вложенные таблицы | Физические rows/cells, блоки, прямые merge metadata | Да | Следующие циклы |
| Изображения, формулы, сложные/неизвестные элементы | Opaque с точной привязкой | Да | Следующие циклы |
| Поля/оглавление, Word revisions | Консервативное opaque-покрытие | Да, без принятия/вычисления | Отдельное проектирование |
| Колонтитулы, сноски, Word comments и другие stories | Ведомость частей | Да | Следующие циклы |
| Шаблон нового документа AIRA | Не создаёт | Не применимо | Отдельное проектирование |

Старый split_markdown создаёт новые UUID и плоские блоки, а Analysis Block требует Markdown и запрещает дополнительные поля. Автоматического адаптера или отправки в анализ здесь нет. Будущий адаптер обязан учитывать notices/opaque и источник каждого span; метка scope не доказывает полноту анализа.

## Реализация чтения и приёмка

После open_docx читать main part через существующие безопасные internal `parsing_end/chunks` (или эквивалент с сохранением всех проверок D02-01); не открывать обычным ZipFile полные bytes без учёта сигнатур внутри archive comment. Не менять D02-01. Лимиты XML-дерева соблюдать также для opaque веток до возврата DTO.

Независимая приёмка: реальные anchors разрешаются по element-child path, одинаковые тексты имеют разные адреса, repeated open детерминирован, body не первый root child, Strict/UTF-16, XML whitespace/emoji, runs/links/tab/breaks/empty paragraphs, p-table-p/nested table/merge metadata, opaque boundary без склеивания, поля через несколько абзацев, revisions в свойствах и тексте, notices stories/unknown parts, limits/immutability/inert I/O. Синтетический контрольный DOCX D02-01 читается; экспорт source остаётся побайтовым. Не заявлять визуальную готовность редактора, Word-совместимость или выполнение анализа. Gate — `bash scripts/check.sh`. Остановиться после D02-02; статус пишет runner.

Первичные технические основания: [структура WordprocessingML](https://learn.microsoft.com/en-us/office/open-xml/word/structure-of-a-wordprocessingml-document), [таблицы](https://learn.microsoft.com/en-us/office/open-xml/word/working-with-wordprocessingml-tables), [FieldChar](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.fieldchar?view=openxml-3.0.1), [принятие Word revisions](https://learn.microsoft.com/en-us/office/open-xml/word/how-to-accept-all-revisions-in-a-word-processing-document), [markup compatibility](https://learn.microsoft.com/en-us/office/open-xml/general/introduction-to-markup-compatibility). Конкретная консервативная проекция и DTO — техническое решение этого цикла.
