# D03-16 — сохранение и восстановление редактора DOCX

31 октября 2026. Проектирование на Astra 6 High после b44e03d, по команде Никиты «Давай дальше». Относится к F05/F06/F11/F12 current-product-scope.md. Уточняет раздел durability в d03-14-design.md. Это техническое решение для будущих циклов, не утверждение о готовности persistence. Код приложения, БД и HTTP в этом проектном цикле не изменяются.

## Основание и выбранное устройство

EditorSession уже обеспечивает точные bytes, выделение и undo/redo в RAM. DocxSession.__init__ считает начальный пакет сохранённым; поэтому его нельзя просто вызвать для несохранённого восстановленного DOCX и показать «Сохранено». Session revision не различает процессы, а capture/no-op/mark_saved не увеличивают её. Эти ограничения учитываются отдельным восстановлением saved digest и порядковым номером команд transport.

Существующие docx_documents содержат original/current, монотонную storage_revision; DocxEditReceipt атомарно подтверждает сохранение по operation_id. Старый docx_edit_drafts.payload строго соответствует одному TextEditRequest. Новый пакет нельзя записывать туда без поломки старого reader.

Выбраны:

1. Один новый постоянный checkpoint-slot на документ в отдельной таблице. В нём точный working DOCX, selection, base и pending save. Старые payload/таблицы/DTO не преобразуются.
2. Порядковая revision checkpoint-slot сохраняется даже после очистки. Это устраняет ABA «пусто → черновик → снова пусто»; старое окно не получает снова право записи только потому, что строку удалили.
3. Редактирование остаётся в RAM. Checkpoint при переключении/закрытии вкладки; каждые две минуты — checkpoint + сохранение current, если документ изменён. Явное сохранение, экспорт текущей работы и запуск анализа также проходят этот барьер. Не писать полный ZIP в PostgreSQL на каждый символ.
4. Save проходит prepare → commit → finalize с устойчивым operation_id. Pending bytes не изменяются между шагами. Повтор не выполняет split/join заново.
5. Один controller на вкладку, команды сериализованы; несколько вкладок/процессов конкурируют через checkpoint CAS и storage CAS. Никакого автоматического merge/перезаписывания проигравшей копии.

Это не zero-loss между checkpoint: авария может потерять ещё не записанный хвост RAM. История undo сохраняется при autosave/переключении вкладок в живом процессе. После restart восстанавливаются последний checkpoint, selection и pending; начинается новая пустая undo-история. Полноценная история версий продукта не добавляется.

## Идентификаторы и равенство

| Значение | Назначение |
|---|---|
| document_id + project/user scope | Проверить доступ до чтения checkpoint/receipt и выдачи конфликтов |
| storage_revision + current_sha256 | Версия подтверждённого current; сравнивать оба значения, SHA не заменяет revision |
| checkpoint_revision | Монотонная CAS revision постоянного slot, включая empty; не session revision |
| session_id | Новый случайный UUID каждого открытия controller; после restart старый ID никогда не восстанавливается |
| command_sequence | Монотонный номер всех принятых controller requests, включая capture/no-op/save; защищает от запоздалого курсора |
| session_revision / position_id | Существующие RAM-счётчики; не переносить в новую сессию как действующие номера |
| command_id | Идентификатор повтора одного RAM-запроса внутри session_id |
| operation_id | Устойчивый UUID сохранения current, ключ общего docx_edit_receipts |

64-битные revisions/sequence/position в новом JSON — канонические десятичные строки без знака и leading zero (кроме «0»). На Python — строгие int без bool. MAX_REVISION прежний 2^63−1; следующий шаг при исчерпании запрещён без изменения данных. Offsets/path indices — ограниченные JSON integers; code-point offsets, не UTF-16. UUID — lowercase canonical; digest — 64 lowercase hex. Недоверенные структуры перепроверять даже после model_construct/frozen bypass.

Равные bytes не доказывают выполнение операции и не разрешают игнорировать revision. Cursor принадлежит именно working digest/main part/path; после восстановления заново проектировать пакет и проверять обе точки/affinity. Храним исходное направление selection.

## Схема нового slot

Миграция 0009_docx_editor_checkpoints, parent 0008_docx_edit_drafts. Новая таблица docx_editor_checkpoints:

