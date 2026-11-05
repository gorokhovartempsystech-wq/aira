# D03-17B2 — сохранение источника, запуска и результата проверки

1 ноября 2026. Архитектурный проход после B1 `4999b57`, по команде Никиты продолжить на Astra. F06–F10/F12; продуктовые границы остаются в [current-product-scope](current-product-scope.md). Это проект, не реализация runtime/миграции и не подтверждение настоящего inference. Предыдущий [D03-17](d03-17-design.md), sections 2/3, уточняется этим техническим решением; B1 wire и старые contracts не меняются.

Текущий цикл: этот документ, [целевой DDL](d03-17b2-schema.sql), [контракт B2A](d03-17b2a-contract.md), результат B2 и ссылки очереди/D03-17. Source/tests/migrations/dependencies/runner/tasks/progress не редактировать. SQL здесь — проверяемый проект будущей V10, не команда для основной БД. Публикация GitHub остаётся отдельной незавершённой задачей доступа.

## Проверенные основания и выбранное представление

- Последний полный implementation gate B1: 2704 tests + 24 subtests. Миграционный head в коде — V9; рабочая ara_dev остаётся V8. Это разные вещи: следующий Alembic upgrade не запускать в основной БД автоматически.
- `SavedTarget` содержит exact bytes, document/storage identity и registry/session/save-command evidence. Повторный GET current может вернуть другой файл. Принимаем target из trusted registry или source прежнего run; client не передаёт доверенные bytes/model/fence/owner.
- B1 `PreparedReview` и `ReviewEnvelope` — detached DTO, их можно создать/подменить вручную. Наличие класса не является доказательством валидации. В B2B воспроизводим request/response по source и сверяем все поля/bytes.
- Видимый snapshot имеет `max_manifest_bytes=33554432`; B1 request/result — 8 MiB, raw engine reply — 4 MiB. Generic B1 capacity не увеличивает server admission: 512 fragments, 1M code points, source 32 MiB. Без clipping.
- PostgreSQL JSONB меняет представление JSON и не принимает `\u0000`; B1 допускает такие символы в некоторых строках ответа. Поэтому exact command/snapshot/execution/request/reply/result храним **BYTEA**, а не JSONB/`::text`. Их SHA вычисляется над исходными canonical bytes там, где определён canonical wire. SQL проверяет размер/форму scalar fields, Python — UTF-8/JSON/достоверность. [PostgreSQL 18: JSON types](https://www.postgresql.org/docs/18/datatype-json.html).
- При подготовке публикации прочитан team main `353cfee98b1cc9db92b1251dc0f59beeb5b8717b`: новый engine возвращает `partial` и `checked.pairwise`, хотя VERSION остаётся 0.1.0. B1 pinned `036a4e8` закономерно отвергнет такой ответ. Это отдельная версия адаптера в C2, не основание ослаблять validator или объявлять реальную интеграцию готовой. Локальный снимок публикации — свидетельство на момент чтения, не обещание актуальности удалённого main.

## Четыре таблицы и границы ответственности

[d03-17b2-schema.sql](d03-17b2-schema.sql) задаёт **точный** набор колонок, типов, null/default, PK/UQ/FK/CHECK/index. Миграция B2A и ORM обязаны совпасть с ним. Нет нового enum type, extension/pgcrypto, trigger, sequence, JSONB или изменения V1–V9. Значения UUID/счётчиков/status/timestamps операций задаёт сервис явно; единственный server default — `sources.created_at=clock_timestamp()`.

| Таблица | Что сохраняет | Что нельзя переиспользовать |
|---|---|---|
| `docx_analysis_sources` | PK(document_id, source_sha256), exact DOCX bytes | Нет dedup между документами, ссылки на latest current, перезаписи source при новой версии |
| `docx_analysis_runs` | Принятая команда/порядок, source revision, snapshot, выбранный engine pack, состояние/время/fence | Новый save не меняет source; модель/profile не меняются после принятия; новый Retry — новый run |
| `docx_analysis_attempts` | Один фактический claim, worker instance UUID, fence, exact B1 request | UUID worker не PID и не полномочие убить процесс; один run не получает скрытый второй inference |
| `docx_analysis_results` | Один validated result/run, exact accepted engine reply, counters и digest | Ошибка/stop не создают пустой successful result; ранее опубликованное не заменяется |

`accepted_order` — положительный BIGINT внутри документа, вычисляется `max+1` под document lock; общий sequence не нужен. Даже одинаковые bytes на storage revisions 2 и 4 имеют разные run/snapshot identity. Source bytes при этом могут быть одной строкой в пределах документа. При найденном ключе source сравниваются и hash, и bytes; различие — corruption, не ON CONFLICT UPDATE. Новых функций удаления/GC нет. История — внутреннее основание восстановления, не пользовательский интерфейс версий.

`accepted_project_id`/`accepted_owner_id` — факты авторизации в момент принятия, FK к существующим entities. Новые таблицы не дублируют текущую project/owner ownership как истину. Доступ всегда через `document → project → current owner`; scoped FK связывают source/run/attempt/result **одним document_id**, а equality accepted/current project/owner проверяется runtime под locks. CHECK не умеет безопасно обеспечивать межтабличные правила; нельзя заменить это фиктивной CHECK-функцией. [PostgreSQL 18: constraints](https://www.postgresql.org/docs/18/ddl-constraints.html).

Читатель с текущим доступом к документу может читать его сохранённый результат; старый owner после transfer — нет. Выполнение прежнего active run не передаётся новому owner: accepted/current mismatch завершает его `failed/ownership_changed`. Nonlocking lookup IDs перед lock не даёт права чтения bytes или публикации. Если ownership ушла и вернулась, без существующего ownership epoch нельзя доказывать факт промежуточного transfer; контракт проверяет состояние под locks, не обещает такую историю.

### Что гарантирует БД

1. Один active run на документ (`queued/running/cancel_requested`) и один accepted client_request_id/document. Rejected competing request не резервирует ключ.
2. Source принадлежит тому же документу; retry указывает run того же документа, не самого себя. Terminal parent для retry и отсутствие циклов проверяются сервисом при создании по уже существующей неизменяемой истории.
3. Ровно одна attempt/run в этой версии. Взаимные deferred FK связывают её с `runs.attempt_id`; невозможно committed orphan attempt или pointer на чужой run. Создание пары делается одной транзакцией.
4. `succeeded` требует non-NULL result SHA и существующий matching result; result через обратный deferred FK требует именно succeeded run. Ни success без result, ни result у queued/failed не могут commit. `SET CONSTRAINTS ALL IMMEDIATE` перед возвратом проверяет пары, но ACK только после реального commit.
5. Shape/fence/lease/error/status/null-pairs, raw size bounds, finite timestamps, deadline exactly created+300 seconds, scoped identity и отсутствие CASCADE.

SQL **не доказывает** корректность ZIP/UTF-8/JSON/SHA, provenance/совпадение counters, immutability прошлой строки или допустимость перехода из одного ранее committed state. Эти гарантии дают B2B + закрытый B3 service с locks/CAS/revalidation. Административная запись с пересчитанными digest не является защищённой криптографически историей. Новые service APIs не разрешают произвольный UPDATE/DELETE данных. Перечисление этого разделения — условие честной приёмки, не разрешение пропустить проверки.

## Canonical данные и восстановление без модели

Новый storage format_version=1 не меняет `docx-review/1`. Точный codec B2B фиксируется перед его freeze в рамках следующих правил:

| Колонка | Bytes / digest |
|---|---|
| `command_data` | ≤16 KiB, strict canonical UTF-8 JSON `docx-analysis-command/1`; fingerprint только принятого клиентского намерения, не случайно выбранной текущей версии модели |
| `snapshot_data` | ≤32 MiB, canonical `visible_main._canonical.tokens(snapshot, omit_hash=True)`; SHA этих bytes **равен** `snapshot.snapshot_sha256`. Не сериализовать hash внутрь собственного preimage |
| `execution_spec` | ≤4 KiB, strict canonical JSON `{schema_version:'docx-analysis-execution/1', execution_kind, engine_version, models_version, model_sha256, adapter_sha256}` без attempt_id. SHA exact bytes; engine0.1 pinned adapter задаётся содержимым/hash, не одной строкой VERSION |
| `attempt.request_data` | Exact B1 `PreparedReview.wire_json`; SHA — `request_sha256`. Отдельный engine_request не дублируется в SQL: проверенно выводится из canonical request |
| `result.reply_data` | Exact принятые UTF-8 bytes engine reply, ≤4 MiB; SHA над этими bytes, не re-serialized JSON |
| `result.result_data` | Exact B1 `ReviewEnvelope.wire_json`, ≤8 MiB; SHA — `result_sha256`. Все count/no_findings сверяются с новым валидированным envelope |

Command saved содержит только version/kind, document_id, registry_id, session_id, save_command_id, command_sequence, session_revision, storage_revision, source_sha256. UUID canonical strings, bigint decimal strings (session_revision допускает 0). Command retry содержит version/kind, document_id и retry_of_run_id. Client_request_id — отдельный ключ, не поле этих canonical bodies. Schema keys exact; data/models/owner/timestamps/fence/extras запрещены. При replay сравнивается canonical body **и** digest, не один SHA. Повтор после смены server pack возвращает принятый run с прежним pack; новый client_request_id выбирает новую текущую конфигурацию.

Execution kind задаётся trusted runtime; `local_model` не выводится из содержания ответа и не принимается из HTTP. Действительность code/model pack и лицензий поставки проверяется C2; синтетические tests local_model branch не являются настоящим inference. `models_version` остаётся внутри BYTEA, не дублируется в TEXT: B1 может принять embedded NUL. Profile/policy SQL допускает bounded ASCII future identifiers, а codec v1 принимает только реально поддержанные `final-visible-main-v1` / `final-visible-no-comments-v2`; неизвестная версия явно unsupported, без fallback.

B2B восстановление: проверить точные типы/размеры до materialization; хеш source; rebuild snapshot по сохранённым document/revision/profile/policy; сравнить manifest bytes/SHA; прочитать execution spec; вызвать B1 prepare_review с **сохранённым attempt_id**; сравнить request bytes/hash; затем validate_engine_reply над exact reply; сравнить result bytes/hash/counts/no_findings. Никакого inference, latest source, quote repair или загрузки текущей модели. Source/canonical/limits mismatch → safe corruption error, не пустые замечания. Для старого поддержанного profile сохраняется reader; смена версии приложения не пересчитывает старый result новым reader молча.

DTO не capability: constructor bypass/replace/wrong nested values/hash-only tampering и request чужой attempt должны отклоняться. Source/manifest/result/quotes и model metadata repr=False, не в logs/errors. Метаданные списков читаются column projection без BYTEA; полный source-backed read — явная отдельная операция. Runtime не валидирует каждый metadata poll по 32 MiB source.

## Запуск, время и блокировки

Схема не реализует API/worker. B3 получает следующий протокол; отдельный точный service/HTTP contract перед кодом.

1. Проверить scope и поискать durable key. При exact replay вернуть принятый run независимо от expired RAM registry/нынешней версии/current/model/status. При altered body — conflict. Сначала эта проверка, затем получение fresh SavedTarget.
2. Fresh saved: под registry actor получить detached подтверждённый SavedTarget и отпустить mutex. Fresh retry: scope-check terminal parent, взять его immutable source/revision; никогда не current DOCX. Нельзя retry active run. Для нового retry текущий trusted pack/profile выбирается заново, версия запроса сохранена явно; coverage/admission проверяются снова.
3. Зафиксировать начальный DB clock до extraction/manifest/model admission. Это `created_at`, deadline=+300s. Предварительная подготовка входит в бюджет, даже если строка run ещё не создана. Если до insert deadline истёк или source/admission не прошли, нет принятого run/source/key; возвращается отказ. Не начинать счётчик только после дорогой extraction. Время сохранения редактора до начала check не является inference.
4. Выполнить bounded extraction/admission вне actor/SQL locks. Immutable target не подменять при параллельном save. Каноническая команда связывает revision/SHA и доказательство registry; client-crafted SavedTarget не доверенный вход публичного сервиса.
5. Enqueue transaction: глобальный admission advisory-xact lock → project → document → replay/active check → source/run insert. Установить accepted order, неизменяемые данные и created/deadline; reread fresh DB clock перед insert/commit gate. Повторить replay проверку после lock. Не оставлять orphan source при rejected enqueue/rollback. Initial queue cap16 queued **на эту локальную БД**, не на отдельный HTTP процесс; схема сама cap не обеспечивает. Один ML child/app instance дополнительно обеспечивается C1.

Advisory lock нужен только enqueue/cap, одинаковая фиксированная namespace пара двух int в B3 (резервируется там); брать **до** row locks. Другие операции не берут его после row lock. Worker не должен держать глобальную блокировку во время работы. Выбор конкретного числа — не product decision и не новый DB object. [PostgreSQL 18: explicit/advisory locks](https://www.postgresql.org/docs/18/explicit-locking.html).

Все изменяющие операции затем используют один порядок **project → document → run → attempt**, sources/results дочерние после document/run. Project lock обязан конфликтовать с transfer owner (`FOR SHARE` или stronger, не `KEY SHARE`); writes document/run `FOR UPDATE`. Не держать locks/actor при ZIP parsing, engine, ожидании child или replay validation больших bytes. Прочитанный immutable input валидируется снаружи; затем под locks повторно сверяются binding/hash/byte identity и eligibility. После locks/validation брать свежий `clock_timestamp()`, а не `now()` начала транзакции. SQL без авторизации после предварительного unscoped lookup запрещён.

Claim: выбрать candidate без захвата run раньше project; подготовить B1 request с новым attempt UUID вне locks; затем recheck queued, owner, exact run binding, deadline и отсутствие attempt под locks; atomically insert attempt + set running/fence1/attempt_id/started/heartbeat/lease. Concurrent loser уничтожает свою подготовку, не child. Выходной claim только после commit. Между выбором и claim deadline мог пройти — transition timed_out, не запуск. Не импортировать engine для подготовки протокола.

### Fence/state matrix

| State | Fence | Attempt / lease | Result |
|---|---:|---|---|
| queued | 0 | нет / нет | нет |
| running | 1 | одна, claim_fence=1 / действует | нет |
| cancel_requested | 2 | та же / прежний срок без продления | нет |
| succeeded | 2 | та же / очищен | один |
| failed/cancelled/timed_out до claim | 1 | нет / нет | нет |
| failed/cancelled/timed_out после claim | 2 | та же / очищен | нет |

Это **одна attempt/run**, а не generic автоматический retry scheduler. Fence не уменьшается; accepted claim нельзя выдать снова. Worker token включает run_id/attempt_id/worker_instance_id/claim_fence; success/heartbeat принимаются только при running+fence1+match+live lease+fresh deadline+current ownership. Сохранённый PID нигде не является token.

Heartbeat ≤5s; new lease=min(DB time+15s,deadline), только пока **предыдущий** lease ещё действует. Истёкшую lease нельзя оживить поздним heartbeat. Cancel running повышает fence до2 и сохраняет прежнюю lease как reaper deadline; heartbeat больше не продлевает её. Cancel queued сразу terminal cancelled. Stop после terminal возвращает фактическое состояние, не меняет успех. Deadline имеет приоритет, если уже наступил при lock gate. Между accepted cancel и deadline acknowledgement может успеть cancelled; при достижении deadline первым — timed_out. Reaper: expired queued → timed_out; expired running lease → failed/interrupted; expired cancel_requested lease → cancelled; deadline любого nonterminal → timed_out. Child termination и local irreversible cancel latch — C1, не SQL.

`succeeded`+result publish — одна transaction с deferred связями. Сначала полностью B1-валидировать reply снаружи locks, затем под locks повторить eligibility. Привязки immutable; нельзя переписать их перед публикацией. failed/cancelled/timed_out не удаляют старые successful runs; latest result выбирается max accepted_order среди succeeded. Running stage только реально начатый этап; проценты/вымышленное завершение не хранить.

Точка завершения по времени — fresh DB-clock decision под locks непосредственно перед terminal update. Нельзя обещать физическое окончание WAL/fsync к той же наносекунде: commit может завершиться позже. UI получает success лишь после подтверждённого commit. Monotonic deadline C1 никогда не продлевается heartbeat/сдвигом wall clock назад. SQL reaper использует wall clock; строгая защита queued timeout от системных clock jumps требует monotonic runtime budget и отдельной приёмки C1/desktop, не обеспечивается TIMESTAMPTZ CHECK.

Unknown commit: не повторять inference. Read/reconcile scoped run/attempt/result; exact successful bytes/digests подтверждают replay. Если stored результат отличается, conflict/corruption, не overwrite. Если still running, повтор публикации того же validated reply возможен только при действующей lease/deadline/local latch. Сбой БД не создаёт fictional terminal status и не делает недоказанный ответ доступным UI.

## Миграции и приёмка

B2A добавит V10 `0010_docx_analysis_storage`, parent `0009_docx_editor_checkpoints`, четыре ORM класса. Constraints обеих циклических пар создаются после таблиц, без CASCADE; metadata identity/DDL сравниваются на настоящей disposable PostgreSQL. В кодовой базе V9 frozen migration tests ходят в moving head, хотя assert exact V9. Narrow pin описан в контракте B2A: все прежние assertions сохраняются; новый gate отдельно проверяет V9→V10 и latest ORM. Не менять общий fixture default head и не скрывать новые таблицы в старых assertions.

Downgrade V10→V9: одной transaction получить `ACCESS EXCLUSIVE` для четырёх таблиц в фиксированном порядке **runs → attempts → results → sources**, затем проверить **любую** строку в любой из них. Даже один source/failed run/idempotency receipt/result — сохранённая работа; refuse safe RuntimeError до DDL. Чистый downgrade явно удаляет cyclic FK, затем results/attempts/runs/sources. Не делать TRUNCATE/DELETE/CASCADE, auto-GC или rewrite документов. Concurrent writer: миграции выполняются без runtime; защитный lock всё равно обязан исключать check-before-drop race. При deadlock/timeout transaction откатывается полностью, после отказа version/data/schema неизменны. B2A проверяет writer commit и writer rollback, direct V9 и несколько шагов downgrade (V9 может отдельно отказаться из-за checkpoint).

B2A matrix: exact schema/defaults/types/FK deferred flags/index predicates/ORM match; V9 history с непустыми saved/working/pending, legacy Markdown/reviews/receipt; upgrade/repeat; clean/dirty downgrade; SQL NULL holes/size boundaries/finiteness/deadline/fence shapes; scoped orphan/mixed document/run; duplicate active/key/order/attempt/result; commit-boundary result/attempt pairs; конкурентный unique index и lock-before-inspect. B2B matrix: canonical Unicode/NUL/duplicate keys/depth/bytes caps, source replay and corruption, fixture/no_findings, result/count/provenance replacement, restart pure restoration без ML/I/O, short/emoji/hidden-gap evidence, exact result retention.

## Следующие ограниченные циклы

| ID | Граница и результат | Режим |
|---|---|---|
| D03-17B2A | Четыре модели, миграция V10, независимая real-PG приёмка; [контракт](d03-17b2a-contract.md) готов | Sol 6.1 High |
| D03-17B2B | Pure storage command/execution codecs, snapshot/request/result integrity и восстановление B1 envelope. Новый собственный контракт/frozen tests перед кодом; без SQL lifecycle/HTTP | Sol 6.1 High |
| D03-17B3A | Scoped start/replay/retry/read immutable target, source dedup/admission и порядок запуска | Sol 6.1 High |
| D03-17B3B | Claim/heartbeat/complete/cancel/reconcile/reaper, deadlines и concurrent cut points | Sol 6.1 High |
| Далее C1/C2/D/E | Child process, адаптер выбранной engine версии, API/freshness и фильтры/скрытие | Sol по отдельным контрактам; Astra только при новом архитектурном противоречии |

B2A не означает, что результат уже сохраняется пользователю. B2B не обещает durable операции без B3. Дополнительный разрез B2/B3 делает две прежние крупные строки четырьмя проверяемыми implementation циклами; это детализация прежнего резерва, не объявление всех этапов завершёнными. Native Word c0/сложные readers остаются открытыми и не блокируют эту независимую ветку. Полноценный DOCX, лицензирование, desktop runtime/installer и реальный frontend/model integration впереди.
