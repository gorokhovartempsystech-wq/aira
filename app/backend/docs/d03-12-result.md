# D03-12 — заголовки и native списки DOCX

31 октября 2026. Выполнен отдельный backend-цикл F05/F11 по [контракту](d03-12-contract.md). Режим Sol 6.1 High. Frontend Ани и проверочный workspace не менялись.

## Поведение

Чистый API ara.docx_package.formatting атомарно задаёт прямой paragraph style и список выбранных body paragraphs по точным source anchors/expected_text. Существующие стили выбираются по реальным ID, без создания или переименования стилей импортированного документа. Для AIRA доступны Title/Heading1–3/Normal/ListBullet/ListNumber; None убирает прямой style. Другие pPr properties и весь run XML остаются исходными.

Native bullet/decimal numbering: новые соседние абзацы получают общую последовательность, пропуски разрывают её с новым стартом 1, явный list_id продолжает проверенную последовательность. Учитывается level-0 override; несоответствие вида, неоднозначные определения или наследование numStyleLink отклоняются. Новый numPr вставляется в порядке OOXML, новые abstractNum/num — до соответствующих следующих definitions/cleanup. Старые definitions сохраняют точные bytes. Изменяются только main и при необходимости numbering part; styles и прочие parts не меняются.

Поддержаны UTF-8, UTF-16 LE/BE, Strict WML и selfclosing containers с сохранением attributes. No-op возвращает точный исходник после проверки ссылок. Настоящие изменения проходят прежние protection/settings/signature/range/opaque gates. Неопределённые, чужие и устаревшие anchors, дубликаты и несовпадение текста дают безопасную ошибку всего batch. Лимиты auxiliary nodes/depth проверяются до lexical allocation. API не обращается к файлам/сети/БД/секретам и не логирует текст.

## Проверки

Подготовка **51b9c20**: контракт и frozen acceptance до реализации. Красный прогон **23 failed**, 0,22 секунды. Frozen acceptance не менялась. Дополнительно 12 cases на Strict/UTF16, отсутствующую/повторную relationship, effective list override, numStyleLink, точный pPr ordering/run bytes, aux depth/ID exhaustion, selfclosing numbering и cleanup order.

Целевой прогон с прежней структурной приёмкой: **77 passed**, 0,37 секунды. Общий `bash scripts/check.sh`: **1657 passed, 24 subtests passed**, 67 предупреждений, **162,72 секунды**, exit 0. Ruff и format прошли, старые проверки не ослаблены и не пропущены. Логи .runtime/d03-12-red.log, d03-12-targeted.log, d03-12-full-check.log. Source после полного gate не менялся.

Визуальный QA через новый API: 13 synthetic paragraphs, Title и три уровня заголовков, bullet, numbered 1/2, отдельный restart 1 и продолжение первой последовательности 3. Все исходные тексты совпадают, пять нетронутых частей побайтово прежние. Экспорт **3449 bytes**, SHA256 `f1a0b6e6c5bb62fca6ea6391ee2da34a27acca8030deb152bec54c047b4cf8a2`. Bundled renderer 26.1026.10807: одна страница просмотрена целиком, маркеры/иерархия/отступы читаемы, обрезаний и наложений нет. Microsoft Word отдельно не запускался.

## Ограничения и следующий цикл

Это pure backend, без HTTP/UI/БД. Только body paragraph и уровень списка 0; styles/numbering parts должны уже существовать с единственной корректной internal relationship. Не поддержано разрешение наследования numStyleLink, списки внутри ячеек, произвольное редактирование сложных/защищённых элементов Word. Это не заявление о полной готовности DOCX-редактора.

Минимальная private refactor structure/_package.py позволяет переупаковать несколько проверенных parts; прежний публичный repack и все D03-11 tests сохранены. Dependencies/runner/tasks/progress/инструкции/чужие dirty-файлы не менялись. Секреты и пользовательский архив не читались.

Итоговый снимок схемы/ревизии/счётчиков совпал с baseline; ara_test пуста, временных ara_check_* нет. PostgreSQL оставлен запущенным для D03-13. После локального коммита — отдельный контракт атомарных HTTP-команд с CAS/idempotency и handoff для frontend, по прямому разрешению Никиты продолжать циклы самостоятельно.
