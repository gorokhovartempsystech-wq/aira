# D03-17E4C1 — effective hide/unhide и явный сброс

3 ноября 2026. [Контракт](d03-17e4c1-contract.md) выполнен. Новый service layer
применяет проверенное соответствие E4B: повторное скрытие уже скрытого finding
не добавляет origin, возврат удаляет все соответствующие aliases. Фильтры и
исходные результаты не меняются. Явный clear снимает все скрытия без decode
результатов, в том числе для восстановления после превышения бюджета resolver.
Ни чтение, ни ошибка не сбрасывают пользовательские решения автоматически.

CAS, atomic receipts, no-op revisions, same-key replay и потеря ACK проверены.
Старый hide после clear возвращает прежнее подтверждение и не скрывает заново.
Clear имеет отдельную каноническую схему; в прежнем parser добавлена только
dispatch-ветвь. Существующие команды и ответы сохраняют байтовый формат.
SQL schema не меняется; prospective workload проверяется до нового hide.

## Проверки

Freeze f2d785d:30 independent cases, red30errors11.85s, targeted30passed14.72s.
4047625 добавил три проверки гонки clear/hide и атомарности удаления всех aliases.
Совместная регрессия **184passed66.92s**; исходные30 test functions и старый codec
после исключения новой dispatch-ветви сохранили AST.

`bash scripts/check.sh`: **4085passed,41skipped,24subtests,74warnings**,
exit0,606.45s. Ruff/format green,553 gate hashes unchanged. Main
`0008_docx_edit_drafts`, schema/counts unchanged; ara_test пустая, temporary DB0.
Артефакты `.runtime/d03-17e4c1-{red,targeted,regression,full}.log`,
`d03-17e4c1-hashes.json`, `d03-17e4c1-runtime.json`.

## Далее

HTTP пока использует прежние exact-source команды. Следующий **E4C2** подключит
effective view/visibility и explicit clear, с отдельным native fixture сценарием.
Только проверенный main-body profile; real ML, frontend и native Word/Windows
release gates не закрыты. Пакет модели отсутствует по ответу Никиты.
Ориентир **18–33 самостоятельных цикла**, E4C1 вычтен один раз. Продолжаем на
выбранной Astra без переключения. Результат локальный, без push/публикации.
