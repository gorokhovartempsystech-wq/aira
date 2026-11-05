# D03-16D — runtime редактора, команды и публикация сохранения

31 октября 2026. Архитектурный проход на Astra 6 High после 6a091ef. Основание: F05/F06/F11/F12 current-product-scope.md, d03-16-design.md и реализованные A–C3B. Этот документ уточняет только runtime-часть прежнего технического проекта; продуктовый объём не меняется. Код D ещё не реализован. Входные вопросы d03-16d-review-brief.md закрываются решениями ниже.

## 1. Владение и публичные границы

Новый пакет `ara.docx_editor`. `EditorRegistry(runtime: DocumentRuntime, *, limits: RegistryLimits | None = None)` создаётся явно на lifetime приложения. Один registry связан с одним engine/user/project/local mode; сохраняет проверенную копию контекста, не читает настройки. Другой scope — другой registry. Пока не менять frozen DocumentRuntime. Application wiring — в E. Singleton, фоновых потоков, I/O при импорте/конструировании нет.

Registry имеет новый случайный `registry_id`, монотонный `open_sequence` (сначала 0), индекс живых actors по (document_id, session_id), индекс открытий по client_open_id. Session ID случайный и новый при каждом свежем открытии, включая recovery. Native EditorSession никогда не отдаётся caller и не принимается извне; произвольного setter DOCX нет. Доступны detached DTO, операции и ограниченный binary snapshot.

Actor хранит immutable published state: EditorSession, command_sequence, base storage revision/hash, известную checkpoint revision, latest command receipt, active durable attempt или recovered pending. Отдельный mutex принадлежит actor. Published EditorSession больше не мутируется: операция выполняется на `copy(EditorSession)`, методы которого уже копируют trusted core и заменяют immutable state. Нужен тест неизменности старой копии для каждого адаптированного intent. Не использовать deepcopy всего package/history.

`RegistryLimits` — strict frozen/slotted record: max_sessions=8, max_retained_bytes=268435456; положительные int без bool. Тяжёлая операция одна, это фиксированный semaphore, не caller option. Per-session SessionLimits остаются defaults 100/134217728, package/projection limits прежние. Нельзя передавать увеличенные limits пользовательским запросом.

## 2. Чтение recovery и открытие

`inspect_recovery(document_id)` — read-only: возвращает registry_id/open_sequence, DocxSummary и проверенные метаданные slot (revision 0/phase absent, если строки нет), working digest/size/selection/origin и классификацию pending при наличии. Не создаёт slot, не сохраняет current, не очищает draft. Pending receipt/current/checkpoint читаются под ОДНИМ project→document FOR SHARE transaction; нельзя соединять get_checkpoint и get_save_status из разных transactions как один согласованный снимок. Использовать существующие `_record`, `_legacy`, `_committed`, `_matches` с полным validation; новый read adapter не меняет их правила. Stored corruption — безопасная 500 без cleanup.

`open(document_id, *, registry_id, client_open_id, expected_open_sequence, expected_checkpoint_revision, mode)` принимает exact UUID, counters 0..MAX и mode current/recover. Для fresh open:

1. Scope проверяется до раскрытия registry/session existence. Registry ID должен совпасть, expected_open_sequence == текущий open_sequence и < MAX. Проверить capacity до загрузки пакетов.
2. Прочитать согласованный checkpoint/current. current разрешён только для empty/absent; recover — только working/pending. Несовпадение observed checkpoint revision -> checkpoint_conflict. Не замалчивать существующий draft открытием current.
3. Open при absent может вызвать существующий get_checkpoint, который создаёт empty1. Ожидание 0 допускает только untouched empty1 (last_request_id/hash NULL); повтор чтения делает полученный slot актуальным основанием. Чужой working/pending/empty revision>1 отвергается. Сбой initialization не публикует actor; пустой slot не означает пользовательской правки.
4. empty -> EditorSession(current). working -> restore(working, saved_sha256=base, selection). pending -> тот же restore, плюс проверенный SaveHandle из checkpoint; open НЕ делает commit/finalize. Восстановленная history пуста, core revision/position0. Новый session_id не равен historical origin. Working с чужим base и pending с чужим current открываются как conflict для сохранения доступа к своей копии; не выдаются за editable/current.
5. Приготовить весь ответ, проверить бюджет, затем атомарно добавить actor и mapping, open_sequence+1. Ошибка до publication не расходует sequence/client ID/capacity. Original/current transient из SQL не удерживаются actor.

