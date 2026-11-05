# D03-17C1E4 — реализация по готовому контракту

**Уточнение 3 ноября:** после описанного запроса на одну строку ожидания Никита дал команду «продолжи». Добавлено предложенное ожидание освобождения command cell в `test_renew_full_receipt_and_busy_control_independent_of_request`. Проверка Ruff также потребовала упорядочить две существующие import строки в native test того же файла; выполнено только форматирование. Все assertions, тайм-ауты и source неизменны. Остальные frozen tests по-прежнему не разрешено менять. Завершающие проверки и статус — в [результате E4](d03-17c1e4-result.md).

2 ноября 2026, Sol6.1 High. [Контракт E4](d03-17c1e4-contract.md) реализуется без расширения source paths: шесть перечисленных новых modules. Стартовая основная БД совпала с design final, E1–E3 unchanged. Новая acceptance использует реальные три threads, strict synthetic endpoint/process owners, controlled clock и barriers. Native fixture matrix13cases требует Windows.

Workers используют bounded timed Condition waits: control<=5ms во время pending delivery, pump<=10ms, launch<=50ms. Это wakeups для nonblocking E2 poll, не busy spin и не clock authority; no native event ждётся чужим thread. В actor state нет callbacks/IO/codec под metadata mutex. API imports инертны. Frozen Mac и E1–E3 не меняются.

До source выполнены collection42cases, проверка подготовки synthetic/native helpers и Ruff/format. Исходный red:29errors/13native skips из-за отсутствующего `windows.driver`,0,22s; лог `.runtime/d03-17c1e4-red.log`. Acceptance фиксируется отдельным локальным commit до исходников. Дальнейшие новые own tests разрешены, frozen acceptance не редактировать без согласования. Native Windows/recovery/weights gates остаются открыты; result должен различать available и environment результаты.
