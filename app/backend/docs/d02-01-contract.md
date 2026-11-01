# D02-01 — сохранение исходного пакета DOCX

28 октября 2026. Первый технический цикл после решения сохранять оформление импортированных DOCX; часть F05/F11/F12 из [текущего объёма](current-product-scope.md). Проверить пакет, получить неизменяемый каталог частей и связей и вернуть исходный файл без изменений. Это основа последующего импорта и редактирования, не готовая обработка всего содержимого Word.

## Техническое решение и границы

Исходные байты DOCX — источник истины для оформления и ещё не интерпретируемых элементов. Экспорт без правок возвращает именно их, без пересборки ZIP, сериализации XML, обновления свойств или принятия tracked changes. Текстовая проекция для редактора/ML будет отдельной структурой следующего цикла. Не заменять DOCX Markdown-строкой и не складывать файл/base64 в существующие provenance/blocks.

Добавить только чистый Python-пакет `ara.docx_package` со стандартной библиотекой. Нет БД/миграций, HTTP, файловых путей на входе, распаковки на диск, сети, запуска Office/LibreOffice, анализа, редактирования, текстовой проекции или шаблона AIRA. Существующие модели, Markdown, drafts, API/ML-контракты и задачи сохраняются.

Проверка относится к контейнеру OPC, связям, типам содержимого и базовой XML-структуре. Это не полная XSD/OOXML-валидация, не антивирус и не гарантия отображения любого файла в любой версии Word. Непрозрачные корректные части сохраняются, а не объявляются потерянными или проанализированными.

## Публичный API

`ara.docx_package` экспортирует `DocxError`, `DocxLimits`, `DocxSource`, `open_docx`, `export_original`:

```python
open_docx(data: bytes, *, limits: DocxLimits | None = None) -> DocxSource
export_original(source: DocxSource) -> bytes
```

Принимать именно bytes (не путь/str/bytearray/memoryview); ограничения — только DocxLimits либо None. Импорты и вызовы выполняются в памяти, не читают настройки или файлы, не создают временных каталогов, не открывают сеть/БД и ничего не логируют. Все возвращённые структуры неизменяемы; вложенные коллекции — tuples, не изменяемые dict/list. Исходные байты не включать в repr.

DocxSource имеет публичные атрибуты:

- `sha256`: SHA-256 исходного архива в lowercase hex;
- `size_bytes`: длина исходного bytes;
- `main_part`: фактическое имя главной части внутри ZIP без начального `/`;
- `entries`: tuple записей с `name`, `content_type`, `size_bytes`, `sha256`, отсортированная по name; все файловые элементы ZIP, включая `[Content_Types].xml`, для которого content_type=None; каталоги не включаются;
- `relationships`: tuple записей с `source_part`, `relationship_id`, `relationship_type`, `target`, `target_mode`, `resolved_part`, отсортированная по (source_part, relationship_id). Для package-level source_part="/", для остальных — имя исходной части без `/`. target хранится дословно, target_mode — Internal или External, resolved_part — фактическое имя целевого элемента либо None для External.

Имена классов записей каталога/связей не фиксируются. Сервис не возвращает XML-деревья, открытый ZipFile или файловые handles. export_original для объекта от open_docx возвращает bytes, побайтово равные входу; несколько вызовов и повторное открытие дают тот же SHA/каталог. На объекте другого типа — invalid_input.

## Ограничения ресурсов

DocxLimits — неизменяемая структура с пятью положительными настоящими int (не bool/float/str):

| Поле | Значение по умолчанию |
|---|---:|
| max_archive_bytes | 33554432 |
| max_entries | 4096 |
| max_part_bytes | 67108864 |
| max_total_uncompressed_bytes | 134217728 |
| max_xml_bytes | 8388608 |

None означает эти значения. Это технические ограничения данного загрузчика, не согласованный продуктовый лимит текста или модели. Превышение явно отклоняется, содержимое не обрезается. Проверять длину архива и объявленные ZIP-размеры до распаковки; фактические размеры и CRC — при ограниченном чтении. Нельзя сначала без ограничения прочитать oversized часть, а затем проверять размер. max_entries считает все элементы ZIP, включая каталоги; max_part_bytes и max_total_uncompressed_bytes — файловые элементы; max_xml_bytes — каждый XML, который будет разобран. Размеры по границе включительно допустимы. Некорректный DocxLimits даёт invalid_input.

## ZIP и имена

Поддержать обычные ZIP с STORE/DEFLATE, валидным CRC, включая комментарий архива и ZIP metadata, которые сохраняются исходными bytes. Зашифрованные элементы и другие методы сжатия — unsupported_package. Невалидный ZIP, CRC, дублирующие либо неоднозначные имена — invalid_package.

Имена файлов — относительные URI-пути без начального `/`, backslash, NUL, query/fragment, пустых сегментов, `.` или `..`; сегменты не заканчиваются точкой. Корректные percent-escape разрешены и остаются в именах, но закодированные slash/backslash/NUL/dot-segments и закодированные unreserved-символы отклоняются как неоднозначные. Некорректные escape также отклоняются. Сравнение частей ASCII case-insensitive; две записи с эквивалентными именами недопустимы. Для результата сохранять фактическое написание ZIP-имени. `[Content_Types].xml` — специальное допустимое имя. Явные записи каталогов допустимы, проверяются аналогично без завершающего `/`, в каталог source.entries не входят. Symlink entries дают unsupported_package. Ничего не извлекать на диск.

