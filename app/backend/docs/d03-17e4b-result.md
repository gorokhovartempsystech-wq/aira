# D03-17E4B — действующие скрытия для нового результата

3 ноября 2026. [Контракт](d03-17e4b-contract.md) выполнен: scoped V13 capture
активных origin references, повторная B2/E4A проверка вне SQL locks, effective
current keys и все aliases одного finding. Чтение не создаёт preferences, не
меняет revision/решения/receipts и не запускает анализ. После decode повторно
проверяются scope/preferences; для будущего writer добавлен exact recheck всех
origin bundles/refs. Новое текущее содержимое не подменяет pinned target.

Corrupt source/request/reply/result/manifest, ложный finding/key и hash-correct
подмена metadata дают безопасную ошибку. Финитные origin/byte/text бюджеты
проверяются до дополнительных blobs/парных decode; нет частичного успеха или
молчаливого пропуска origins. Несколько старых решений могут дать один current
key: сохраняются все aliases для будущего полного unhide.

## Проверки

До freeze отдельно проверена подготовка B3 synthetic saved-target/result данных:
1passed1.21s на disposable DB. Freeze91bb036:28 tests, red1failed+27errors6.26s;
targeted28passed14.20s. d329e0e добавил5 independent budget/metadata/corruption
checks. Последующая Ruff-правка только переносит2 SQL literals и разделяет imports;
весь AST сохранён. E4B/E4A/E2B/E1 regression **151passed43.37s**.

`bash scripts/check.sh`: **4052passed,41skipped,24subtests,78warnings**,
exit0,583.35s. Ruff/format green;549 gate hashes unchanged; все544 прежних
source/tests/config files сохранены. Main `0008_docx_edit_drafts`, schema/counts
не изменились, ara_test пустая, временных БД0. Артефакты
`.runtime/d03-17e4b-{preparation,red,targeted,regression,full}.log`,
`d03-17e4b-hashes.json`, `d03-17e4b-runtime.json`.

## Далее и ограничения

Resolver ещё не подключён к HTTP/view или mutation. Ограничен текущим проверенным
main-body profile и conservative E4A; полного Word/реального ML не объявляем.
При накоплении64+ origins/большом workload возможен413 preferences_resolution_limit.
До HTTP wiring необходим explicit recovery без source decode: снять все скрытия
документа с CAS/receipt, сохранив фильтры и исходные результаты.

Следующие отдельные циклы: **E4C1** effective hide/unhide + explicit clear + receipt
compatibility, затем **E4C2** HTTP/presentation integration. Прежний ориентир
**19–34 самостоятельных цикла** пока сохраняется: E4B завершён (-1), интеграция E4C
разделена на два проверяемых шага (+1), новых ML/Word функций не добавлено.
Выбранная Astra; продолжаем без смены режима. Пакета модели нет по ответу Никиты,
frontend Ани и native Word/Windows release gates остаются внешними.
