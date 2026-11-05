# D03-17E3 — API постоянных фильтров и скрытия

3 ноября 2026. [Контракт](d03-17e3-contract.md) выполнен в проверенных локальных
fixture-границах. Новый optional review router вместе с analysis supervisor:
preferences GET/POST, explicit finding visibility, конкретный/latest successful
review. Перед выдачей проверяются исходные B2 данные, scope и revision настроек.
Изменение preferences во время decode даёт409; изменение DOCX показывает durable
freshness без переноса старых anchors. Defaults остаются virtual до первой записи.

Сквозной save→check→hide→new app→show hidden→unhide прошёл, в том числе с native
macOS child fixture. Старые raw result routes и модельный запрос не меняются.
HTTP команды подтверждают COMMIT200 и возвращают исходный receipt при повторе;
прежний ack не откатывает новое решение. Общий nonwaiting gate2 ordinary+1Stop
сохранён, два review reads не блокируют Stop. Bootstrap owns migrations/processes;
V12 остаётся совместима с D, review требует13 без auto-upgrade.

## Проверки

Freeze4d04491; red1failed+17errors5.83s. Первичная приёмка18passed9.08s.
Дополнениеc3018ac:8 independent ownership/locator/latest/hash checks; все исходные
functions/assertions AST сохранены. Совместная регрессия **136passed95.71s**.

`bash scripts/check.sh`: **3974passed,41skipped,24subtests,78warnings**,
exit0,562.90s. Ruff/format green;539 gate hashes unchanged. Из прежних533 файлов
изменены только разрешённые installer hook и HTTP matcher; E1/E2/schema/old tests
сохранены. Main `0008_docx_edit_drafts`, schema/counts unchanged; ara_test пустая,
временных databases0. Логи `.runtime/d03-17e3-{red,targeted,regression,full}.log`,
`d03-17e3-hashes.json`, `d03-17e3-runtime.json`.

[Handoff для frontend](docx-review-api.md). Дальше E4 pure conservative remapping,
затем persistent integration и сквозная приёмка после edit. Реальный ML отсутствует
по ответу Никиты; frontend Ани и native Word/Windows release gates не закрыты.
Ориентир оставшейся самостоятельной очереди **20–35 циклов**, требует уточнения
после reader/desktop integration; на выбранной Astra продолжаем без смены режима.
