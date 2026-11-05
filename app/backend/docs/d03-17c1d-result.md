# D03-17C1D — результат проектирования macOS lifecycle

1 ноября 2026, Astra 6 High, по команде Никиты. Основание `0f9b335`, завершённые C1A/B/C. Подготовлены [точный проект C1D](d03-17c1d-design.md), [первый implementation contract D1](d03-17c1d1-contract.md), актуальные ссылки C1/D03-17/очереди. Это **завершённый дизайн**, не работающий macOS supervisor; runtime source/tests не менялись.

Основные решения:

- Engine начинается только после отдельного bootstrap barrier prepared→gate→armed и valid run. Frozen C1C не дополняется несовместимым ACK.
- Только G владеет M. NOTE_EXIT необратимо закрывает возможность будущего сигнала до wait/reap. EPERM/ESRCH/успешный KILL не считаются доказательством cleanup; нужен actual exact wait. Неизвестный PID не используется для остановки.
- Independent guardian контролирует continuous D/L, включая сон. Отдельный control writer не ждёт большого request/reply; все pipes/FDs/bytes/loop work bounded, EOF и физический exit различаются.
- Owner/slot передаются строго по таблице. Slot сохраняется при смерти родителей до выхода child; inherited lock нельзя снимать LOCK_UN. После SQL reconciliation отдельный open/lock проверяет отсутствие holder. Двойной отказ G/S при native hang может оставлять busy: автоматическое безопасное убийство orphan на macOS не заявлено.
- Три bounded реализации: **D1 native clock/locks; D2 guardian/bootstrap/ownership; D3 parent transport и native failure matrix**. Для D1 точные API/errors/path checks/allowed paths/acceptance зафиксированы; D2/D3 freeze делают перед своим кодом на основании выбранной архитектуры.

## Проверка

Native synthetic probe `.runtime/d03-17c1d-design-probe.json`: natural exit0 без сигналов; live TERM→exit-15; ignored TERM→KILL→exit-9; во всех трёх NOTE_EXIT и exact wait, все children завершены. Continuous clock integer conversion с timebase125/3 увеличивается и помещается в signed63. No model/DB/documents/secrets в probe. Это проверка выбранных OS primitives, не реализация guardian и не proof physical suspend/resume. Старый EPERM объясняется возможной zombie race, его точная причина на установленном ядре не утверждается; новый probe не обходил отказ и не использовал alternate kill API.

**`bash scripts/check.sh`:3121 tests +24 subtests passed,76 warnings,646,18s,exit0.** Ruff и format375files прошли; `.runtime/d03-17c1d-design-full-check.log`. Запуск выполнен во время documentation-only проектирования; src/tests не менялись до/во время/после него. Это регрессия существующего кода, не приёмка будущих D1–D3. Новых frozen acceptance в design-cycle нет — freeze/red первого D1 выполняется перед реализацией.

Read-only runtime snapshots `d03-17c1d-design-start-runtime.json`/`-final-runtime.json` совпадают с baseline C1C: main ara_dev V8/schema/counts unchanged; ara_test пуста, временных ara_check0. Содержимое строк/документов не читалось, рабочие данные не мигрировались. PostgreSQL оставлен запущенным. Checked relative links, UTF-8 и git diff --check; changes только собственные design/status docs. Чужие README/specs/untracked материалы сохранены и не включены в commit. Секреты/архив/Word/реальная модель не использовались. Локальный commit, без push/публикации, runner/tasks/progress unchanged.

## Следующий шаг и ограничения

**Сейчас вернуться на Sol 6.1 High и реализовать D03-17C1D1.** Затем без повторного «дальше?» продолжать D2 и D3 отдельными циклами, если не обнаружится новое архитектурное противоречие. Для каждой части обязательны собственный freeze/red, targeted/native/full gate, read-only сохранность БД, result/local commit. Не править старые frozen tests/DDL под новую реализацию.

Дизайн не закрывает runtime/Windows/real pack/suspend acceptance, SQL supervisor C1F, настоящий engine C2, frontend, полноценный DOCX/Word, лицензию или установщики. Основной продуктовый документ не менялся: новых бизнес-решений здесь нет.

Актуальный самостоятельный остаток **30–45 циклов**: прежний28–43 считал C1D одним шагом, точное разбиение на три добавило2. Уже выполненное проектирование повторно не считается. Это рабочая оценка размера независимых циклов, не гарантированный потолок; участие Ани/Артёма отдельно.
