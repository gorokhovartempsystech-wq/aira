# D03-17 — DOCX и локальная проверка требований

31 октября 2026, проектирование на Astra 6 High после `3060014`. Основание: команда Никиты продолжить после переключения модели; F05–F12 в current-product-scope.md. Это технический проект будущих циклов. Текущий цикл меняет только этот документ, d03-17a1-contract.md, d03-17-result.md и development-queue.md. Product scope, source, tests, contracts/, БД, dependencies, runner/tasks/progress не меняются. Реализация и запуск ML не объявляются выполненными.

## Проверенные основания

| Основание | Наблюдение | Решение |
|---|---|---|
| docx_editor.SavedTarget, D03-16 | Exact bytes/storage revision/SHA уже связаны с подтверждённым save; новый GET content может вернуть другую версию | Начало проверки принимает конкретный SavedTarget, никогда latest content вместо него |
| docx_package/projection | Main-body projection сохраняет paragraph/spans/table anchors; opaque U+FFFC и notices обозначают пропуски. Stories не извлекаются | Собственный snapshot + учёт покрытия; presence файла не равно полноте анализа |
| contracts/README.md 0.1.0, runs/worker | Markdown/DocumentVersion, Merge/context/change_groups, fixture, default timeout900s, иной lock order | Новый DOCX analysis namespace и таблицы; старые версии/worker не перепрофилировать молча |
| Артём, snapshot `036a4e89027276144c51de14f0cc91412c59f437`, engine/aira_ml/engine.py | Engine.parse_text пропускает headings и строки короче12 символов, strip/remove markers; guess_status исключает архив/обсуждение эвристически | Передавать готовые fragments; не использовать parse_text/parse_file для нашего DOCX |
| Там же Onnx/Engine.review | `enable_truncation(256)`, матрица N×N, top-K candidate NLI; duplicate confidence — cosine; rule text с ISO | Проверять реальные tokenized inputs без truncation; не обещать exhaustive contradiction scan/калиброванную вероятность/проверку ISO |
| Там же serve/engine.schema.json | ThreadingHTTPServer, runtime token в stdout, request limit5MB, нет cancel endpoint; schema допускает лишние поля и не проверяет quote offsets | Закрытый child-process bridge и собственная строгая проверка результата |

Источник зафиксирован по конкретному commit, не утверждение об актуальном удалённом main. Сам модуль движка не импортировался, ONNX/HTTP не запускались, веса не найдены в ранее проверенном снимке. Pure audit исполнил только три просмотренных static AST methods parse_text/guess_status/guess_type: три непустые синтетические строки стали одним fragment. Rich fixture имеет unprojected_part/unprojected_story/unsupported_element. Это свидетельство ограничений, не тест ML качества; .runtime/d03-17-design-audit.json.

## Границы и последовательность

```mermaid
flowchart LR
    S[Подтверждённое сохранение] --> R[Запуск с неизменяемой копией DOCX]
    R --> P[Текст, адреса и проверка покрытия]
    P --> W[Отдельный процесс модели]
    W --> V[Проверка ответа и координат]
    V --> D[Сохранённые замечания и вопросы]
    D --> U[Фильтры и подсветка версии]
    P --> E[Объяснимая ошибка без потери DOCX]
    W --> E
    V --> E
```

Не добавлять Merge/impact/auto-fix/ISO compliance/аккаунты/Confluence/телеметрию документов. Категории движка formulation/duplicate/contradiction — возможности конкретного адаптера, не окончательно согласованная продуктовая таксономия. affected относится к отложенному impact и в review не принимается. Фильтры в первом UI только меняют представление; disabled_types/dismissed движку всегда пустые, все поддерживаемые проверки выполняются. Это позволяет не терять исходные замечания и вопросы. Позднее изменение генерации по фильтрам — отдельное продуктовое решение.

## 1. Неизменяемый snapshot и точные координаты

