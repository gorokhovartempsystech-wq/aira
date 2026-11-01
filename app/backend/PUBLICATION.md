# Проверенный backend AIRA — передача команде

1 ноября 2026. Снимок локального проекта: `4999b57d725fa749a70ee839aa1ff8d0016db2b6` (D03-17B1). Перенесены все 522 tracked файла: source, migrations, contracts, tests, engineering docs и Ralph harness. Код и тесты совпадают с проверенным снимком. В копии для GitHub удалены ссылки на закрытые сервисы, персональные абсолютные пути заменены переносимыми ссылками; также добавлены входной README, эта инструкция и manifest. Локальные базы, .venv/.runtime, рабочие архивы, output, незакоммиченные материалы и секреты не передаются.

## Проверено

Последний полный gate исходного снимка: `bash scripts/check.sh` — **2704 tests +24 subtests passed**, 75 warnings, exit0, 296,65 секунды. Проверка на macOS с Python3.12/PostgreSQL18; Windows/новый clean clone/desktop installer этим не подтверждены. В отдельной чистой копии с расположением app/backend повторно прошли Ruff/format (337 files) и 476 pure regression tests за2,29 секунды; БД-зависимые tests повторно там не запускались. Основная локальная БД V8 не изменялась; миграции V9 проверены на disposable databases.

- API хранения DOCX, структурная проекция, точечные и абзацные изменения, заголовки/базовые списки.
- Controller для split/join/paste/soft breaks, undo/redo, selection и сохранения/восстановления; это backend без DOM/IME bindings.
- CAS/idempotency, durable checkpoints/pending save/recovery, scoped HTTP API и source-backed downloads.
- Read-only DOCX inventory/final-view/styles/visibility; новый visible-main snapshot и exact подсветка через hidden gaps.
- Strict internal wire `docx-review/1`, проверка engine reply, related evidence/questions/semantic IDs. Fixture обозначен явно, модель в этих tests не запускалась.

## Начать здесь

1. [Текущий продуктовый scope](docs/current-product-scope.md) — выше исторических Linting/Merge/Confluence документов.
2. [Готовые DOCX editor API](docs/docx-editor-api.md).
3. [Последняя проверка visible-main](docs/d03-17a2b2a2b2-result.md) и [review validation](docs/d03-17b1-result.md).
4. [Очередь дальнейших циклов](docs/development-queue.md).
5. [JSON Schema внутреннего review wire](contracts/docx-review-v1.json).

## Разработка

Все команды выполняются **из `app/backend`**, не из корня monorepo:

```bash
cd app/backend
bash scripts/bootstrap.sh
bash scripts/dev.sh
```

Нужны Python3.12/3.13 и зависимости requirements.lock. Ralph harness сохранён как проверенный baseline исходного самостоятельного Git-проекта; его live-запуск внутри monorepo требует отдельной проверки Git-root/allowed paths и этим переносом не объявляется настроенным. Последняя команда запускает только автономный health API на127.0.0.1:8000; установка зависимостей требует сети. Для document API/full tests сначала подготовить project-local PostgreSQL по [инструкции](docs/local-postgres.md), затем `bash scripts/postgres.sh start` и `bash scripts/check.sh`. Runtime Postgres.app/данные в Git не входят; script start не устанавливает PostgreSQL сам. Не запускать alembic upgrade head над чьей-либо существующей рабочей БД без отдельной подготовки. Secrets — только ~/secrets.env, без токенов в репозитории.

## Связь с engine команды

Backend расположен отдельно, **реальная интеграция с текущим engine не выполнена**. B1 проверен по pinned engine036a4e8; main команды на момент переноса353cfee уже содержит новые ML-изменения. В новом engine.review присутствуют `partial` и `checked.pairwise`, отсутствующие в pinned reply. Текущий строгий B1 отвергнет дополнительные поля. Нужен отдельный versioned adapter/contract pass; нельзя просто удалить checks/молча пропустить partial или объявить ответ полным. Root contracts/engine-api.md и engine.schema.json этим переносом не заменяются.

Открыты persistent source/run/attempt/result lifecycle (D03-17B2/B3), supervisor/новый engine adapter, реальный model gate, фильтры/память скрытия, лицензирование, frontend Ани, desktop/платформенная приёмка. Full DOCX readers для сложных элементов/hidden paragraph boundaries/native Word ещё не завершены: сохраняются explicit blockers. Один native read direct gap прошёл, общий Word corpus нестабилен. Исторические /Merge/accounts fixture endpoints не добавляют эти функции в текущий scope.

## Происхождение

VERIFIED-SNAPSHOT.json содержит исходные SHA256/размеры522 файлов и evidence последнего gate. Сам локальный Git history не переносится в историю команды: это additive snapshot под app/backend. Подробные исторические результаты имеют local runtime paths; они не означают, что эти файлы/базы переданы. PUBLICATION.md — текущий входной handoff; исходный README ниже сохранён как история.

## Подготовка документации для GitHub

Из публикационной копии удалены две ссылки на закрытую запись встречи. Сохранены дата, описание встречи и принятые продуктовые решения. Ссылки на файлы проекта сделаны относительными; ссылки на исключённые локальные материалы убраны. Персональный путь в двух исторических task prompts заменён на домашний путь. Исходные документы рабочего проекта не редактировались. Точный список изменённых копий и их SHA256 указан в VERIFIED-SNAPSHOT.json; source_manifest сохраняет исходные отпечатки.