Повтор live client_open_id с теми же исходными аргументами возвращает тот же actor и его ТЕКУЩИЙ snapshot; не сбрасывает selection/history. Altered аргументы -> idempotency_conflict после scope check. Сравнить replay ДО проверки текущего open_sequence: за это время могли открыться другие документы. Response содержит accepted_open_sequence и текущий next_open_sequence.

**Уточнение прежнего проекта: добавлен registry_id/open_sequence на open.** Одного checkpoint fence недостаточно для закрытия конфликтной вкладки без записи чужого slot; бесконечный cache закрытых IDs тоже неприемлем. После удаления live mapping старый expected_open_sequence меньше текущего -> stale_open. Новый процесс отвергает старый registry_id (410 editor_registry_expired); клиент перечитывает recovery и делает новый open. Никакая старая команда автоматически не переносится. Коллизии одновременных свежих открытий дают stale_open проигравшему; клиент заново читает sequence, использует новый client_open_id. Это редкая операция, глобальная координация вводимого текста не появляется.

## 3. Snapshot, scope и внешний writer

`snapshot(document_id, session_id)` возвращает fresh detached EditorView, не меняет editor/sequence и не создаёт checkpoint. Проверить scope даже для cached/open replay/unknown session. Нет actor при существующем доступном документе ->410 editor_session_expired; чужой/удалённый документ ->404. Между первым lookup и получением mutex scope проверяется снова перед ответом.

Для live snapshot/RAM operation нужен лёгкий scoped reader: `_session` удерживает Project FOR SHARE, затем SELECT только doc identity/summary/hash/size и checkpoint fence (revision/phase/version) под document FOR SHARE. Не загружать original/current BLOB ради проверки доступа. SQL immutable summary validate, unknown checkpoint schema/error -> safe error. Slot writers уже берут document lock, поэтому fence согласован с head. Полная проверка пакета/metadata остаётся при open и durable operations.

Это быстрый путь обычного actor без pending. Для recovery_pending/неопределённого attempt, когда нужна классификация собственного save, допустим полный passive recovery/status read с proof в одной transaction под semaphore. Нельзя признать receipt по одному совпадению observed hash/revision или склеить поля двух прочитанных в разное время snapshots. В D1 pending snapshot заново классифицирует проверенный stored handle/receipt; если слот уже сменился, возвращает conflict, сохраняя private old handle и RAM для будущего reconcile.

EditorView содержит registry/document/session IDs, command_sequence, native EditorSnapshot, base revision/hash, actor checkpoint revision, отдельно observed current DocxSummary и observed checkpoint revision/phase, state, last_command, active_command/recovery_pending descriptors без содержимого запросов. Данные repr скрыты. Нельзя смешивать actor base с latest observed head в одном поле.

State выводится из local operation state и свежего observation:

| Состояние | Разрешённые действия |
|---|---|
| editable | Native commands, checkpoint/save/обычный close, snapshot/download |
| recovery_pending | Snapshot/download, новый reconcile command со старым durable handle, explicit release_local |
| operation_pending | Snapshot/download, retry исходной команды или reconcile её ID, explicit release_local после выхода исполняющего вызова |
| conflict | Snapshot/download, безопасный повтор/reconcile сохранённого attempt (может отказать), explicit release_local; никакого rebase/нового save |