Identity: document_id + storage_revision + source_sha256 + extractor_version. Bytes проверяются по SHA, сохраняются с run независимо от текущего DOCX. Same bytes в разных revisions имеют разные пользовательские identity, даже если текст/cache общий. `snapshot_sha256` связывает весь manifest: identity, fragments, segments, coverage и synthetic separators. Это digest, не доказательство права доступа.

Первый pure цикл A1 строит `main-body-v1` поверх существующего project_docx. Каждый поддержанный непустой paragraph становится отдельным fragment, включая headings, короткие строки, list-item и paragraphs внутри физических ячеек/вложенных таблиц. Текст не trim/normalize/переводится в Markdown; внутренние TAB/LF сохраняются. На этом этапе synthetic list labels/табличные headers не дописываются в текст. В строке analysis_text fragments соединены двумя LF; separators не имеют Word anchors. IDs — полный SHA256 от source SHA/part/path с префиксом f-, различают одинаковый текст в разных местах, действуют только внутри snapshot. Никаких обещаний постоянства F001 после split/join.

Каждый fragment хранит paragraph anchor, ordered structural ancestry и nonzero spans: text/tab/break, local [start,end), original SourceAnchor и run anchor при наличии. map_span требует точное равенство quote == fragment.text[start:end], целые code-point offsets, 0≤start<end≤len. Возвращает paragraph range и ordered пересечения с исходными spans; несколько runs допустимы. Не искать цитату по всему документу, не выбирать первое совпадение и не исправлять offsets автоматически. В UI нужен явный перевод code points↔UTF-16, с проверкой source SHA; XML UTF-8 bytes не являются text offsets.

Paragraph с opaque span целиком блокируется для анализа в A1: не отправлять U+FFFC или склеенный текст по сторонам неизвестного элемента. OpaqueBlock и notices становятся coverage records. Empty/whitespace-only p учитывается как empty, не как проверенное требование. Text literal U+FFFC в обычном w:t не является opaque: решение по span.kind. Таблицы обходятся row/cell/block в физическом XML-порядке; текст объединённой ячейки не размножается на gridSpan/vMerge. Рендер, вычисление layout/номеров и смысловое восстановление строк таблицы не следуют из этого обхода.

Coverage имеет уровни: `included`, `empty`, `blocked`. A1 complete=true только при отсутствии blocked и projection.has_unprojected_content=false. Пустой snapshot может быть complete, но запуск с нулём fragments получает empty_document. Complete здесь означает покрытие заданного extractor profile, не успешность ML. Snapshot builder сам никогда не говорит «Замечаний нет».

### Расширение покрытия A2

A1 — строительный этап, не выполнение полной DOCX matrix. A2 получает отдельный контракт инвентаризации всех text-bearing OPC parts и чтения stories: headers/footers/footnotes/endnotes, text boxes/SDT, field results, comments и revisions. Сначала классификация всех parts/relationships, затем поддержка по отдельным A2a/A2b подциклам. Unknown/unsupported остаётся blocking, без сетевого разрешения external links. Images без текста — accounted non-text (OCR исключён); text boxes/captions рядом с ними — отдельный текст, его нельзя объявить картинкой и пропустить.

Word comments и tracked changes не равны замечаниям AIRA. Уточнение Никиты 1 ноября: анализировать итоговый текст (включать добавленное, пропускать удалённое); комментарии сохранять, не анализировать. Это не принятие/удаление revision markup в файле. Политика снимает продуктовый вопрос, но не даёт готового reader: до его отдельной реализации affected input остаётся unsupported_analysis_content. A1/строгие DTO/fixtures/lifecycle независимы, full DOCX scope сохраняется.

Пользовательская проверка пока запрещает succeeded при blocking coverage. Возвращается понятная ошибка с перечислением типов неподдержанного содержимого, сохраняется предыдущий результат. Не вводить исключённый продуктовый «режим частичной проверки» и не показывать частичный успех как полный. Разрешить положительный анализ rich DOCX можно только после доказанного покрытия соответствующих parts, а не отключением gate.

## 2. Запуск и хранение выбранной версии

