# DOCX API для подключения редактора

Актуально 31 октября 2026: прежний D03-13 и новые D03-16D/E1/E2/E3A/B/C ниже. Состав продукта определяется current-product-scope.md. Документ описывает готовые backend-возможности и явные ограничения; frontend Ани не реализован этими циклами. Ничего не отправлено другим участникам команды.

## Чтение и запись

API подключается к приложению с явным локальным DocumentRuntime. Текущая local-dev identity не является авторизацией или лицензией. Default create_app() содержит только /health. Swagger/OpenAPI: /docs и /openapi.json на явно запущенном local сервере.

| Операция | Маршрут | Результат |
|---|---|---|
| Создать пустой AIRA DOCX | POST /docx-documents/{uuid}/create?title=… | Metadata; стабильный UUID позволяет повтор |
| Импортировать DOCX | POST /docx-documents/{uuid}/import?title=… | Binary body; исходные bytes сохраняются |
| Список / metadata | GET /docx-documents, GET /docx-documents/{uuid} | Ограниченный список / metadata |
| Структурное представление | GET /docx-documents/{uuid}/view | Blocks, paragraph/span anchors, style_id, numbering_id/level |
| Скачать текущий DOCX | GET /docx-documents/{uuid}/content | DOCX bytes, ETag, X-ARA-Storage-Revision |
| Заменить пакет | PUT /docx-documents/{uuid}/content?expected_storage_revision=… | Binary CAS, без idempotency receipt |
| Редактировать один span | POST /docx-documents/{uuid}/text-edit | Старый TextEditRequest, optional Idempotency-Key |
| Абзацы, стили и списки | POST /docx-documents/{uuid}/paragraph-commands | Обязательный Idempotency-Key, атомарный batch |

Не строить визуальное Word-представление только по /view: это structural projection, она не рендерит layout и не обещает извлечение всех частей. has_unprojected_content/notices/opaque явно сообщают границы. Сложные элементы сохраняются в пакете, даже когда редактирование выбранного элемента пока недоступно.

## Paragraph commands

Content-Type: application/json; необязательный единственный charset=utf-8. Content-Encoding только identity. Тело до 2 MiB. Idempotency-Key: новый canonical lowercase UUID для одной пользовательской попытки. document_id и operation_id — разные идентификаторы. Query запрещён. Ревизии всегда передавать/читать **строкой**, не JavaScript Number.

Body содержит expected_storage_revision (из свежего view), kind (structure или format) и commands. Каждый anchor копируется целиком из paragraph.anchor, а не span.anchor. expected_text — точный paragraph.text: без trim, нормализации пробелов/переносов/Unicode. Все команды одного batch адресуют один и тот же source_sha256.

| command.kind | Остальные поля | Смысл |
|---|---|---|
| insert | anchor, expected_text, texts: string[], position: before/after | Вставить отдельные body paragraphs; default position after |
| delete | anchor, expected_text | Удалить выбранный body paragraph |
| format | anchor, expected_text, style_id, list_kind, list_id | Полностью задать прямой paragraph style/list |

kind=structure допускает insert/delete в одном batch. kind=format — только format. Форматировать только что добавленные абзацы можно следующим запросом после получения свежих anchors. Одному source paragraph нельзя задать дублирующие/конфликтующие команды. Порядок независимых structure/format commands не влияет на экспорт, но порядок commands участвует в идентичности запроса.

Форматирование задаёт полное состояние. Чтобы поменять только стиль, передать также нужное состояние списка; чтобы изменить список, сохранить нужный style_id явно. Default style_id=null удаляет прямой стиль; default list_kind=none/list_id=null удаляет прямой numPr. Автоматически сохранять пропущенное поле API не обещает. Imported style IDs не переводятся и не заменяются AIRA-стилями. Для новых AIRA известны Normal, Title, Heading1/2/3, ListBullet/ListNumber. Полный каталог импортированных styles отдельным API пока не выдаётся; неизвестный ID отклоняется.

list_kind=bullet/numbered и list_id=null создают новую native последовательность с уровня 0 и старта 1. Соседние в исходном body commands одинакового вида объединяются в одну последовательность, пропуск/другой вид/явный ID разрывает группу. Для продолжения существующего списка передать его numbering_id из view как list_id; вид обязан совпадать. API не вставляет маркеры в текст. Снятие списка требует none/null. Работа с многоуровневыми списками и разрешение numStyleLink не реализованы.