Conflict имеет приоритет при внешнем изменении base storage revision/hash или checkpoint fence, кроме ожидаемых собственных переходов active attempt. При read нельзя объявить свой prepare чужим только потому, что CP стал +1: распознавание собственных переходов делается full proof через durable adapter, не только арифметикой counter. В неясности сохранять operation_pending и требование reconcile. `is_dirty` остаётся native сравнением с saved digest; флаг «актуально сохранено» допустим только без pending/conflict и при matching current/base. Snapshot отражает момент чтения, а не обещание отсутствия будущих внешних изменений.

## 4. Порядок блокировок и публикация RAM

Index/budget lock краткий: lookup, reservation, accounting и assignment. Под ним нельзя ждать actor mutex, semaphore, SQL или вызывать editor. Никогда не держать SQL transaction, ожидая RAM lock/semaphore.

Порядок обычной операции: lookup под index (отпустить) → actor mutex → heavy semaphore → scoped SQL transaction, если нужен → завершить SQL → короткий budget/index lock → publication. Open использует отдельный open mutex для serial admission; live-open replay получает actor mutex ДО heavy semaphore. Ни одна actor operation не получает open mutex. Close удаляет mapping под index, не берёт open mutex. Перед публикацией/replay повторно убедиться, что actor ещё зарегистрирован; гонка close/open replay возвращает expired, а не создаёт другой actor в том же вызове.

Pure command выполняется на отдельном editor при удерживаемом project/document read lock. Candidate/DTO/budget reservation готовы внутри этого transaction, но live publication происходит ТОЛЬКО после успешного выхода `_session`. Ошибка read commit не меняет RAM — здесь записей в БД не было. Бюджетная reservation удерживается до публикации/отказа. Точка проверки права/внешней версии — успешное завершение read transaction; последующее внешнее сохранение обнаружится следующим observation/CAS. Не обещать distributed lease.

Ожидаемые native validation/unsupported/resource ошибки внутри `_session` преобразовывать в согласованный DocumentError до выхода: иначе общий storage boundary превратит их в 500. Неизвестные ошибки остаются sanitized 500; никакого broad catch с ложным успешным ответом.

Durable controls используют существующие C1/C2/C3 transactions **без внешнего SQL lock**. Иначе outer FOR SHARE на одной connection блокирует собственный FOR UPDATE на другой. Actor mutex сохраняет serial порядок локальных действий, но не является SQL lock. Между requests не удерживать transaction/semaphore/mutex. Незавершённый attempt остаётся данными actor, поэтому другой документ может работать.

## 5. Command ordering и bounded replay

Каждый mutating/control request: exact UUID command_id, expected_command_sequence, expected_session_revision, строго типизированный action. MAX=2^63−1, bool/coercion запрещены. Декодирование и bounded structural validation до hash/deepcopy; lower native validators перепроверяют anchors/types. Caller не выбирает имя Python method/callable/limits.

Canonical fingerprint namespace `ara.docx.editor-command.v1\0`: registry_id/document_id/session_id, command_id, оба expected counter, action, все semantic args. UUID canonical strings, 64-bit counters decimal strings, offsets/path integers. Явный encoder для allowlisted DTO; не generic asdict произвольного объекта. SHA256 обновляется кусками JSONEncoder.iterencode(sort_keys=True, ensure_ascii=True, separators=(comma,colon)); не собирать вторую giant JSON string. Wire 8 MiB и длина escaped JSON различны. Хранить только hash, command identity/action/result counters, не raw text команды.

Проверка под actor mutex после scope:

1. Exact latest accepted identity/старые expected counters + тот же hash -> повтор без операции и increment; fresh view/observation могут показать новый внешний conflict. Тот же latest command_id с другим payload/counters -> idempotency_conflict.
2. Active attempt: тот же ID/полная identity продолжает неизменённый attempt; другой запрос ->409 editor_operation_pending. Reconcile указывает ID и исходные counters активного запроса, не создаёт второй command.
3. Иначе expected_sequence/current core revision должны совпасть. Старый superseded request -> stale_command, без history lookup. Не обещать вечную дедупликацию UUID вне сохранённого latest/active; клиент обязан выдавать новый UUID каждому новому намерению и никогда не обновлять counters старого запроса.
4. До любого изменения reserve sequence+1; при MAX отказ. Для потенциально изменяющих bytes/history native intents дополнительно reserve core revision+1 (даже если фактически будет no-op); capture можно при core MAX, если sequence позволяет. Position не должен превышать MAX; проверять returned counters до публикации.
5. Успешный capture/no-op/checkpoint/clean save тоже sequence+1. Validation/resource/native failure до записи не увеличивает sequence. Native undo/redo сохраняют прежние bytes/selection semantics. Latest command receipt обновляется вместе с editor одной публикацией.

Адаптер поддерживает существующие capture, insert_text, enter, join_previous, join_next, paste_text, insert_soft_break, range_edit, structure, format, undo, redo. Передавать existing native DTO с exact validation, обязательные after targets там, где их требует EditorSession. D2 контракт фиксирует точный union перед тестами, без generic passthrough.

## 6. Durable attempt и SaveTarget

Перед ПЕРВЫМ вызовом, способным записать в БД, подготовить immutable Attempt и установить его в actor. Это отдельная публикация состояния «исход ещё не подтверждён», не successful command: sequence/editor остаются прежними. В Attempt: исходная identity/hash/action, неизменённые bytes reference/metadata/base/expected CP, request IDs, stage и private SaveTarget.

SaveTarget = registry_id/session_id/document_id, исходный command_sequence, native revision/position_id, working SHA/size и selection. Это binding текущей RAM, не historical CheckpointOrigin. Сохранить полный ожидаемый SaveHandle ДО prepare: алгоритм C1 детерминированен по expected CP+1, UUID operation_id и payload. Новый pure helper в runtime использует существующие canonical codecs/fingerprint; тест сравнивает его результат с реальным C1. Не менять C1 и не подделывать proof из receipt-only полей.

Для checkpoint/close/clean save Attempt держит один immutable PUT request. Для dirty save — prepare request_id, operation_id, finalize request_id и полный handle. Все UUID создаются один раз. Для recovered pending создаётся новый локальный command/SaveTarget, а старый handle/operation_id сохраняется; finalize request_id можно новый, C3A поддерживает logical completed proof.

Для dirty save заранее fork editor и подготовить mark_saved на этом fork для exact SaveTarget, не изменяя live history. Пакеты shared immutable; budget/результатная структура проверены до первого durable write. Actual receipt/base/CP данные проверяются при ответе; если окончательная DTO/publication подготовка всё же не удалась после DB commit, attempt остаётся для reconcile, dirty live не превращается в ложный ACK.

### Переходы save

| Шаг/исход | Что остаётся в RAM | Следующая попытка |
|---|---|---|
| До записи, validation/budget failure | Прежний editor, no active, sequence прежняя | Исправленный новый запрос |
| prepare вызван, ответ неизвестен | prepare_unknown, full ожидаемый handle и все IDs | Сначала искать proof handle через commit/reconcile; если matching pending/receipt не найден, повторить ТОТ ЖЕ prepare |
| prepare подтверждён | prepared, тот же candidate/handle | commit с тем же handle |
| commit вызван, ответ неизвестен | commit_unknown | commit того же handle: receipt replay, не новый save |
| commit подтверждён, finalize не подтверждён | finalize_unknown, receipt отдельно | finalize тем же handle/request_id |
| finalize подтверждён и current_matches_receipt | Проверить SaveTarget; atomically editor.mark_saved fork + base=receipt + CP=final + sequence+1 + latest receipt, active=None | Обычный latest replay |
| receipt/current или checkpoint чужие | Conflict, editor/candidate/attempt остаются | Read/download, explicit resolution; не очищать чужую работу |
| HTTP ответ потерян после RAM publication | Latest accepted receipt сохранён | Replay без второго mark_saved/save/increment |