Новые внутренние модули: ara.docx_analysis (pure snapshots/result validation), ara.docx_analysis_runs (scoped durable lifecycle), ara.docx_analysis_worker (explicit supervisor/adapter). Старые ara.analysis_contract, runs/reviews/worker и contracts0.1 остаются совместимыми. Новый wire contract имеет собственную версию `docx-review/1`; output Артёма v1 — вход адаптера, не готовый frontend DTO.

Будущий POST `/docx-documents/{document_id}/analysis-runs` принимает стабильный client_request_id и saved identity: registry/session/save command IDs, resulting command/session counters, storage_revision/SHA. Внутри scope сначала проверять durable idempotency record — lost creation ACK должен повторяться после restart/истечения RAM session. Подмена тела с прежним ключом409; fresh request получает SavedTarget из registry, а не client bytes/произвольный storage revision. Затем short project→document transaction сохраняет immutable source и run. Не держать actor mutex/SQL locks во время extraction/ML.

Изменение current после захвата target не подменяет source. Проверяется явно выбранная версия; UI помечает результат устаревшим, если текущая RAM/current SHA/revision отличается. Ошибка источника/размера до enqueue ничего не создаёт. Same client_request_id возвращает исходный run при любом его status. Один active run на документ (partial unique index queued/running/cancel_requested), другая попытка получает409 analysis_in_progress; её ключ не считается принятым. После завершения пользователь может явно запустить новую проверку с новым ключом, в том числе того же файла.

Будущие отдельные таблицы (точный DDL freeze в B2): docx_analysis_sources (docid+SHA immutable BYTEA, без междокументного dedup), docx_analysis_runs (source revision, profile, request fingerprint, status/deadline, active attempt/lease), docx_analysis_attempts (fence/generation/execution kind), docx_analysis_results (unique run, validated immutable JSON+digest), позднее preferences и dismissals. Source equality проверяется bytes/hash; конфликт hash/data500, не доверять client digest. FK привязывают всё к конкретному DOCX/project. Пакет модели закреплён content digest, а не только manifest.version. Старые successful results не переписываются при неудачной проверке.

Snapshot JSON детерминированно создаётся worker из pinned source/profile, валидируется перед сохранением. Нельзя обновить extractor/model version посередине run. Не хранить source text/credentials в logs/error/attempt metadata; text/results находятся только в scoped storage. Technical budgets задаёт сервер. Initial admission: source≤32MiB, canonical request≤8MiB, fragments≤512, total fragment chars≤1M, result≤8MiB/issues≤10000/questions≤10000. Это обратимые пределы первого адаптера, не согласованный продуктовый max; oversize сообщает техническую ошибку, ничего не обрезает. Утверждение о RAM/скорости требует измерений до релиза.

## 3. Worker, отмена и пять минут

Новый run получает created_at/deadline_at=created_at+300s в PostgreSQL: ожидание в очереди, extraction, загрузка модели, вычисление, валидация и публикация входят в этот срок. Не наследовать900s старого worker. Глобально один active ML child на app instance; очередь других документов ограничена server admission (initial16 queued). Deadline не сбрасывается при claim/retry/restart.

States: queued→running→succeeded|failed; queued→cancelled; running→cancel_requested→cancelled. Deadline любого nonterminal состояния →timed_out. User cancel принимается, если terminal result ещё не committed; обработчик блокирует project→document→run и устанавливает fence. Completion под тем же порядком locks заново проверяет owner/source/run, active attempt, lease и deadline свежими DB clock; cancel/expiry/потеря ownership исключают публикацию. Поздний child output discarded. Не считать cancelled/timed_out/failed успешным «0 issues».

Claim/heartbeat/complete/reaper всегда одинаковый lock order project→document→run→attempt; предварительный nonlocking lookup IDs не даёт права записи и перепроверяется под locks. Не копировать обратный run→document→project порядок старого worker. Lease initial15s, heartbeat≤5s, ≤deadline; lease loss fences результат и завершает owned child. После crash running не перезапускается автоматически как будто ничего не было: reaper ставит failed interrupted (или timed_out при deadline). Пользовательский Retry создаёт новый run с новым ключом и явной ссылкой на исходный pinned source; fresh «Проверить текущий документ» сначала делает новый save. Транспортный retry создания/остановки сохраняет прежний ключ и не даёт новый бюджет времени.