При insert каждое texts[i] становится отдельным абзацем с default formatting документа. LF внутри строки — мягкий Word line break, TAB — Word tab. Это не split текущего styled paragraph и не вставка в позицию курсора: содержимое/formatting исходного paragraph остаётся прежним. Delete не удаляет последний body paragraph. Ячейки, hyperlinks, section properties, поля, annotations/ranges/отслеживаемые изменения и защищённые пакеты имеют консервативные границы pure API; отказ не изменяет документ.

Лимиты: batch 1..1000 commands; expected_text/каждый новый текст ≤100000 code points; суммарно новых абзацев ≤1000, нового текста ≤1000000; style ID 1..255; existing list ID canonical positive int32. Это технические ограничения операции, не обещанный продуктовый предел документа. Полный schema доступен в OpenAPI. Нельзя молча обрезать вход.

## Подтверждение, повтор и конфликт

HTTP 200 возвращает operation_id, document_id, title, storage_revision, current_sha256/current_size_bytes, created_at/updated_at. Revision — строка; остальные типы описаны schema. Ответ и ошибки команд имеют Cache-Control: no-store. Ошибки используют прежние code/message/retryable/request_id, без request text и внутренних исключений.

До подтверждения держать исходное тело и тот же operation_id неизменными. При сетевой ошибке/503 запись могла уже завершиться: повторить тот же запрос с тем же ключом. Он вернёт исходное подтверждение без повторного применения, в том числе после перезапуска backend. Другой запрос с тем же ключом получает 409 idempotency_conflict. Не создавать новый ключ автоматически после неизвестного исхода.

Receipt может относиться к уже более старой revision, если после операции были другие записи. Успешный replay не означает, что возвращённая revision сейчас последняя. После подтверждения читать свежий /view и не заменять новую локальную работу старым snapshot. Подтверждённые операции не отправлять повторно как новые. Даже semantic no-op создаёт одну storage revision; retry не создаёт следующую.

409 docx_conflict — другой writer изменил storage revision; stale_source/text_mismatch — anchors/text не соответствуют пакету. Сохранить пользовательский ввод, перечитать view и явно согласовать новое действие. Не переписывать чужую более свежую версию и не подставлять новые anchors к старой операции автоматически. 422 unsupported_structure/unsupported_format/invalid_anchor/conflicting_commands/conflicting_formats означает, что пакет не изменился; показать причину и оставить ввод. 413 означает технический лимит; 404 сохраняет scope, не раскрывает наличие чужого документа. 500/503 не считать подтверждением.

Idempotency ledger общий с прежним text-edit, поэтому один operation_id нельзя переиспользовать между разными видами операции одного документа. Для разных документов ключи независимы. Original DOCX не перезаписывается: content отдаёт текущий пакет, original остаётся в storage. Замечания AIRA в DOCX не записываются.

## Что ещё нужно frontend и следующему backend-циклу

Этот маршрут сохраняет команды сразу и атомарно. Он не хранит unsent command batch или undo stack UI. Прежний /draft предназначен для прежней single-span рабочей копии; не отправлять туда новые structure/format bodies. Состояния ожидания/повтора новых batch, структурный undo/redo, вставка по курсору и устойчивое восстановление ещё не подключены к frontend. Их готовность не следует из наличия HTTP-команд. Лицензия и реальная локальная модель также не входят в этот API-цикл.

31 октября подготовлен [дизайн split/join и общей отмены](d03-14-design.md). Он разделяет чистые XML-операции, историю открытого документа и durable working state; это план следующих циклов, а не новые действующие endpoints. D03-13 и старый /draft сохраняют текущие wire-контракты.

## Живой редактор — D03-16D/E1/E2/E3A

Новый transport подключён только с explicit DocumentRuntime; PostgreSQL должен иметь schema V9. Рабочая БД автоматически не мигрируется. Один app владеет registry/эпохой, caller владеет engine. Health-only app не создаёт registry и не подключается к БД. Старые маршруты остаются внешними writers: их запись вызывает конфликт живого редактора, без тихого rebase.