Prepare-unknown recovery уточнение: из-за другого recovery controller prepare мог уже дойти до finalize. Нельзя обязательно начинать с C1: его replay отвергает уже сдвинутый CP. Сначала `commit_save(expected_handle)` может подтвердить receipt или exact pending. При checkpoint_conflict/save_unconfirmed без подтверждения попытаться тем же C1; затем C2/C3. Никакого повторного prepare с новым ID/обновлённым CP. Если slot чужой — оба пути безопасно отказывают. Это bounded последовательность, не бесконечный цикл. Receipt validation/idempotency/storage errors не интерпретировать как «prepare отсутствует».

`reconcile_save` C3B остаётся пригодным для стадии с известным handle; runtime хранит stage/полный prepare request, чтобы обрабатывать потерю самого первого ответа. matching receipt при уже superseded checkpoint подтверждает сохранение, но не разрешает очищать другой slot/mark_saved как актуальную работу. Вернуть conflict с отдельным save confirmation.

Любое исключение после dispatch durable request консервативно оставляет Attempt. Для 409/422 может быть доказан отказ этого вызова, но прежний ACK-loss уже мог записать данные. Snapshot/безопасный retry/explicit release доступны; ошибка не запускает discard. Простое отсутствие receipt не доказывает rollback. Storage 500 не раскрывает payload и не вызывает repair.

### Checkpoint, clean save, close

checkpoint PUT-ит exact working/selection/origin с текущими base/CP; receipt success меняет CP и sequence, но не saved digest/history. Повтор после ACK-loss тот же PUT; проверить, что returned current всё ещё matching base. Если уже изменён — conflict без mark_saved. Selection-only checkpoint допускается даже при dirty=false.

Обычный save dirty=false выполняет этот checkpoint, не создаёт storage revision/receipt. Dirty определяется native snapshot, а readiness — base/CP observation; одинаковые bytes при чужой revision всё равно conflict. Autosave использует тот же save; таймер двух минут — отдельный frontend/scheduler этап, в D фонового таймера нет.

close(mode=checkpoint) делает checkpoint даже clean, затем под mutex удаляет actor/mapping и освобождает budget. Pending сначала требует reconcile, close не начинает новый save молча. Failure оставляет actor. Потеря close ACK после удаления ->410; recovery показывает durable checkpoint, 410 сам ничего не доказывает. Переключение вкладки вызывает checkpoint, а не close: история остаётся в RAM.

Уточнение lifecycle: `close(mode=release_local)` — отдельное явное намерение caller отказаться от RAM-хвоста, без записи/очистки durable slot/current. Разрешено при conflict/pending после выхода текущего вызова под mutex. Не автоматический fallback/eviction. В UI E это возможно только после явного выбора пользователя; нельзя писать «ничего не сохранено», durable pending может завершиться. Default mode всегда checkpoint. Такая операция позволяет закрыть конфликтную копию после скачивания/импорта в отдельный документ, не присваивая себе чужой slot. Stale open закрывает registry sequence. Полное удаление durable draft — отдельные существующие CAS discard APIs, не побочный эффект закрытия вкладки.

release_local — терминальное удаление actor, исключение из правила accepted command sequence+1: оно проверяет exact текущие expected sequence/revision и отдельное explicit intent, после чего возвращает только подтверждение освобождения (не «сохранено»/новый snapshot). Это позволяет освободить actor даже при sequence MAX. Pending active command не считается completed; повтор release после удаления410, никаких повторных SQL действий. Обычный checkpoint-close подчиняется обычному sequence budget. Это исключение фиксировать в D3A acceptance до кода.

## 7. Память, snapshots и failure cleanup

Добавить private read-only `DocxSession._retained_packages()->tuple[bytes,...]` (current+undo+redo) и forwarding `EditorSession._retained_packages()`. Это единственное необходимое изменение pure core; не setter и не public wire field. Проверить отсутствие I/O и immutable references. Runtime не читает `_state` напрямую.

