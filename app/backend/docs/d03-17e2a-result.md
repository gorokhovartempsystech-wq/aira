# D03-17E2A — схема постоянных фильтров и скрытия

3 ноября 2026. Завершён schema цикл по [контракту](d03-17e2a-contract.md).
V13 добавляет только preferences, active dismissals с scoped ссылкой на исходный
результат, small command receipts. Canonical filters/UUID/hash shapes/counters/
finite timestamps/FK/unique constraints проверены. Старые таблицы/история не
меняются, новых initial rows нет. Main автоматически не мигрируется.

Downgrade блокирует3таблицы и отказывает при любых сохранённых настройках/
решениях/receipts; writer commit/rollback перепроверяется после lock. Неудачный
дальнейший downgrade к V11 также откатывает удаление пустых review tables.
Supervisor принимает только совместимые V12/V13;10/11/unknown future по-прежнему
recovery_required. Ни lifecycle, ни native handling, ни timeout правила не менялись.

## Проверки

Freeze `b4933d2`: новая независимая приёмка и **только подготовка** исторического
V12 файла до source. Red:3failed+28errors+3passed4.65s (V13 ещё отсутствовала).
Targeted schema+historical V12+HTTP/native **84passed60.76s**.

`bash scripts/check.sh`: **3908passed,41skipped,24subtests,76warnings**,
exit0,520.35s. Ruff/format green.527 gate hashes unchanged. Из525 предыдущих
файлов изменены только разрешённые models append-only, supervisor version gate и
подготовка test_docx_analysis_continuous_timeout. Все прежние ORM определения
побайтово сохранены; все исторические assertions AST-identical. Не приписываем
Никите отдельное согласование строк: изменение входит в заранее зафиксированный
контракт автономного следующего цикла, а не подгонку проверок после failure.

Main остаётся `0008_docx_edit_drafts`, schema/counts неизменны; ara_test пустая,
временных databases0. Логи/снимки `.runtime/d03-17e2a-{red,targeted,full}.log`,
`d03-17e2a-hashes.json`, `d03-17e2a-runtime.json`.

## Следующее

E2B — scoped read/CAS write/hide/unhide и идемпотентные receipt, затем E3 HTTP,
E4 перенос при изменении source. Таблицы сами по себе не доказывают сохранение
скрытия в пользовательском UI. Пакет ML, frontend/Word/Windows release gates
остаются отдельными. Ориентир самостоятельной очереди **22–37 циклов**;
продолжаем на выбранной Astra без остановки на смену режима.