Последовательность нового frontend:

1. `GET /docx-documents/{document_id}/editor-recovery` читает состояние без создания черновика. Сохранить registry_id/open_sequence/checkpoint_revision. Для absent/empty выбрать mode=current; для рабочей/незавершённой копии пользователь выбирает recover. Не уничтожать найденную копию автоматически.
2. `POST .../editor-sessions`: registry_id, новый client_open_id, expected_open_sequence, expected_checkpoint_revision, mode. Reply kind=opened с view и accepted_open_sequence/next_open_sequence. Exact retry открытия возвращает текущий view того же живого actor. После restart registry/session IDs меняются; старые запросы получают410. Новый процесс восстанавливает bytes/selection, history/revision/position начинают с0; durable undo stack не обещан.
3. `GET .../editor-sessions/{session_id}` возвращает metadata: counters/selection/dirty/history/state/последний и активный intent. `GET .../{session_id}/view` отдельно возвращает structural projection и metadata одного snapshot. В metadata нет текста документа или BLOB. View может получить413 по размеру, при этом metadata ACK и undo доступны.
4. `POST .../{session_id}/commands`: command_id, expected_command_sequence, expected_session_revision, command с action/value/optional after. Формы всех действий — OpenAPI: capture, insert_text, paste_text, enter, join_previous/join_next, soft_break, undo/redo, range_edit, structure, format. Не пересылать UI event или внутренний метод. Один неразрешённый запрос на сессию; следующий intent после ACK использует возвращённые counters. Успешный capture/no-op тоже увеличивает command_sequence. Native session_revision увеличивается при изменении bytes; position_id и selection не заменяют ни один из этих counters.
5. `POST .../{session_id}/checkpoint|save|reconcile` принимает ту же identity без command. Checkpoint сохраняет рабочую копию, save подтверждает конкретные bytes как current. При неизвестном исходе сохранить исходную identity и повторять её или reconcile. Нельзя создавать новый command_id и заново применять edit. Active attempt замораживает следующие intents; ошибки сети/503 не доказывают rollback. Per-app503 editor_busy означает отсутствие dispatch именно этого запроса. Server request_id из error envelope — диагностический UUID, не client command_id.
6. `POST .../{session_id}/close` default mode=checkpoint сохраняет копию и освобождает RAM. Явный mode=release_local только освобождает RAM, не отменяет SQL/save и не очищает pending. После close session410; повтор lost close ACK не создаёт новый checkpoint. Не вызывать release_local автоматически при ошибке.

UUID canonical lowercase; все command/session/storage/checkpoint/open/position counters — decimal **strings**, никогда JavaScript Number. Offsets — Unicode code points; DOM UTF-16 offsets нужно переводить в обе стороны, не разрезая surrogate pair. Selection anchor/focus сохраняют направление и affinity. Enter создаёт абзац, soft_break — Word line break; Shift+Enter/IME/DOM bindings остаются работой frontend. Нельзя заменять unsupported/opaque части плоским текстом ради отображения.

Control body≤64KiB, command body≤8MiB. JSON UTF-8 без duplicate keys/неизвестных fields/query/неоднозначных headers; gzip не принимается. Metadata≤64KiB, full projection≤8MiB с отдельными budgets на nodes/text/depth; 413 без молчаливого truncation. Per-app nonblocking gate охватывает чтение body, worker и send, включая скачивание. Все editor-prefix successes/errors/404/405 no-store. Local-dev identity по-прежнему не является лицензией/продуктовой авторизацией.

### Три вида скачивания

| POST path от `/docx-documents/{document_id}` | JSON body | Что скачивается |
|---|---|---|
| `/editor-sessions/{session_id}/saved-content` | command_id последнего save, **результирующие** expected_command_sequence/expected_session_revision | Exact SavedTarget этого подтверждения; даже если current уже изменён другим writer |
| `/editor-sessions/{session_id}/working-content` | expected_command_sequence, expected_session_revision, expected_sha256 из последнего metadata | Текущая RAM копия; допускает conflict/pending/повреждённый receipt |
| `/editor-recovery/content` | expected_checkpoint_revision, expected_sha256 из recovery | Exact durable working/pending copy; без commit/finalize/receipt lookup |