Registry учитывает union bytes references по id объекта, удерживая сильные ссылки, чтобы id не переиспользовался при счёте. Одинаковое содержимое в разных bytes считается отдельно; одна ссылка в undo/live/candidate — один раз. Под budget lock считать live actors + reservations + pending candidates. Final publication переводит reservation в actor retention атомарно; rollback освобождает её. Нельзя evict чужую/dirty/pending сессию для освобождения места.

Admission проверяет union live+новый candidate, а не только итог после удаления старой history. Пакет впервые возникает как transient результата native операции; до принятия/удержания проверить бюджет, при отказе не публиковать и отпустить. Semaphore ограничивает одновременно строящиеся packages/projections. 256 MiB — retained compressed packages, не hard RSS/peak limit: временный ZIP/XML/SQL data, projection и detached reply buffers требуют отдельного измерения до desktop release.

Snapshots готовить на запрос; не cache-ить projection/StoredDocx/оригинальный DOCX/полную JSON command history в actor. E сериализует и освобождает ответ до новых тяжёлых запросов, вводит bounded transport concurrency; retained registry budget не гарантирует объём объектов, которые произвольный Python caller удержал снаружи.

Наконец/finally освобождает actor/open mutex/semaphore/reservation при validation/DTO/DB/cancellation. В synchronous runtime прерванный HTTP request не должен запускать параллельно новый worker для того же actor до выхода первого из mutex. Application shutdown не объявляет незаписанный RAM-хвост сохранённым.

Текущий engine не задаёт lock_timeout/statement_timeout. D устраняет циклы собственных locks, но не доказывает ограниченное время ожидания внешнего SQL writer. В E/application wiring отдельно проверить cancellation и настройку SQL deadlines с контролем крупных файлов; не менять engine/старый `_session` скрыто внутри D1. Ошибка timeout любого durable вызова также требует обычного reconciliation.

## 8. Экспорт/анализ и будущий HTTP

Binary working download использует один scoped actor snapshot с ожидаемыми sequence/revision/hash; bytes/identity выдаются вместе, без внешнего latest GET. При conflict это копия для спасения работы, не утверждение successful save. Recovery download отдельно привязан к CP revision/hash.

Save barrier для Check/обычного Export возвращает immutable SavedTarget(document_id, storage_revision, SHA, exact bytes) после successful save/clean checkpoint. Содержимое берётся из замороженного candidate, identity из подтверждения; для clean case из того же проверенного base. HTTP retry, пока это latest accepted command, может вновь получить ту же bound copy. Если superseded — stale, не подменять новым current. Последующий внешний writer не меняет этот аналитический/экспортный снимок. Сам анализ/ML и запуск экспортного UI не добавляются в D.

E: явные DTO serializers, никакого asdict DocxSource/StoredDocx, DOCX только binary/no-store. 64-bit wire values strings, offsets code points; DOM UTF-16/IME преобразования остаются frontend. Strict bounded body/duplicate keys/headers/query правила прежние. Новые routes и узкий маршрутный test diff фиксировать только в E. Main frontend Ани не переписывать.

## 9. Циклы и приёмка

| Цикл | Разрешённый результат | Обязательные сценарии |
|---|---|---|
| D03-16D1 | Registry, согласованный recovery read/open, snapshot/epoch/open ordering, admission и private retained references | Повтор/гонка open, revoked scope, старый registry/session, working dirty и pending без save, conflict, corrupt metadata/receipt, бюджеты/DTO failure, inert import |
| D03-16D2 | Native command union, fork/publication, sequence/latest retry и error mapping | Capture/no-op и stale cursor, все intents/undo/redo, altered/superseded retry, concurrent commands, read commit failure, Unicode/large paste, union budget, history/selection exact |
| D03-16D3A | Attempt/SaveTarget, checkpoint/clean-save/close и release_local | ACK-loss PUT/close, чужой head/CP, ни одного false saved, closed-open retry, no eviction, reservation cleanup |
| D03-16D3B | Dirty prepare/commit/finalize/reconcile, recovered pending, SavedTarget | Все cut points, full expected handle до prepare, другое окно завершило save, current/CP superseded, DTO failure after commit, отдельный процесс, exact bound export bytes |
| D03-16E | HTTP/contracts/handoff | Scoped errors/streaming bounds/serializer, route acceptance, session epoch UX contract; UI/platform проверки отдельно |