При DB unavailable completion не публикует неподтверждённый результат в UI; bounded retry публикации возможен лишь пока lease/deadline действуют. При неизвестном commit исходе сначала read/reconcile по run/attempt/result digest, не повторять inference. Reaper обязан обслуживать очередь без открытого UI; read endpoint может дополнительно материализовать истечение времени, но не быть единственным таймером.

Недоступность БД не должна оставлять локальное вычисление после Stop: supervisor немедленно ставит необратимый local cancel latch для owned attempt и прекращает его child, даже если durable cancel fence ещё не удалось подтвердить. Пока исход SQL неизвестен, UI показывает неподтверждённую остановку/ошибку связи, не выдуманный terminal ACK; затем тот же cancel intent reconciles с БД. Local latch запрещает публикацию сохранённого ответа этой попытки. Если result успел committed раньше cancel, read возвращает фактический succeeded, а не переписывает историю. После потери процесса действуют lease/reaper fences. При claim дополнительно фиксируется monotonic budget оставшегося DB deadline; последующие heartbeat не увеличивают его, сдвиг wall clock назад не продлевает локальный run.

Progress только подтверждённые стадии: queued, preparing_document, loading_model, analyzing, validating_result, finishing. Процент и выдуманные внутренние «лексика/логика» не рисовать. Terminal state и result публикуются одной SQL transaction. Latest result выбирается по latest successful **accepted run order**, не по времени запоздалого ответа; при одном active run на документ проще сохранить порядок. Scope/DELETE races —409/404 без чужих данных.

### Закрытый child-process bridge

Выбран наш thin bridge вокруг pinned `Engine(...).review(fragments, disabled=(), dismissed=())`. Upstream HTTP serve/parse_file не вызываются. Bridge запускается только явно supervisor, `shell=False`, доверенный installer-resolved executable/module/model path, закрытый environment allowlist, без загрузки .runtime/team source в production. Package code/hash/license/distribution checks выполняются перед real gate. Не менять remote репозиторий Артёма или его HTTP контракт из этой задачи.

Один owned child обслуживает одну попытку, затем завершается. Это первая проверяемая стратегия отмены; загрузка моделей входит в300s и требует benchmark. Постоянный model pool возможен отдельной оптимизацией с таким же fence/cancel. Desktop bootstrap по F02 (запуск модели при старте приложения) требует отдельного контракта и остаётся обязательным: этот supervisor для проверок сам по себе F02 не закрывает. Pipe protocol `aira-worker/1`: length-prefixed bounded UTF-8 JSON messages, explicit attempt UUID/profile/model digest, ready/result/error; stdout pipe содержит только protocol и не транслируется в пользовательский лог. Никаких runtime auth tokens, публичного listening port, document path arguments или временных plaintext файлов. Runtime secrets не нужны; если будущий adapter требует внешние credentials — только ~/secrets.env по явному запуску, не import.

Child не имеет DB credentials и не пишет результат в storage. Supervisor постоянно ограничивает stdout/stderr bytes, не накапливает неограниченный stderr/не выдаёт его в errors. Unexpected frame/extra fields/oversize/exit — sanitized adapter_error. Детали text/quotes доступны только результату, не diagnostic traces. Отмена/deadline: fence в БД, затем terminate owned process и ограниченное ожидание≤2s, при необходимости kill; новый child только после подтверждения выхода предыдущего. Это ограничивает cooperative grace, но не обещает мгновенный syscall при сбое OS.

Parent death должен закрыть private control pipe; отдельный reader/watchdog child обнаруживает EOF и завершает процесс даже при работающем inference. Дополнительно C1 фиксирует и проверяет process ownership primitive для Windows/macOS (job/process group/lifetime lock). Не убивать процесс по сохранённому голому PID после restart: возможен PID reuse. Если ownership не доказано, runtime_busy и диагностика без чужого kill. Проверка обеих платформ — release gate, macOS-only тесты не доказывают Windows teardown.