Ответ — DOCX binary с ETag SHA256, no-store, безопасным UUID filename и X-ARA-Copy-Kind=saved/working/recovery. Дополнительно storage revision для saved, command/session counters для working, checkpoint revision для recovery. Working/recovery download не подтверждает сохранение, не меняет current/history/dirty/черновик. Устаревшие counters/hash дают409; старый local SavedTarget после нового intent также409. Повреждённый package/metadata не выдаётся как проверенная recovery copy. RAM rescue зависит только от scope и сохранности самой RAM, не от receipt/чужого CP. Утерянная RAM после закрытия процесса не восстанавливается этим маршрутом.

Перед будущим анализом или экспортом сохранённой версии использовать save ACK → saved-content с resulting counters и тем же command_id. Новый GET общего `/content` может вернуть уже другую версию и не заменяет SavedTarget. Автосохранение каждые две минуты, запуск/отмена анализа, реальная модель и UI ещё не подключены. Полная DOCX matrix и визуальный renderer не следуют из structural projection и сохранения исходных частей.

### Явное удаление черновика — D03-16E3B

После явного выбора пользователя `POST .../editor-recovery/prepare-discard` с expected_checkpoint_revision и новым request_id возвращает plan. Подготовка read-only: working/pending остаётся, receipt не читается. До выполнения хранить plan целиком в клиенте. Working plan содержит kind/document_id/expected_checkpoint_revision/request_id; pending plan — kind/document_id/request_id и полный immutable handle без package/text. Это описание выбранной копии для безопасного повтора, не ключ доступа.

`POST .../editor-recovery/discard` принимает plan целиком. После сетевой ошибки/503/ошибки формирования ответа повторять **тот же plan**, даже после перезапуска. Не вызывать prepare заново для более свежего CP и не подменять request_id. Новый черновик получает другую revision: старый plan его не удалит. Prepare не выдаёт план для absent/empty; вручную построенный working plan следует прежнему B2 empty-CAS поведению.

Ответ kind=discarded содержит checkpoint_revision, current summary, save_confirmation и current_matches_receipt. Для working confirmation=not_checked/matches=null. Для pending confirmed означает найденное подтверждение записи, unconfirmed — отсутствие подтверждения при этом чтении, без обещания rollback. Удаление черновика **не откатывает current/original/receipt**, включая уже сохранённый или более новый current. Повреждённый receipt блокирует pending discard, при этом valid recovery download остаётся доступен.

Живые сессии не закрываются/не rebase/не mark_saved при discard. Их metadata показывает conflict нового fence, RAM можно скачать через working-content. Пользовательский выбор оставить/освободить RAM отдельный. Не использовать discard как автоматическую реакцию на save error, timeout или закрытие вкладки. Все запросы имеют прежние strict JSON/64KiB/gate/no-store/error границы.

### Ожидание БД — D03-16E3C

Explicit editor transport использует отдельный engine wrapper с общим caller-owned pool: на каждую транзакцию только редактора PostgreSQL получает SET LOCAL lock_timeout=5s и statement_timeout=15s. Это касается JSON, binary downloads и discard. После commit/rollback настройки сбрасываются, прежние API/прямой Registry с исходным runtime их не наследуют. App не закрывает caller engine/pool и не меняет server/role defaults.

SQL timeout возвращает503 storage_unavailable с retryable=true. Если durable attempt уже отправлен, сохранить command identity/plan и повторить тот же запрос или reconcile после устранения причины. Не повторять edit, не выдавать timeout за rollback и не очищать черновик автоматически. Пока worker занят, другой editor-prefix request получает503 editor_busy без dispatch; после выхода worker gate освобождается.

Эти лимиты относятся к отдельному SQL statement/ожиданию lock. Они не ограничивают целиком транзакцию/HTTP/парсинг DOCX/CPU и не заменяют connect/pool-checkout настройки явного engine. Пять минут анализа и две минуты автосохранения остаются отдельными продуктовыми правилами, их таймеры пока не подключены. Retained package/transport budgets не являются гарантией hard RSS. Перед desktop release нужны измерения памяти/отзывчивости на крупных реальных файлах и проверка Windows/macOS.