Все реализации — **Sol 6.1 High**, по очереди; новый архитектурный проход по этому плану не требуется. Перед каждым циклом freeze собственных tests/точного контракта, red, implementation, targeted и bash scripts/check.sh, результат и локальный commit. D1 контракт готов в d03-16d1-contract.md; frozen executable tests создаются до source следующего прохода. Старые tests, B/C contracts/схема, dependencies/runner/tasks/progress не меняются. Пересмотр одного нового acceptance примера не разрешает ослаблять критерии.

Этот проект не доказывает работающий runtime. Текущие 2086 tests проверяют ранее реализованное. Базовый PostgreSQL V8 автоматически не мигрируется; новые adapter calls требуют V9. Реальные DOCX визуальные/Word проверки сохраняются; для D1 без редактирования допустимо exact-byte reuse проверенного fixture, для native edits в D2 — прежние package/visual gates.

## 10. Проверка решений на последовательностях событий

Это архитектурная трассировка, не выполненные runtime tests. Каждая строка входит в будущую executable acceptance указанного цикла.

| Последовательность | Почему не теряется/не повторяется работа | Цикл |
|---|---|---|
| open(seq0) → close release_local без SQL → поздний open(seq0) | Registry seq1 и отсутствие live mapping дают stale_open, CP fence не нужен | D3A |
| Два одновременных open одного ID/seq | open mutex, replay перед fresh CAS; один actor/increment | D1 |
| Edit fork создан → read transaction commit failure | Candidate/reservation уничтожены, live history/selection/sequence прежние | D2 |
| Save prepare записан → ACK потерян → другой recovery завершил finalize | Ожидаемый полный handle известен до dispatch; C2 receipt replay проходит без pending, C3 full proof подтверждает finalize | D3B |
| Finalize записан → DTO error → чужой writer сменил current | Retry подтверждает прежний receipt, current_matches_receipt=false; live не mark_saved как актуальная версия | D3B |
| Native same bytes/no-op → запоздавший capture старой sequence | Принятый no-op увеличил command_sequence; capture stale, хотя native revision могла не измениться | D2 |
| Restart с dirty working и историческим origin | Новый registry/session, restore revision0/history0, saved hash старой base; dirty сохраняется | D1 |
| Restart с pending уже имеющим receipt | Open frozen без записи; reconcile использует old handle + NEW local SaveTarget | D1/D3B |
| Чужой CP сменился, а current bytes равны | CP/storage revisions сравниваются независимо от SHA, автоматического rebase нет | D2/D3 |
| SavedTarget получен → другой writer сохранил → экспорт | Экспорт использует exact candidate/receipt snapshot, не latest current | D3B/E |
| Candidate history превышает union budget, итог после eviction был бы меньше | Отказ без публикации/автоматического удаления чужой истории | D2 |
| Вызов save держит actor mutex, затем запрос snapshot другого actor | Нет global SQL/index lock; незавершённый attempt освобождает semaphore между вызовами | D3B |

31 октября, реализация E3C: оговорка выше про отсутствие SQL deadlines в D закрывается отдельным HTTP wiring, см. [контракт](d03-16e3c-contract.md) и [результат](d03-16e3c-result.md). Instance-only OptionEngine/SET LOCAL lock5s/statement15s для editor HTTP, без изменения старого engine/_session/прямого Registry. Это не общий request/CPU/pool deadline. Остальные D решения остаются; frontend/IME/platform/Word gate отдельно.