## OPC и главная часть

Обязательны `[Content_Types].xml` и `_rels/.rels` с соответствующими root-элементами и namespace `http://schemas.openxmlformats.org/package/2006/content-types` / `http://schemas.openxmlformats.org/package/2006/relationships`.

Content Types: Default по расширению и Override по абсолютному имени части. Override имеет приоритет; каждому файловому элементу кроме самой таблицы типов должен соответствовать непустой content type. Дублирующие эквивалентные Default/Override и ссылки Override на отсутствующую часть отклонять. Default Extension сравнивать без учёта ASCII case. Relations parts имеют type `application/vnd.openxmlformats-package.relationships+xml`.

Найти ровно одну root-связь officeDocument; она должна быть Internal. Поддержать Transitional URI `http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument` и Strict URI `http://purl.oclc.org/ooxml/officeDocument/relationships/officeDocument`. Не полагаться на имя word/document.xml. Main part должна существовать и иметь тип `application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml`. Основная часть DOCM, DOTX, XLSX, PPTX или другого формата — unsupported_package; отсутствие/неоднозначность или External main relationship — invalid_package.

Главный XML должен иметь root document и прямой единственный body в namespace Transitional `http://schemas.openxmlformats.org/wordprocessingml/2006/main` либо Strict `http://purl.oclc.org/ooxml/wordprocessingml/main`. Пустой body допустим. Остальные Word-элементы не преобразовываются и не проходят здесь полную схематическую валидацию.

## Связи и XML

Разобрать все корректно расположенные `.rels`: package `_rels/.rels` либо каталог `_rels` рядом с исходной частью, например `word/_rels/document.xml.rels` для `word/document.xml`. Исходная часть обязана существовать. В каждом наборе Id уникальны, Id/Type/Target непустые, TargetMode отсутствует (Internal) либо Internal/External. Relations не могут быть источником других relations и не должны быть целью Internal-связи. Неизвестные relationship types сохраняются.

Internal target — URI относительно каталога source_part либо путь от корня пакета с начальным `/`. Разрешить нормальные `./` и `../`, пока разрешение остаётся внутри пакета. Отсутствующая цель, выход выше корня, scheme/netloc, query/fragment, backslash и закодированные неоднозначности дают invalid_package. Корректные percent-escape сопоставляются с ZIP-именами; регистр hex-цифр escape и ASCII-регистр имён не создают другую часть. resolved_part содержит фактическое имя найденной части. External target хранится дословно без попытки загрузить/проверить адрес; это не разрешение выполнять его.

Проверять well-formed XML таблицы типов, relations и всех частей с XML media type (application/xml, text/xml или суффикс +xml). Неизвестный XML должен сохраняться без пересериализации. DTD и объявления entities запрещены независимо от кодировки XML; никаких внешних сущностей или загрузок. Корректные UTF-8 и UTF-16 XML допустимы. Ошибка XML/DTD — invalid_package. Бинарные части остаются непрозрачными, но их CRC/размеры проверяются. Не исполнять изображения, вложенные объекты, поля или scripts.

## Ошибки и приёмка

DocxError имеет `code` и непустой постоянный безопасный `message`; str(error)==message. Коды: invalid_input, invalid_package, unsupported_package, package_limit_exceeded. Не возвращать сырое исключение ZIP/XML, пути, XML-текст, имена/targets из входа; скрывать цепочку исходного исключения. Ошибки не создают частичный DocxSource и не меняют вход.

Приёмка использует синтетические пакеты и контрольный DOCX: нестандартная main part, Strict/Transitional, styles/numbering/tables/media/headers/footers/comments/revisions и непрозрачные части. Проверить исходные bytes и все hashes/metadata после открытия и экспорта, каталог связей и отсутствие исполнения External. Отдельно — повреждения, дубликаты/неоднозначности, недостающие части, строгие лимиты и инертные импорты. Parent визуально проверяет контрольный DOCX и экспорт; одинаковые bytes подтверждают только сценарий без правок, не качество будущего редактирования. Проверка Microsoft Word остаётся отдельной, если доступен только другой renderer.

Разрешены `src/ara/docx_package/**`, `tests/docx_package/**`. Не менять другие сервисы, app, БД, миграции, API/ML, зависимости, независимую приёмку, контракт, runner/prompt/статусы/журнал. Общий gate — `bash scripts/check.sh`. Остановиться после D02-01; статус пишет runner.

Основания архитектуры: [Microsoft OPC Parts Overview](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/opc/parts-overview) — часть находится через тип связи и разрешение URI; [Microsoft WordprocessingML structure](https://learn.microsoft.com/en-us/office/open-xml/word/structure-of-a-wordprocessingml-document) — содержимое и оформление распределены по частям; [ECMA-376](https://ecma-international.org/publications-and-standards/standards/ecma-376/) — контейнер и WordprocessingML имеют разные уровни правил. Сохранение оригинальных bytes — техническое решение этого цикла для требования пользователя.
