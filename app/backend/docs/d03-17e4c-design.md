# D03-17E4C — применение effective скрытий и возврат замечаний

3 ноября 2026. Проект после E4B full4052passed (f13c3e9); не считать реализованным. F09/F12,
текущий продукт тот же. E4A даёт консервативные пары; E4B читает активные origin
references и все aliases без записи. Здесь explicit команды и подключение API.
Разделить на C1 (команды/receipt compatibility) и C2 (HTTP/view/handoff), с отдельными
freeze/red/full/result/commit. Это разбиение одного прежнего интеграционного шага,
не новая ML/Word функция. Пакет модели отсутствует по ответу Никиты.

## Решение о сроке/памяти скрытий

Не писать и не переносить rows при GET. Старые explicit hides остаются привязаны
к исходным verified results. На новом source E4B вычисляет effective keys. Hide
текущего already-effective finding — no-op с новой revision, без лишнего source
row. Unhide текущего finding удаляет **все** активные origin keys, которые E4B
однозначно сопоставил с ним. Это возвращает именно текущее замечание; прочие
скрытия/фильтры не меняются. Повтор старого command возвращает original ack и
ничего не применяет заново, включая после последующего clear.

## Recovery от bounded resolution

E4B limits (64 distinct runs включая target,256MiB records,8Mi text work) могут
быть превышены после накопления history или роста нового source. Нельзя молча
игнорировать часть скрытий или выдавать полную resolution. Оставить явный413
preferences_resolution_limit. Перед HTTP wiring добавить explicit **clear_hidden**:
снять все скрытия данного документа, сохранив filters/result/source. Эта команда
не декодирует модельные origins и работает даже когда resolver не помещается
в budget. Она также работает при повреждённых source/result blobs; повреждение
самой preference/receipt metadata не маскируется. Это узкий технический recovery
для F09 по автономному поручению пользователя, не новое решение команды о ML.
Пользователь выбирает действие явно; чтение и ошибки ничего не сбрасывают сами.

Clear требует того же CAS revision и уникального command UUID. Каждый accepted
command (включая no-op) расходует revision и пишет atomic small receipt. Первое
clear без state создаёт default preferences revision1, changed=false. Старые
receipts не удаляются; очистка скрытий не разрешает повторно применить старый hide.
Технически не нужна миграция: receipt.kind остаётся `unhide`, что точно соответствует
действию, но command_data получает отдельную каноническую схему `docx-review-clear/1`
с явным `operation=clear_hidden`. Она отличима от обычного unhide ещё до mutation.

Новый make_clear(doc,cmd,expected) -> прежний Command(kind=unhide,values={operation:
clear_hidden},data/hash). JSON fields exactly schema_version,document_id,command_id,
expected_revision,kind,operation; UUID/counters canonical strings. Shared E2B
_codec.restored_command расширяется **одной ветвью** по этой schema_version:
лениво вызывает новый restore_clear(body), который проверяет exact fields, kind,
operation и пересоздаёт canonical bytes. Остальной v1 parser неизменен. Existing
read_receipt уже сравнивает saved fields/bytes/hash/response и caller command;
один UUID для clear и old hide/preferences возвращает409, не ложный replay/500.
Нельзя передавать clear body в прежний _commands._apply: это другой explicit entry.
Все старые serialized command/receipt bytes остаются прежними.

## E4C1 — новая service layer

Allowed new `src/ara/docx_review_commands/{__init__,_codec,_commands}.py`;
только dispatch-ветвь нового clear schema в `docx_review_preferences/_codec.py`;
новый `tests/acceptance/test_docx_review_effective_commands.py`; docs. Нет миграций,
изменений E1/E4A/E4B/старых assertions/runner/deps. Core E2B exact set_hidden API
сохраняется для совместимости; новый namespace выбирает effective behavior явно.

`set_hidden(runtime,*,document_id,command_id,expected_revision,run_id,
result_sha256,finding_id,hidden,limits=None)`:
1. Строгий прежний v1 command через E2B make, hidden exactbool; начальный scoped
   V13 tx: original receipt прежде CAS/decode, revision, successful target,
   E4B load_inputs. Конфликт before write, без source decoding под SQL locks.