### Запрет скрытого truncation

В bridge оборачиваются per-instance emb/nli/pair runners. До реального ONNX call каждый **фактически отправляемый** single/pair input токенизируется exact tokenizer с отключёнными truncation/padding; specials учитываются, len≤256. Actual inference tokenizer тоже без truncation; padding не превышает проверенный batch max. Guards не основаны на количестве символов/«128 токенов на половину». Пары проверяются в обе стороны именно в выбранных движком вызовах. Превышение даёт model_input_limit_exceeded и ни одного successful result, даже если предыдущие стадии уже посчитаны. Не разбивать требования автоматически на куски: это меняет смысл противоречий. Missing tokenizer/manifest/hash mismatch/недоказанная конфигурация запрещают real call. Fake tokenizer/adapter tests явно fixtures, не доказательство ONNX качества.

## 4. Строгий ответ и отображение

Собственный валидатор stronger than upstream JSON Schema: canonical version/hash, nonempty IDs, finite numbers (bool не number), known review types/severity/light, unique upstream IDs, bounded nested fields, exact fragment membership. `checked.fragments == checked.active == submitted_count`, skipped_status=0 при всех status=active; mismatch invalid_result. Status для нашего DOCX initial active у всех fragments, без эвристического скрытия «Архива». type='фрагмент', document='Документ' в будущем bridge для main-body-v1: неизвестные table/header semantics не угадывать. Уточнение context-aware классификации требует A2/profile версии; A1 сам bridge не реализует.

Primary span строго проверяется map_span. Related для pinned v1 обязан ссылаться на другой submitted fragment и его полный exact text; контекст/статус совпадают. Для duplicate/contradiction related обязателен; formulation не притворяется двухсторонним доказательством. Нет offset repair/первого совпадения/тихого пропуска плохого issue. Любой invalid issue блокирует публикацию всего результата. Top-level questions равно множеству непустых issue.question; локальные question IDs связываются с origin issues, не теряются при dedup текста.

Новый app DTO: source identity/profile/model/attempt provenance, execution_kind=fixture|local_model, findings с локальным полным digest ID/type/severity/assessment/explanation/primary и related addresses, questions с source finding IDs, coverage ledger, counts. raw upstream rule/confidence/suggestion можно сохранять только как bounded private provenance; пользовательский API не предоставляет apply endpoint, ISO badge или «95% истинности». Light допускает осторожную формулировку assessment, не математическую вероятность. `no_findings` true только для validated complete local_model result с0 findings и0 questions; fixture всегда учебный. Если все findings скрыты/отфильтрованы, это отдельное состояние «нет видимых замечаний», исходный count остаётся.

Freshness проверяется по exact source identity/hash с текущим RAM и durable current; несовпадение означает stale. Старую подсветку не переносить на новую версию по quote search. Просмотр сохранённого результата возможен вместе с его pinned source; новый анализ не выдумывать при reopening. Ошибка нового run сохраняет прежний successful result с его source/freshness.

## 5. Скрытие и фильтры

Preferences scoped документом, UI filters только presentation. Скрытие — отдельная CAS/idempotent команда по validated finding ID/result ID; связь с исходным immutable result обязательна. Скрытый finding не удаляется, решение переживает закрытие приложения; возврат возможен отдельной explicit командой. Engine dismissed=[] всегда, чтобы новое issue не исчезло до нашей проверки identity.

На той же exact source/model/profile hide повторяется по собственному fingerprint: type/severity/assessment, exact primary+related paragraphs/ranges/quotes, explanation/question/rule identity и модель/adapter digest. Не доверять upstream40-bit issue ID как единственному ключу. Более сильная severity/новый related/смена модели или правила образуют новый finding.

