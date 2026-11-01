# D02-03 — точечные правки текста и экспорт DOCX

29 октября 2026. Один ограниченный цикл после D02-02, часть F05/F10/F11 из [текущего объёма](current-product-scope.md). Пользователь продолжил разработку после обсуждения правок и обратного экспорта. Это техническая операция для будущего редактора: заменить текст выбранных фрагментов, сохранив исходное оформление. Интерфейс и автоматическое применение замечаний сюда не входят.

## Границы

Добавить только `src/ara/docx_package/editing/**` и собственные тесты `tests/docx_editing/**`. Существующие D02-01/D02-02, API, БД, Markdown, ML, зависимости и runner не менять. Только стандартная библиотека; операции чистые, в памяти, без файлов, сети, БД, процессов и логирования документа. Исходный файл не изменяется. Использовать заново проверенную проекцию D02-02, не доверять присланному дереву/DTO документа.

Это замена целого `kind="text"` span, то есть одного существующего `w:t`. Поддержать абзацы, подписи гиперссылок и ячейки вложенных таблиц, которые уже доступны в проекции. Несколько замен могут менять разные spans одного run или абзаца. Вставка/удаление блоков, создание runs, перевод строки/табуляция, изменение оформления, перенос диапазонов между runs, новые документы и шаблон AIRA остаются следующими задачами. Удаление всего текста узла разрешено: пустой узел и его run сохраняются.

## API

Модуль `ara.docx_package.editing` экспортирует:

```python
TextEdit(anchor: SourceAnchor, expected_text: str, replacement_text: str)
EditLimits(max_edits: int = 1000, max_total_replacement_chars: int = 1000000)
EditError
export_docx(data: bytes, edits: tuple[TextEdit, ...], *,
            limits: DocxLimits | None = None,
            projection_limits: ProjectionLimits | None = None,
            edit_limits: EditLimits | None = None) -> bytes
```

`SourceAnchor` — существующий тип D02-02. TextEdit и EditLimits — frozen/slotted DTO. TextEdit repr не содержит expected_text/replacement_text. Все DTO и их поля проверяются при вызове, включая объекты, изменённые обходом frozen. Не полагаться только на конструктор. Контейнер edits — строго tuple, элементы — TextEdit; якорь — SourceAnchor. Строки — настоящие str. source_sha256 — 64 lowercase hex; part_name — непустая строка; path — tuple неотрицательных настоящих int, не bool. Неверный тип/форма — invalid_input. Не принимать генераторы, произвольные mappings, XPath или индексы текста от клиента.

EditLimits: настоящие положительные int, границы включительны. Считать все переданные edits и длины всех replacement_text в Unicode code points, включая no-op. Превышение — edit_limit_exceeded; проверить до построения нового XML. Это технические пределы вызова, не продуктовый предел длины документа. Параметры limits и projection_limits проверяются существующими механизмами.

## Проверки и атомарность

1. Заново прочитать и проверить bytes через D02-02 с переданными лимитами.
2. Каждый source_sha256 должен совпасть с исходником, иначе stale_source. part_name и path должны указывать именно на проецируемый text span в этом исходнике, иначе invalid_anchor. Адреса properties, табуляций, рисунков, скрытого текста, других частей и непрозрачных блоков запрещены. Наличие opaque-фрагмента в другом месте само по себе не запрещает менять доступный text span.
3. expected_text должен точно совпасть с текстом span, иначе text_mismatch. Никаких trim/normalization, Unicode code points сохраняются. Два edits одного адреса запрещены как duplicate_edit, даже если одинаковы или один no-op.
4. replacement_text должен состоять из разрешённых XML 1.0 символов: U+0009/U+000A/U+000D, U+0020–D7FF, E000–FFFD, 10000–10FFFF. Остальные, включая lone surrogates, дают invalid_input. В фактически изменяемом replacement_text табуляция/CR/LF дают unsupported_edit: в этом цикле нельзя незаметно превращать их в обычный текст вместо Word-элементов. No-op с уже существующими переводами строк допустим.
5. Все edits проверяются до возврата результата. Ошибка любого из них не даёт частичного экспорта. При пустом edits или всех replacement_text == expected_text вернуть точные исходные bytes после проверки аргументов/якорей/лимитов. No-op не переписывает XML/ZIP и не требует поддержки кодировки для редактирования.

Повторная отправка прежних anchors к изменённому файлу даёт stale_source. Для следующей правки вызывающий заново получает проекцию нового файла. Автоматического переноса anchors между версиями нет.

EditError: `code` из invalid_input, edit_limit_exceeded, stale_source, invalid_anchor, text_mismatch, duplicate_edit, unsupported_edit; `message` — постоянная безопасная непустая строка для каждого code, str == message. Не раскрывать текст, пути, XML/ZIP или parser traceback. Ошибки исходного/итогового пакета остаются DocxError, лимитов проекции — ProjectionError. Не маскировать ошибки в пустой успешный результат.

## Сохранение XML и частей

Обязательно редактировать Transitional и Strict WML, UTF-8 с BOM/без, UTF-16 LE/BE с BOM и корректно объявленные LE/BE без BOM. Сохранять исходную кодировку, BOM и XML declaration. Для других валидных исходных кодировок фактическая правка может дать unsupported_edit; no-op сохраняется.

