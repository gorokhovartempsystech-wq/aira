# D03-16D — вход для архитектурной проверки runtime

Архитектурный проход выполнен 31 октября на Astra 6 High: решения в [d03-16d-design.md](d03-16d-design.md), первая реализация в [d03-16d1-contract.md](d03-16d1-contract.md). Ниже сохранён исторический вход; его предложения не конкурируют с принятыми решениями. В частности, выбран registry open sequence вместо одного checkpoint fence, recovery open не делает save, точные D3 границы разделены на A/B. Далее Sol 6.1 High.

31 октября 2026, после 9520da0, Sol 6.1 High. Это передача к следующему проектному проходу, не новый продуктовый scope и не готовый контракт реализации. D1 не начат. D03-16A/B1/B2A/B2B/C1/C2/C3A/C3B завершены, последний gate 2086 tests + 24 subtests. F05/F06/F11/F12 и d03-16-design.md остаются основанием. Runner/tasks/progress не менять.

Оценка режима уточнена перед D: один bounded проход **Astra 6 High** для проверки runtime state/lock/publication contract; затем реализация на **Sol 6.1 High**. Прежняя строка Sol для D относится к реализации. Основание — соединение независимых durable transactions с mutable RAM controller, а не необходимость переписать уже проверенный storage. Пользователь разрешил останавливаться после завершённого цикла при необходимости смены режима.

## Что уже доступно

- EditorSession.restore восстанавливает exact bytes/selection, saved digest и dirty, но создаёт revision0/position0 и пустую историю. Старый origin остаётся provenance, не действующей command identity.
- checkpoints.get/put/discard — постоянный монотонный slot, scope/CAS/legacy arbitration. get создаёт empty slot, если его ещё нет. Нет автоматического rebase/merge.
- save_prepare.prepare_save — immutable durable pending. SaveHandle содержит полный fingerprint payload, а не только четыре старых поля проекта.
- save_commit.commit_save — current+receipt атомарны, pending остаётся. Receipt replay не читает checkpoint и может вернуть более новый current отдельно.
- save_finalize.get_save_status/finalize_save — matching receipt/current, full control proof, clean working checkpoint. Completed replay может вернуть current_matches_receipt=false.
- save_reconcile.reconcile_save — две независимые transactions commit→finalize, полная input validation перед первой записью. discard_pending — явная очистка без rollback current, save_confirmed=false не доказывает отсутствие commit.
- CP MAX guard резервирует finalize; обычный get/status/доказанный replay не должен менять истощённый counter.

Прочитать contracts/results этих подциклов и source перед новым контрактом. Рабочая ara_dev всё ещё V8; V9 проверена только на disposable DB. Не мигрировать рабочие базы автоматически.

## Решения, которые нужно проверить до D1

1. **RAM publication и неопределённый save.** Точная таблица состояний для prepare ACK-loss, commit ACK-loss, finalize ACK-loss, DTO failure и foreign writer после подтверждения. Кандидат EditorSession и ответ готовятся до публикации. Pending должен удерживать исходные command/prepare/operation/finalize IDs и private SaveTarget; capture/undo/edit блокируются до reconcile. Статус conflict важнее dirty=false. Не считать исключение доказанным rollback и не mark_saved по одному равенству digest.
2. **Recovery target.** После restart новый session_id и локальная revision0 должны связываться с historical pending без повторного редактирования. Old origin.session_id/session_revision/position_id не сравнивать с новым target как с одной эпохой. Определить, открывается ли pending frozen без записи или recovery сначала выполняет reconcile; не смешивать read-open с неявным сохранением. Чужой current не перезаписывать.
3. **Scope и lock order.** Cached snapshot/команда обязаны повторно проверять project ownership и document scope. Не держать внешний SQL document FOR SHARE во время вызова C1/C2/C3 через другую connection: это создаёт self-deadlock с FOR UPDATE. Для RAM-команды проверить вариант brief scoped read transaction, приготовить reply/candidate, завершить read transaction, затем publish; определить точку авторизации и поведение отказа commit. Index lock не должен ждать actor lock или SQL; actor mutex и heavy semaphore получают единый порядок.
4. **Ordering/replay.** Зафиксировать строгие command_id/expected_sequence/expected_session_revision, canonical fingerprint, latest-result replay и stale superseded command. Capture/no-op увеличивают sequence, не обязательно core revision. Незавершённая команда занимает одну identity; reconcile продолжает её без второго increment. Определить strict overflow и scope-before-expired, ограниченный cache без текста/истории replies. Не хешировать произвольные callables/private method names.
5. **Open/close lifecycle.** client_open_id повторяет live open без сброса состояния, но не воскрешает закрытый controller и не требует бесконечного tombstone cache. Проверить предложение: open имеет observed expected_checkpoint_revision и режим current/recover, close всегда подтверждает checkpoint, даже для чистого файла, тем самым fence-ит старое open. Проверить races одного ID, двух окон, close ACK-loss, нового current и legacy draft. Не выдавать 410 за доказательство потери/сохранения работы.
6. **Retained budget.** 8 actors/256 MiB compressed retained packages, per-session 128 MiB/100 states, 1 heavy operation. Учёт union live+candidates по object identity immutable bytes, без двойного счёта одной ссылки; отказаться без eviction dirty/pending. Public snapshots показывают только depths: выбрать ограниченный private introspection в EditorSession вместо доступа к его mutable internals извне. Временные XML/projection buffers не входят в обещание compressed budget; RSS потребует отдельного benchmark. Candidate failure освобождает reservations.
7. **Будущий HTTP boundary.** Python controller не принимает произвольный DOCX setter и не выдаёт BLOB/base64 в JSON. Canonical fingerprint больших paste нужно считать после строгой проверки и без смешения 8 MiB wire body с размером ensure_ascii JSON: 1M non-BMP code points расширяются до 12 MiB при escaped representation. Проекции сериализовать явно, не dataclasses.asdict(DocxSource), содержащий original bytes. Check/Export должны использовать точный сохранённый candidate/receipt, не новый GET latest.

Это варианты для проверки, а не дополнительные согласованные бизнес-правила. Результат прохода: выбрать конкретные signatures, state transitions, lock/resource protocol и разрешённые пути; зафиксировать границы и frozen acceptance следующего цикла до кода. Менять критерии прошлых подциклов не требуется.

## Предложенное разбиение реализации после review

- D1: scoped registry, current/recovery open, epoch/snapshot, admission и lifecycle foundation; без всех edit commands сразу.
- D2: bounded native command adapter, ordering/idempotency, atomic fork/reply/publication и общая история.
- D3: durable checkpoint/save/reconcile/close bridge, ACK-loss/private SaveTarget и resource cleanup.
- E: отдельные bounded HTTP/wire contracts, ручная serialization, routes и handoff для Ани. Не переписывать её frontend. UI timer/IME/клавиши и Windows/macOS gate остаются отдельными проверками.

Каждый цикл получает свой контракт и red→implementation→targeted→полный bash scripts/check.sh→result/local commit. Это предложение границ; архитектор может уточнить их до freeze, сохраняя scope. Реальный ML запуск пока пропускается до весов Артёма; лицензирование/desktop не включать в D.