2. resolve вне SQL; current finding ID должен существовать (404 иначе). Aliases
   только проверенные E4B, никаких arbitrary caller keys. Если hide создаёт новую
   origin group, prospective next read text work включает её old+current pair;
   проверить budget до записи, чтобы команда сама не создавала нечитабельное
   состояние. Record/origin budget уже считает target даже до hide. MAX_HIDDEN10000
   сохраняется. Limits в command identity не включаются: это local execution budget,
   не намерение пользователя; original successful receipt доступен при меньшем budget.
3. Final project-shared/doc-update tx: original receipt снова прежде CAS; revision
   и E4B recheck_inputs (exact active decisions + all origin bundles) повторно.
   No decode под locks. Подтверждённый same-key race возвращает один ack.
4. При hide вставить текущий key/current origin только если effective finding ещё
   виден; при unhide удалить все aliases; остальные rows/filters неизменны.
   Pref revision/time + receipt атомарно. No-op revision+1, limit overflow409.
   Потеря ACK503 безопасно разрешается повтором того же key/body; decode не нужен
   при original replay. Настройки меняются только прежним set_preferences.

`clear_hidden(runtime,*,document_id,command_id,expected_revision)`:
new clear command; one scoped write tx replay→CAS→counter guard→delete all active
rows of doc→prefs revision/unchanged flags+small ack→COMMIT. Не читает origins/ML.
Всё откатывается при fail before COMMIT; unknown successful COMMIT восстанавливается
receipt. Никакой автоматической delete/cascade source/result/receipts.

New writer может переиспользовать E2B codec/response/metadata/scope; не изменять его
старый _apply ради новой семантики. Короткий private helper общего parent/receipt
записывания в новом namespace допустим. Ошибки E2B/E4B fixed messages; unexpected
exceptions sanitized, finite SQL via existing transaction/runtime pool.

C1 tests: real SQL origins from E4B fixture; effective hide no-op; unhide twoaliases;
changed source/severity/model stays visible; initial clear/defaults/reopen;
clear preserves filters/raw/source/history; old hide/unhide/clear replay after
new actions; cross-command UUID conflicts both directions through old/new APIs;
CAS/samekey races; rollback/unknown COMMIT; origin/prefs/ownership change after
resolve no mutation; no locks during decode; bad finding/result/foreign inputs;
cap recovery without codec calls, budgets/prospective admission; corruption safe;
receipt/hash-correct schema tamper; old parser bytes/assertions unchanged.

## E4C2 — HTTP/view integration

Allowed new HTTP/native independent acceptance, changes only hooks in review API
_http/_view/_wire and docs/product technical status. No new pool/gate/lifespan/S.
Existing E3 `/.../findings/.../visibility` calls effective set_hidden namespace;
GET review initial scoped tx adds E4B load_inputs, then resolve outside SQL and
passes effective keys to existing E1 present. Final prefs revision/scope check
remains. Keep _view.present hook and all strict E3 behavior/tests. Extra final
E1 validation is bounded by existing B2 limits; don't claim it is free.

Add POST `/docx-documents/{document_id}/analysis-preferences/clear-hidden`, body
exact command_id/expected_revision; response existing docx-review-http/1 receipt,
kind=unhide. Strict64KiB/canonical UUID/counters/duplicate/query/media/no-store;
same2 ordinary gate (path matcher already covers preferences suffixes), Stop
separate. Add clear_command wire parser and OpenAPI schema; old bodies unchanged.
Default create_app without explicit S still has no analysis/review endpoints.

Frontend guidance: at413 offer explicit clear hidden then reread, filters remain;
no silent auto-clear. Successful unhide removes all corresponding origins, oldack
requires reread, current source evidence still pinned; UI RAM freshness separate.
All findings shown/no_findings/fixture invariants preserved. Clear does not fix an
invalid current result; raw corruption remains error independently of preferences.

Portable HTTP uses valid B3 fixtures and explicitly issued supervisor without real
weights. Native Mac E2E использует существующий fixture без изменений: замечание
в первом абзаце, ручная правка последнего абзаца пятиабзацного документа. Такая
дальняя правка также проверяет correspondence. Подготовка editor capture/save/
recheck подтверждена отдельным synthetic тестом до freeze. Новый test-only ML
adapter не требуется. Native Windows/Word и real ML остаются отдельными gates.

Product update source: current F09 technical implementation under autonomous
instruction, not falsely attributed user answer; main spec remains sole product
scope. Record reset decision and conservative mapping limitations; actual readiness
only after C1/C2 gates. Publish nothing, main V8 unchanged.