Не сериализовать целиком XML через ElementTree: префиксы и namespace declarations могут быть значимы для `mc:Ignorable` и неизвестного содержимого. Менять байтовые диапазоны только выбранных `w:t`. Все bytes основной части вне этих элементов обязаны совпадать с исходником, в том числе пробелы, comments, PI, неизвестные расширения и namespace-префиксы. Лексические границы определять XML-aware, с учётом кавычек, CDATA, entities и кодировки; простая замена текста/regex по всему XML недопустима.

Внутри изменённого w:t разрешено заменить его текстовое содержимое и изменить/добавить только `xml:space="preserve"`. Все остальные атрибуты, их значения и имя элемента сохраняются. Existing xml:space="default" заменить на preserve; preserve оставить. Self-closing w:t при непустой замене раскрывается в пару тегов. XML escaping обязан сохранять точный replacement_text после повторного разбора, включая &, <, >, кавычки, эмодзи и Unicode. CDATA/character references внутри изменённого узла могут стать обычным экранированным текстом. Если внутри целевого w:t есть XML comment/PI, фактическую замену отклонить unsupported_edit, чтобы не удалить их молча. Comments/PI вне него сохраняются.

Нетронутые w:t должны оставаться побайтово идентичны, даже если их текст совпадает с редактируемым. Свойства абзаца/run/таблицы/ячейки/секции, нумерация, стили, рисунки, ссылки и прочие части не меняются. Длина нового текста может законно поменять переносы/число страниц.

При фактической правке отклонять unsupported_edit пакеты с признаками OPC digital signatures: имя части начинается с `_xmlsignatures/` без учёта регистра, тип связи содержит `/digital-signature/` или content type содержит `digital-signature`. Также отклонять при любом WML documentProtection или включённом trackRevisions в части content type `application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml`. Для trackRevisions отсутствие val или любое значение, кроме `0`, `false`, `off`, означает включено. Даже documentProtection с enforcement=false пока отклоняется консервативно. Не удалять/обходить защиту, не инвалидировать подпись молча. No-op разрешён. Существующие tracked changes остаются непрозрачными по D02-02; не принимать и не отклонять их автоматически.

Части settings находить по указанному content type и по Internal settings relationships главной части (`http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings` и `http://purl.oclc.org/ooxml/officeDocument/relationships/settings`). Кандидаты объединяются по фактическому resolved_part. Несколько кандидатов, External settings relationship, несовпадение content type либо корень не WML settings дают unsupported_edit при фактической правке. Отсутствие settings допустимо. Gate проверяет WML элементы во всех потомках, включая MC wrappers; чужой namespace с теми же local names не блокирует. Дублирующийся trackRevisions также unsupported_edit, даже если оба выключены. Это консервативная проверка, не полноценное вычисление правил совместимости Word.

Технические основания: [Python Expat](https://docs.python.org/3/library/pyexpat.html) и [zipfile](https://docs.python.org/3/library/zipfile.html), Microsoft [TrackRevisions](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.trackrevisions?view=openxml-3.0.1), [DocumentProtection](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.documentprotection?view=openxml-3.0.1), [OPC digital signatures](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/opc/digital-signatures-overview). Запрет documentProtection с выключенным enforcement строже стандарта и является временной границей D02-03.

## ZIP и итоговая проверка

Читать через существующие parsing_end/chunks, учитывая допустимые служебные ZIP-сигнатуры в комментарии. После изменения допустима перепаковка ZIP; побайтовое совпадение всего архива не требуется. Сохранить порядок/имена всех entries, directory entries, точное содержимое каждой части кроме main, archive comment, entry comment, date_time, compress_type, create_system, external_attr и internal_attr. CRC/size/offsets/flags пересчитываются корректно. Неструктурные extra fields сохранить; структурное ZIP64 extra (id 1) можно пересчитать/удалить при перепаковке небольшого архива, оно не должно содержать старые размеры.

Повторно валидировать экспорт теми же DocxLimits/ProjectionLimits до возврата bytes. Превышение любого лимита, включая выросший XML/размер архива/распакованную сумму, не должно отдавать некорректный результат. Полученная проекция обязана содержать запрошенные изменения. Порядок независимых edits не влияет на содержимое частей или итоговые bytes. Никаких новых служебных частей, комментариев AIRA или искусственных timestamps.

## Приёмка

Независимые тесты родителя: `tests/acceptance/test_docx_editing.py`, `tests/acceptance/test_docx_editing_boundaries.py`, при необходимости отдельный helper. Их зафиксировать до реализации, показать красный gate. Внутренний исполнитель их не меняет.

Проверить реальные варианты XML/ZIP, точное сохранение всех нетронутых bytes/частей/метаданных, Unicode/пробелы/escaping, пустые узлы, повторяющийся текст, nested tables/hyperlinks, атомарность/stale anchors, opaque/revisions/поля/защиту/подписи, лимиты, безопасные ошибки и отсутствие внешних действий. Повторно открыть результат D02-01 и D02-02. Полный `bash scripts/check.sh` обязателен.

На синтетическом `tests/fixtures/docx/rich-source.docx` сделать через новый API несколько правок обычного текста, подписи ссылки и ячейки таблицы. Структурно сравнить нетронутые части и свойства; отрендерить исходник и изменённый файл bundled LibreOffice, просмотреть все страницы. Это проверка сохранения оформления контрольного файла, а не доказательство совместимости со всеми Word-файлами/версиями Microsoft Word. Не использовать архив пользователя.

После одного цикла остановиться. UI, HTTP, сохранение DOCX в БД, полноценный визуальный редактор, сложные поля, редактирование revisions, шаблон AIRA и ML остаются отдельной работой.
