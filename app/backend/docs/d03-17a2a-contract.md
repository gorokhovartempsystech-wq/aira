# D03-17A2a — инвентаризация всех частей DOCX

1 ноября 2026, Sol 6.1 High; после A1 `9ea40c5`. F06/F11, расширение покрытия по D03-17. Прямое разрешение Никиты продолжать автономно, локальные commits без push. Согласованные сегодня policy: читать итоговый текст revision markup без изменения package; комментарии сохранять, но не анализировать. Решение записано в current-product-scope.md, не требует повторного вопроса.

Одна задача: pure metadata inventory частей/отношений валидированного package. Не извлекать новые stories, не менять A1 projection/profile/coverage/map_span и не заявлять полное покрытие. Не читать/переписывать XML для принятия правок, не фильтровать A1 notices по новому inventory. Unknown остаётся unknown; один MIME type не доказывает отсутствие вложенного текста/поддержку reader.

Allowed: новый `src/ara/docx_analysis/inventory.py` с helpers при необходимости под именем `_inventory*.py`, `src/ara/docx_analysis/__init__.py` только новые exports; новая frozen `tests/acceptance/test_docx_analysis_inventory.py`, own `tests/docx_documents/test_analysis_inventory*.py`; current-product-scope.md только прямое новое решение/дата, d03-17-design.md только policy/статусы/ссылки, development-queue.md и d03-17a2a-result.md. Никаких прежних source/test/fixtures/schema/DB/dependencies/runner/tasks/progress/AGENTS изменений. Main не мигрировать; секреты/архив не читать. Contract+новая приёмка freeze до implementation; red→targeted→full scripts/check.sh→baseline→result/local commit. Frozen приёмку не менять без конкретного разрешения.

## API и DTO

`inventory_docx(data: bytes, *, source_sha256: str, limits: InventoryLimits | None=None) -> DocxInventory`. Exact bytes, lowercase64hex hash; exact InventoryLimits/None. Defaults: max_parts4096, max_relationships10000, positive exact int, inclusive. Неверный тип/limits/hash form — InventoryError.invalid_input; mismatch — source_mismatch; превышение собственных limits — inventory_limit_exceeded. Messages статичны, без исходника/URL/пользовательских аргументов. Перед hashing/parser действуют неизменные default DocxLimits archive32MiB; остальные package errors проходят как прежний безопасный DocxError. Никаких caller-controlled package limits. Получить источник через существующий open_docx(data), не доверять переданным inventories/DocxSource. После валидации проверить counts до создания новых output collections. Внутренний reader уже ограничен package budgets; новый limit не обещает streaming admission до его выполнения.

Frozen/slotted DTO, tuple collections, никакой исходной ZIP/XML/DocxSource в output:

- AnalysisPolicy: version=`docx-analysis-policy/final-no-comments-v1`, revisions=`final`, comments=`preserve_exclude`. Все три поля init=False: публичный выбор политики этим API не предоставляется.
- InventoryPart: name, content_type (nullable), size_bytes, sha256, category, disposition.
- InventoryRelationship: source_part, relationship_id, relationship_type, target_mode, resolved_part(nullable). **Не хранить target URL/raw target**, не открывать external links; External resolved_part=None, Internal уже разрешён исходным package validator.
- DocxInventory: source_sha256, size_bytes, main_part, policy, parts, relationships. Нет complete/ready/checked/successful-analysis поля.

Parts в exact ordinal name order существующего source.entries, все non-directory entries включаются ровно раз, даже orphan/unreferenced. Relationship order (source_part,relationship_id), без обхода только достижимых от main. Part hashes/sizes — точные исходные metadata. Policy — информация будущему reader, не утверждение выполненного принятия правок. Поля с произвольными package metadata strings и содержащие их агрегаты repr=False; static category/disposition и counts/hash не содержат текст документа. Импорт/API не читают env/файлы/сеть/БД, не пишут logs; стандартная загрузка Python-модулей разрешена. Оригинальные bytes неизменны.

## Точная классификация, без вывода по имени файла

Main определяется source.main_part, а не word/document.xml. [Content_Types].xml (casefold name, content_type=None) и RELS_TYPE=`application/vnd.openxmlformats-package.relationships+xml` → package_metadata/metadata.

Для остальных совпадения MIME exact, неизвестные/case variant/параметризованные остаются unknown. Только metadata classification, не content/schema conformance.

| MIME/условие | category | disposition |
|---|---|---|
| source.main_part | main_body | requires_reader |
| `application/vnd.openxmlformats-officedocument.wordprocessingml.{header,footer,footnotes,endnotes}+xml` | соответствующее header/footer/footnotes/endnotes | requires_reader |
| тот же prefix + `document.glossary+xml` | glossary | requires_reader |
| тот же prefix + `comments+xml` | comments | preserve_excluded |
| тот же prefix + `{styles,numbering,settings,webSettings,fontTable}+xml` | auxiliary | metadata |
| application/vnd.openxmlformats-officedocument.theme+xml | auxiliary | metadata |
| application/vnd.openxmlformats-package.{core-properties,custom-properties}+xml | auxiliary | metadata |
| application/vnd.openxmlformats-officedocument.extended-properties+xml | auxiliary | metadata |
| image/png, image/jpeg, image/gif, image/bmp, image/tiff, image/x-emf, image/x-wmf, image/svg+xml | image | requires_media_accounting |
| всё прочее, в том числе charts/embedded docs/custom XML/unknown binary | unknown | requires_reader |

Имя header*.xml/image*.png не является основанием классификации. Orphan comments всё равно учитываются; glossary — потенциальный текст, не auxiliary. Image category не разрешает пропустить caption/textbox/SVG text; OCR по scope исключён, но учёт видимого текста требует отдельного reader. Unknown relationship types учитываются в metadata без загрузки target и не делают package безопасным для анализа. Inventory не заменяет future coverage gate и не удаляет notices.

## Приёмка

Точный список всех parts/links (включая orphan, custom main, Strict/Transitional packages), metadata equality с package bytes и hashes, стабильный порядок/повтор, MIME matrix и misleading filenames. Нет source ZIP/XML/URL в DTO/repr. External HTTP/file targets инертны, resolved_part=None; local relative targets разрешены существующим validator. Exact policy values/frozen fields, A1 snapshot неизменен и по-прежнему incomplete при stories. Strict types/hash/sizes/limits, inclusive/+1 counts, count всех parts/links включая неизвестные, malformed package/relationships и oversize отвергаются. Subprocess import/build при запрете env/file/network/DB подтверждает inert API, без upstream/ML imports. Targeted и полный gate; реальный ML/новый Word render не нужен, bytes не экспортируются заново.

Следующий этап — не «поддержка всего Word» одним commit. Нужен отдельный технический дизайн reader final-view и story coverage/source mapping, затем маленькие contracts/fixtures по структурам; не ослаблять A1 ради согласованной новой policy.