| Поле | Тип и правило |
|---|---|
| document_id | UUID PK, FK docx_documents.id; прежний порядок удаления по FK, без скрытого cascade |
| checkpoint_revision | BIGINT > 0; начальное empty = 1; каждый успешный переход +1, никогда не сбрасывать |
| format_version | SMALLINT, ровно 1 |
| phase | TEXT, empty / working / pending |
| base_storage_revision | BIGINT > 0 или NULL для empty |
| base_sha256 | TEXT hex64 или NULL для empty |
| working_data | BYTEA, 1…33554432 bytes или NULL для empty |
| working_sha256 | TEXT hex64 или NULL для empty |
| metadata | JSONB object или NULL для empty; строгая схема ниже |
| last_request_id | UUID nullable у исходного empty или после legacy fence |
| last_request_sha256 | TEXT hex64, NULL только вместе с last_request_id |
| updated_at | TIMESTAMPTZ NOT NULL, clock_timestamp() |

metadata = {selection, origin, pending}. selection — прежний EditorSelection в каноническом JSON (две точки с source anchor/path/offset/affinity). origin = {session_id, session_revision, position_id}; это источник checkpoint, не разрешение команд новой сессии. pending = null для working; для pending — {operation_id, request_sha256}. Prepared checkpoint_revision берётся из revision строки, не дублируется в mutable payload.

DB CHECK: допустимые phase/version, диапазоны/формат hash, NULL-поля согласованы с empty, тип metadata object, pending object/null согласован с phase, пара last_request заполнена вместе. Размер metadata ≤64 KiB в канонической UTF-8 JSON-сериализации, без секретов/текста требований. Path глубина ≤128, компоненты 0…100000, offset 0…2^31−1 с дополнительной проверкой по реальному p.text. App проверяет exact keys, types, package/hash, selection, base и pending fingerprint при каждом чтении. Неизвестная version/повреждение -> безопасная ошибка, строку не очищать. JSONB не хранит base64 DOCX.

Только один working package на slot; история по-прежнему ограничена RAM-бюджетом. Старые receipts хранят лишь metadata. Пользовательских product limits не вводим: package/projection defaults остаются техническими, без обрезания. Storage не принимает ослабленные caller limits. Downgrade 0009 разрешён только для таблицы без working/pending rows; иначе отказ без удаления черновиков. Upgrade/repeat/downgrade обязаны сохранять все старые rows/schema. Совместный запуск старого бинарника, не знающего 0009, не поддерживается; updater обязан завершить старый backend до миграции, без обещания rolling upgrade.

## Транзакции и старый draft

Использовать существующую _session(runtime): project ownership lock → document FOR UPDATE → slot/legacy draft/receipt. Чтение согласованного состояния: project → document FOR SHARE, затем зависимые rows в одной транзакции. Все новые writers и изменённый legacy recover() соблюдают этот порядок. Даже отсутствующие slot/legacy rows защищены общим существующим document lock; отдельный row lock на отсутствующую строку не считается защитой.