Между source revisions перенос допустим только через детерминированное однозначное соответствие неизменённых evidence fragments в том же документе: exact full paragraph text, structural kind/ancestry context, соседние текстовые context hashes и монотонный порядок. Все primary/related evidence и их ranges должны пройти соответствие; повторяющиеся/двусмысленные candidate keys, смена таблицы/раздела/контекста, split/join или изменение evidence запрещают автоматическое скрытие. Нельзя выбирать ближайший/первый match или скрывать категорию целиком. Это консервативное сопоставление текста, не семантическое доказательство эквивалентности. В E отдельная frozen матрица moved/inserted/duplicate/split/context cases до кода; сомнение возвращает замечание пользователю.

## Подциклы и проверки

| Цикл | Выход | Условие старта/режим |
|---|---|---|
| D03-17A1 | Pure main-body snapshot/coverage/map_span без ML/SQL/HTTP | Реализован 1 ноября, [результат](d03-17a1-result.md), Sol6.1 High |
| A2a/A2b… | Inventory и дополнительные DOCX text stories/контекст, отдельные coverage profiles | A2a реализован; A2b [спроектирован](d03-17a2b-design.md) 1 ноября, следующий [контракт b1](d03-17a2b1-contract.md) |
| B1 | [Реализован](d03-17b1-result.md): docx-review/1 request/result validation, strict new schema, source-backed mapped evidence/semantic IDs/questions | Gate2704+24, main V8 unchanged; реальная модель не запускалась |
| B2 | Новый DDL source/run/attempt/result, migration/replay/scope/lock order | Следующий архитектурный pass на Astra6 High по handoff B1, затем implementation Sol6.1 High. Frozen DDL до source, disposable real PG; main не мигрировать автоматически |
| B3 | Start/read/cancel/reconcile/reaper и immutable target pin, идемпотентность | Real PG cut points, exact saved target и restart, Sol6.1 High |
| C1 | Supervisor/IPC/lifetime/deadline с fake child | Real subprocess fixtures, bounded stdout/deadlock/cancel/orphan tests, Sol6.1 High |
| C2 | Pinned Engine bridge/token guard/pack manifest; затем real model gate | До весов fixtures; engine import только в child, dependencies отдельно |
| D | End-to-end API results/freshness/questions/empty state | Complete coverage + validated result; UI handoff для Ани, Sol6.1 High |
| E | Persistent filters/hide/unhide и консервативный перенос | Отдельный exact contract/fixtures/conflict matrix, Sol6.1 High; при неоднозначности Astra |
| F | Real model corpus/performance, Word/Windows/macOS release checks | Зависит от weights/front/packaging; не объявлять fixture готовым пилотом |

На старте дизайна точный контракт был только у A1; 1 ноября A1 и A2a реализованы отдельными проверенными циклами. Каждому последующему подциклу требуется свой allowed paths/contract/frozen acceptance перед code; эта таблица не разрешает смешать SQL/ML/UI в один шаг или менять старые tests/dependencies. Типовые проверки: headers/короткие строки/повторяющийся текст/emoji/combining/soft breaks/mixed runs/nested merged cells; opaque/stories/revisions accounting; MAX/canonical/repr/zero I/O/budgets; token limit actual pair; malicious/malformed reply/NaN/quote mismatch; source change while checking; loss before/after enqueue/complete/cancel; deadline/cancel/owner-transfer races; stale worker fences; same key altered body; damaged stored source/result; stderr flood/child crash/parent death; dismissal across duplicate paragraphs/version/model change.

## Готовность и дальнейшая работа

Дизайн не подтверждает full DOCX/ML/desktop readiness. Реальные weights/packaging, корректный final-view reader по согласованной policy, UX Ани и Windows process lifetime — явные оставшиеся gates. По разрешению Никиты отсутствие weights блокирует только real inference/benchmark, а не независимый код. A1/A2a выполнены на Sol6.1 High; A2b спроектирован 1 ноября на Astra6 High, [результат](d03-17a2b-result.md). Выбран новый profile/multi-source ranges без изменения A1; следующий b1 реализовать на Sol6.1 High по отдельному контракту. Не менять frozen A1 или упрощать scope ради зелёного gate.
