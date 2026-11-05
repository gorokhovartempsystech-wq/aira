# D03-17 — результат проектирования анализа DOCX

31 октября 2026, Astra 6 High, исходный HEAD `3060014`. По команде Никиты после смены режима выполнено проектирование следующей связки редактора и локальной модели. Изменены только четыре документа: [дизайн](d03-17-design.md), [контракт D03-17A1](d03-17a1-contract.md), этот результат и development-queue.md. Поведение приложения этим циклом не изменялось; реализация ещё не начата.

## Принятые технические решения

- Анализ привязан к конкретному подтверждённому SavedTarget. Неизменяемые bytes, storage revision и SHA остаются с запуском; изменение документа делает прежний результат stale, не переносит подсветку поиском похожей цитаты.
- Собственный snapshot сохраняет точные paragraphs/spans/Word anchors и Unicode code-point offsets. Coverage отдельно учитывает opaque/unsupported содержимое. Нельзя показывать полный успешный анализ при непроверенных частях файла.
- Новые namespaces/таблицы/wire contract не переписывают прежний Markdown/fixture/worker0.1. Запуск идемпотентен; один active run на документ; пять минут включают очередь, подготовку, загрузку модели и публикацию. Cancel/deadline/lease fences исключают позднюю публикацию, при сбое БД local stop тоже прекращает owned child.
- Отдельный процесс модели получает bounded JSON через закрытые pipes. Upstream HTTP/token/parse_file не используются. Точные token guards запрещают скрытое обрезание; ответ проверяется целиком, включая spans/quotes/ссылки на фрагменты.
- Скрытие хранится отдельно от неизменяемого результата. Повторное скрытие опирается на полное evidence/model/profile; между версиями допускается только однозначное консервативное сопоставление. Фильтры первоначально меняют представление, движок возвращает полный поддержанный результат.

Это технические решения проекта, не добавление Merge/impact/автофикса/ISO/аккаунтов/Confluence или обещание полного качества анализа. Продуктовый scope не редактировался.

## Проверенные основания

Прочитаны текущий scope, сохранение/registry/wire handoff, projection и старые analysis/worker contracts. Использован ранее полученный локальный снимок Артёма `036a4e89027276144c51de14f0cc91412c59f437`; удалённый main в этом цикле повторно не проверялся. SHA256 engine.py: `b43c2727fa69f242a521e105dc83f9df865d9bf2cd4f91619843c420d1044e8f`.

Узкий audit извлёк из AST только просмотренные pure static methods parse_text/guess_status/guess_type, без импорта модуля/ONNX/HTTP. Синтетический ввод из heading, короткой строки и полного предложения дал один fragment вместо трёх непустых строк. В исходнике подтверждён enable_truncation(256). Rich DOCX fixture дал notices unprojected_part/unprojected_story/unsupported_element, то есть main-body projection не доказывает полное покрытие Word. Отчёт `.runtime/d03-17-design-audit.json`; это не запуск модели и не измерение её качества. Секреты/пользовательский архив не читались, upstream repository не менялся.

Полный `bash scripts/check.sh`: **2301 passed + 24 subtests passed**, **76 warnings**, **288,87 секунды**, exit0. Ruff и format прошли, 285 файлов уже отформатированы. Лог `.runtime/d03-17-design-full-check.log`. Новые tests не добавлялись: red/freeze для A1 выполняет следующий implementation cycle до source, его будущие критерии не выдаются за уже проверенное поведение.

Read-only baseline до/после совпал целиком: schemas/revisions/counts неизменны, main ara_dev остаётся V8 `0008_docx_edit_drafts`, ara_test пуста, temporary databases0. Отчёты `.runtime/d03-17-design-start-runtime.json` и `.runtime/d03-17-design-final-runtime.json`. Source/tests/БД/schema/dependencies/runner/tasks/progress не менялись, чужие рабочие изменения сохранены. Git diff whitespace check и локальные ссылки проверены. Документы сохраняются отдельным локальным коммитом без push; PostgreSQL оставлен запущенным.

## Следующий цикл и ограничения

**Вернуться на Sol 6.1 High для D03-17A1.** Контракт задаёт public API, immutable DTO, exact extraction, canonical digests, budgets, coverage, span mapping, безопасные ошибки, разрешённые файлы и семь групп приёмки. Первый шаг — отдельно зафиксировать новую приёмку, получить red, затем реализовать pure snapshot. Никаких SQL/HTTP/ML/UI в этом шаге.

Дальнейшие A2/B/C/D/E/F разбиты в дизайне; каждому нужен собственный точный контракт до кода. Реальные weights/manifest/tokenizers и benchmark, comments/tracked-changes policy, дополнительные DOCX stories, native process lifetime Windows/macOS, frontend Ани, F02 bootstrap/установщики и лицензирование остаются. Отсутствие weights по разрешению Никиты блокирует только зависимый real inference/benchmark. Смена режима рекомендована на границе законченного дизайна; runner task вручную не закрывался.