Это опирается на поведение блокировок строк до завершения транзакции и повторную проверку строки после ожидания при Read Committed. См. [PostgreSQL 18 locking](https://www.postgresql.org/docs/18/explicit-locking.html) и [Read Committed](https://www.postgresql.org/docs/18/transaction-iso.html). Выбор общего document lock — решение AIRA. Нельзя заменить его двумя независимыми SELECT без блокировки.

Legacy arbitration:

- Если docx_edit_drafts существует, новое открытие/создание рабочего checkpoint возвращает legacy_draft_present. Старый draft сначала восстанавливается/разрешается прежним путём; он не удаляется автоматически.
- Если новый slot working/pending, старый GET/PUT/DELETE /draft возвращает 409 draft_mode_conflict. Ответы при отсутствии нового checkpoint прежние; empty slot не мешает legacy. Блокировка применяется до декодирования payload, без возврата чужого содержимого.
- Старый successful PUT /draft при empty slot дополнительно увеличивает его checkpoint_revision и сбрасывает last_request_id/hash. Это fence для уже открытых новых RAM-сессий, даже если legacy draft затем удалён без изменения current. Legacy replay того же token/payload без записи slot не двигает. При максимальной revision — атомарный отказ. Старые token/CAS/payload остаются прежними.
- Если при чтении найдены одновременно legacy draft и nonempty slot — storage_error, сохранить обе копии. Не выбирать победителя по timestamp.
- Старые PUT content/text-edits/paragraph-commands остаются разрешёнными внешними writers. Их новая storage_revision обнаруживается новым controller; нет тихого rebase. Прежние migration/API тесты сохраняются; узкое дополнение ожидаемых routes фиксируется отдельно только перед HTTP-циклом.

## Checkpoint CAS

Получение slot может инициализировать empty revision 1 под document lock (не читать runtime при import). Вновь открытая сессия запоминает revision и current base. При наличии working/pending mode=current не игнорирует его: нужен recovery-путь с тем же checkpoint.

put_checkpoint(expected_checkpoint_revision, request_id, candidate) выполняется под общим lock:

1. Scope/целостность current и slot, отсутствие legacy, типы/лимиты candidate. Проверка повтора выполняется до запрета изменения pending.
2. Если revision = expected+1 и last_request_id/hash совпали с каноническим запросом — возвратить текущий результат без нового шага. Тот же ID с другим body в этой позиции -> idempotency_conflict.
3. Иначе revision обязана равняться expected; pending запрещает замену candidate. Старые retries после следующего перехода -> checkpoint_conflict, никогда не восстанавливают старую копию.
4. Проверить base == current revision/hash для обычной записи. При внешнем изменении сохранить предыдущий durable checkpoint и RAM candidate, вернуть docx_conflict. Автоматической подмены base нет.
5. Записать полные проверенные bytes/selection/origin, phase working, revision+1, last request; подготовить DTO до commit.

Идентичность checkpoint request — (document_id, expected_checkpoint_revision, request_id), а не вечный UUID-ledger. Последний fingerprint хранится для потерянного ACK. Empty после discard остаётся строкой с новой revision и последним fingerprint. UUID не используется вместо CAS; намеренное переиспользование ID с другим expected revision не возрождает старый запрос.

Внешний конфликт не должен уничтожить более свежий RAM-хвост: controller остаётся доступен для скачивания своей копии. Для crash-safe сохранения конфликтной работы нужен отдельный документ через существующий import с новым document_id; действие явно выбирает пользователь. Нельзя автоматически перезаписать единственный checkpoint другого окна. Работа с конфликтной копией не объявляется autosaved до успешного отдельного импорта.

## Save — prepare, commit, finalize

Controller замораживает новые document mutations, capture, undo/redo и второй save на время незавершённого durable-запроса. Другие документы работают. ACK-error не размораживает автоматически. RAM candidate/reply/mark_saved подготавливаются на отдельной копии; живой controller меняется только после подтверждённого исхода. Не держать SQL transaction между HTTP requests.

**Prepare** атомарно сохраняет текущий candidate как checkpoint с phase=pending и новым operation_id. Можно сразу перейти empty/working → pending одной транзакцией без промежуточной working-записи. CAS/retry/base правила как выше. В pending fixed working bytes/hash/selection/origin/base. Commit ещё не менял current.

request_sha256 = SHA256(prefix + canonical JSON), prefix `ara.docx.editor-save.v1\0`. JSON содержит version=1, document_id, operation_id, prepared_checkpoint_revision, base_storage_revision, base_sha256, working_sha256, working_size_bytes, origin, selection. Revisions в canonical JSON — десятичные строки; sort_keys=True, ensure_ascii=True, separators comma/colon, UTF-8. Fingerprint вычисляет backend из проверенных данных; caller hash не принимается как доказательство. Для checkpoint request другой namespace `ara.docx.editor-checkpoint.v1\0`, включить action/expected revision/request_id и все candidate поля, bytes представлены digest/size после проверки actual bytes.

**Commit** получает immutable SaveHandle {document_id, prepared_checkpoint_revision, operation_id, request_sha256}; candidate берётся только из durable pending, не из недоверенного JSON/повторного выполнения команды.

Уточнение C1 от 31 октября, после eee1a22: для проверки старого replay после очистки checkpoint SaveHandle хранит полный fingerprint payload: document_id/prepared revision, base revision/hash, working digest/size, selection/origin/pending identity. Operation ID/hash доступны из pending. Это позволяет пересчитать fingerprint и проверить altered handle без бывших working bytes; receipt schema не расширяется. Точный контракт — d03-16c1-contract.md. Минимальные четыре поля выше описывают назначение handle, а не достаточный состав его проверки.

1. Под lock проверить scope и current, затем общий DocxEditReceipt по operation_id.
2. Receipt есть: сравнить namespace fingerprint и проверить целостность receipt как D03-13; вернуть его исходный результат плюс отдельно актуальный current. Pending/slot может уже измениться — replay ничего туда не записывает. Другой fingerprint -> 409 idempotency_conflict. Общий ключ защищает и от коллизии с прежним text/paragraph save.
3. Receipt нет: slot обязан быть тем же pending с exact revision/operation/fingerprint; legacy отсутствует. Current обязан совпадать с base revision/hash. Любое несовпадение — конфликт без записи.
4. Записать current=working exact bytes, storage_revision=base+1, updated_at; добавить DocxEditReceipt с полным прежним DocxSummary. Подготовить ответ внутри transaction. Обе записи коммитятся вместе. Original DOCX не меняется. Pending пока сохраняется.

Каждый реально подготовленный save даёт +1 storage revision, даже если candidate bytes равны base: совместимо с прежним receipt >1. Обычный controller не начинает save для чистого документа — только checkpoint selection после проверки current base. Undo уже сохранённой правки сохраняется новым save, старые revisions/receipts не уменьшаются и не удаляются.

**Finalize** получает expected prepared checkpoint revision, SaveHandle и request_id. Под lock проверяет matching receipt и current == receipt revision/hash/size. Тогда переводит тот же pending в working с новой checkpoint_revision, base=receipt result, pending=null, bytes/selection неизменны. Last request обеспечивает retry. Это очищает pending, но оставляет один checkpoint для восстановления selection. Если slot уже изменился — не очищать чужой checkpoint; если current новее receipt — конфликт, pending сохраняется. Успешный DTO готовится до commit. Только затем RAM-копия подтверждает mark_saved для того же session_id/command_sequence/session_revision/digest и публикуется целиком. Автосохранение не сбрасывает undo/redo.

Повтор уже выполненного finalize распознаётся по expected+1/last_request до требования phase=pending. Он возвращает подтверждение предыдущего finalize и отдельно актуальный current, без новой записи. Если current успел измениться, controller показывает конфликт; такой повтор не даёт основания помечать рабочую копию актуальной. После следующего изменения slot старый finalize не применяется.

## Матрица восстановления и неопределённого ответа

| Durable состояние | Действие |
|---|---|
| empty | Открыть current с чистой пустой историей; новая session_id |
| working, base == current | Восстановить working/selection; saved digest = base_sha256; dirty определяется сравнением bytes digest; новая история |
| working, base != current | Вернуть конфликт с обеими идентичностями; working не очищать и не накладывать поверх current |
| pending, receipt отсутствует, current == base | Повторить commit по тому же SaveHandle, затем finalize; bytes не пересчитывать |
| pending, receipt отсутствует, current != base | Конфликт, сохранить pending |
| pending, matching receipt, current == receipt | Finalize, затем восстановить чистую сессию; потеря ответа не создаёт ещё одну storage revision |
| pending, matching receipt, current новее | Наш save подтверждён, но current уже другой; конфликт, сохранить pending/рабочую копию |
| pending, чужой/повреждённый receipt, неизвестная schema | Безопасный отказ без очистки |
| finalize прошёл, ответ потерян | Повтор по last_request или чтение working с новой base; не посылать новый save |
| Backend умер после RAM edit, до checkpoint | Восстанавливается предыдущий durable checkpoint; RAM-хвост не обещан сохранённым |

503/разрыв соединения могут означать неопределённый commit. Нельзя считать rollback доказанным по исключению соединения. Controller хранит неизменяемый request/handle и остаётся в pending/reconciling. Потеря ACK на prepare тоже блокирует mutation: повторить тот же prepare identity и только после подтверждения переходить к commit.

DTO validation до commit обязана откатывать transaction при ошибке. Ошибка последующей HTTP serialization/отправки после commit уже не откатывает БД: это lost ACK с обычным reconciliation. Не обещать атомарность сети и PostgreSQL. Статус conflict имеет приоритет над is_dirty=false: равенство working старой base не означает актуальность current после чужого сохранения.

Явный discard очищает только ожидаемую checkpoint_revision, оставляя empty tombstone. Pending перед discard классифицируется по receipt под тем же lock: пользователь видит, был ли current уже записан. Discard не откатывает уже совершённый save. Поздний commit без receipt после discard отклоняется по slot CAS; поздний replay существующего receipt лишь сообщает старый результат. При неизвестном исходе UI не обещает «ничего не сохранено».

## Controller и transport

Уточнение архитектурного прохода D от 31 октября после 6a091ef: [d03-16d-design.md](d03-16d-design.md) задаёт окончательные runtime state/lock/replay/resource правила и имеет приоритет над наброском этого раздела. В частности, open получает registry epoch и sequence, pending открывается без автоматического save, а явное release_local закрывает только RAM, сохраняя durable данные. [D1 contract](d03-16d1-contract.md) ограничивает первую реализацию. Схема и готовые B/C операции не изменяются.

Registry хранится в явном DocumentRuntime/application lifetime, не global singleton и не модульный I/O. Ключ (scope, document_id, session_id), отдельный mutex на controller. Новый процесс/закрытая сессия: 410 editor_session_expired, без автоматического replay команды на новой сессии. RAM-сессии не восстанавливают старый ID. Перезапуск worker с другой registry не считается поддержкой одной общей RAM-истории нескольких workers.

Начальные технические runtime defaults: 8 открытых controller, 256 MiB суммарных retained compressed packages (включая живые и подготовленные candidates без двойного счёта общей immutable bytes-ссылки), одна тяжёлая DOCX-операция одновременно на runtime. Существующий per-session предел 128 MiB/100 состояний сохраняется. При отказе admission — явная resource-limit ошибка без eviction чужой/dirty сессии; пользователь может сохранить/закрыть вкладку. Это не обещание предела всей RSS: XML/projection/transient buffers требуют отдельного измерения на control files перед desktop-поставкой. Registry не закрывает dirty/pending сессию по таймеру. Candidate/reply failure освобождает reservations/semaphore/mutex.

Каждый mutating запрос содержит command_id, expected_command_sequence и expected_session_revision. Sequence увеличивается на любой принятый запрос, даже capture/no-op; failed validation не увеличивает. Один outstanding request на клиентскую сессию. Хранятся fingerprint и короткие metadata последнего результата; projection пересоздаётся из того же current snapshot при retry, не кэшируется отдельной большой копией. Точный retry последнего command_id/sequence возвращает результат; altered body -> idempotency_conflict; старый уже superseded request -> stale_command, без повторной операции. GET snapshot позволяет узнать последнюю принятую identity. В save-неопределённости command остаётся активным, reply не выдаётся как завершённый до reconciliation. Полный cache текста/истории запросов не хранить.

В живой сессии reconcile ссылается на active_command_id/expected_command_sequence и продолжает именно незавершённую команду: не создаёт новый save ID и не увеличивает sequence второй раз. После restart recovery-controller получает новую session_id; его reconcile — новая RAM-команда, но использует старый durable SaveHandle. Close после подтверждённого checkpoint освобождает RAM; повтор после удаления registry entry может вернуть 410. Клиент проверяет durable checkpoint identity через recovery, а не считает 410 доказательством сохранения или потери работы.

Новые маршруты фиксируются в HTTP-подцикле, целевая группа:

- POST /docx-documents/{id}/editor-sessions — open current/recover, client_open_id для повтора открытия в живой registry; response session_id + snapshot. Повтор после restart создаёт новый session_id. Open не присваивает монопольную DB-lease и не перезаписывает checkpoint.
- GET /docx-documents/{id}/editor-sessions/{sid} — snapshot/status/last command identity.
- POST /docx-documents/{id}/editor-sessions/{sid}/commands — строгий discriminated union capture, insert_text, enter, join_previous, join_next, paste_text, insert_soft_break, range_edit, structure, format, undo, redo.
- POST .../{sid}/checkpoint, /save, /reconcile, /close — отдельные typed controls с command identity. Close сначала подтверждает checkpoint; failure оставляет сессию. Если phase pending, сначала reconcile. Переключение вкладки checkpoint-ит, но не закрывает RAM history.
- GET /docx-documents/{id}/editor-recovery — состояние checkpoint/current и классификация pending без mutation. POST .../editor-recovery/discard — явный CAS discard. Для конфликтной копии отдельный bounded binary download по ожидаемой checkpoint_revision/hash, не base64 snapshot.

Не выставлять произвольную загрузку пакета в live controller: все edit candidates получаются его операциями. Существующий import/PUT content остаётся отдельным внешним writer. Snapshot transport не включает DOCX bytes/base64; содержит projection/selection/identities/history depths/status. Download отдаёт проверенные bytes с no-store, revision/hash из одного snapshot; analysis использует конкретные сохранённые bytes/revision, а не новый GET latest без привязки.

Новые JSON endpoints: bounded streaming body, UTF-8, application/json, запрет duplicate keys/unknown fields/query/неоднозначных headers/content encoding, без request text в логах/errors. Command body ≤8 MiB для paste до 1M code points; control/selection body ≤64 KiB; projected reply ограничен прежними package/projection budgets. 404 scope/not found; 409 CAS/base/draft mode/identity conflicts; 410 session expired; 413 resource budget; 422 invalid input/unsupported operation; 500 stored corruption; 503 unavailable/unknown outcome. Клиент различает «проверено и отклонено» и неизвестный исход транзакции; HTTP code сам по себе не доказывает отсутствие commit.

## Порядок реализации

| ID | Разрешённый результат и проверка | Режим |
|---|---|---|
| D03-16A | Pure restore session/selection/saved digest; точный соседний контракт, без wire/БД | Sol 6.1 High |
| D03-16B1 | Миграция/ORM нового slot, version/null/size constraints, сохранность V8; без endpoints | Sol 6.1 High |
| D03-16B2 | Строгие checkpoint DTO/serialization, read/put/discard CAS + legacy arbitration/fence; real PostgreSQL concurrency | Sol 6.1 High |
| D03-16C | prepare/commit/finalize/receipt reconciliation; ACK-loss, rollback, старый replay и foreign writer | Sol 6.1 High |
| D03-16D | Registry/controller, command sequence, RAM/DB publication, restore dirty, resource/close policy | Sol 6.1 High |
| D03-16E | Bounded HTTP, точный маршрутный контракт, frontend handoff; без переписывания фронта Ани | Sol 6.1 High |

Перед каждым подциклом фиксировать собственные allowed paths/frozen acceptance и red baseline. Этот дизайн не разрешает одним шагом менять все слои. D03-16A уже имеет точный соседний контракт; остальные получают свои contracts до кода. При новой архитектурной неоднозначности остановиться после завершённого подцикла, не менять критерии ради зелёного gate. Runner/tasks/progress не изменяются.

Сквозная приёмка: cut points до/после каждого commit/ответа, два controller/process, старый /draft и все старые writers, same bytes/ABA/overflow, повтор altered identity, corrupt package/metadata/receipt, prefix/suffix/current/original сохранность, failed DTO/reply, restart с пустой историей и правильным dirty. Проверять настоящим PostgreSQL и отдельным процессом; модель переходов проектирования не заменяет эти тесты. Финальный UI-цикл проверяет Ctrl/Cmd клавиши, IME, Unicode и autosave на Windows/macOS совместно с фронтом, отдельный Word render/open gate остаётся.

31 октября, implementation pass: A/B/C/D/E разделены на frozen подциклы; актуальный список результатов — [очередь](development-queue.md). HTTP E1 metadata-first codec, E2 scoped JSON/lifetime, E3A exact saved/RAM/recovery downloads, E3B explicit discard и E3C scoped SQL deadlines описаны в [handoff](docx-editor-api.md). [Результат последнего HTTP цикла](d03-16e3c-result.md) фиксирует фактический gate и ограничения. Наличие backend transport не завершает frontend Ани, autosave timer, реальный ML/лицензию/desktop или всю DOCX matrix. Main V8 автоматически не мигрировалась.
