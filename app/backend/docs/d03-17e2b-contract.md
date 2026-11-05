# D03-17E2B — атомарная память фильтров/скрытия

3 ноября 2026. E2A завершён полным gate3908, коммит7fd5330. Это следующий
отдельный цикл с independent freeze/red до source, в рамках автономного запроса.
F08/F09, только core storage; HTTP E3 и перенос через изменённый source E4 отдельно.

Allowed: новый namespace src/ara/docx_review_preferences/{__init__,_models,_codec,
_reads,_commands}.py; новая independent acceptance tests/acceptance/test_docx_review_preferences.py;
contract/result/queue. Схема/модели E2A, B1/B2/E1/D, прежние tests/runner/deps
не меняются. Main V8 не мигрировать. Explicit server-owned DocumentRuntime,
без config/file/network import I/O. Только выбранный runtime на explicit call.

## Pure inputs / результаты

get_state(runtime,*,document_id) -> PreferencesState(document_id,revision,
disabled_types tuple,show_questions,show_hidden,hidden_keys tuple/reprFalse).
Absent row=virtual revision0/default([],true,false), read ничего не создаёт.

set_preferences(runtime,*,document_id,command_id,expected_revision,disabled_types,
show_questions,show_hidden) -> PreferenceReceipt.
set_hidden(runtime,*,document_id,command_id,expected_revision,run_id,result_sha256,
finding_id,hidden) -> PreferenceReceipt.

Core UUID objects exact, counters int0..MAX/no bool, strict known types/flags,
E1 prefixes64hex. Canonical command schema docx-review-command/1; sorting type set
считает перестановку одинаковой, другие изменения того же key409. kind
preferences/hide/unhide. Cmd≤16KiB. Caller **не** передаёт dismissal key или scope.
Receipt frozen document_id,command_id,kind,expected_revision,revision,changed.
Stored canonical response schema docx-review-receipt/1,counters strings,≤2KiB;
никакого полного растущего hidden set/result/DOCX на каждый command.

Каждый fresh accepted command расходует revision+1, включая logical no-op.
Одинаковая команда replay возвращает original receipt, даже после последующих
настроек; не откатывает latest state. При MAX reject409, никакого overflow.

## Транзакции и source validation

Caller owns pool/connect timeout (будущий HTTP использует bounded D pool).
Каждая transaction задаёт LOCAL lock_timeout500ms/statement_timeout2s/
idle_in_transaction_session_timeout2s/transaction_timeout5s, требует exactV13,
scope project shared→document shared дляread, projectshared→docupdate дляwrite.
Никакого глобального SET, auto migration или неограниченного фонового retry.

После validation command:
- scoped receipt lookup проверяет stored command/response hashes, canonical shapes,
  все identity/kind/revision поля. Existing equal returns old ack, different409;
  corrupt500. Exact replay не перечитывает historical result/provider.
- Для fresh hide/unhide загрузить successful same-document SourceBundle/AttemptBundle/
  ResultBundle (run/attempt/result identity/hash relations). Non-success409;
  missing/foreign404; caller result_sha256 mismatch preferences_conflict409. После завершенияSQL вызвать E1.finding_keys (полная B2
  revalidation) и найти exact finding_id. Unknown404, corrupt500; никаких prefs
  или receipts до успешной validation. Не доверять source-less findingID.
- Final tx подdocwrite: снова receipt first, current prefs CAS expectedrevision,
  scope/immutable source+attempt+result records recheck на точное равенство ранее
  проверенным bytes/IDs (без parsing вlock); change500. Только затем prefs/hide/
  receipt atomic commit. Owner transfer доfinal scope даёт404 без записи.

set_preferences меняет flags/types, сохраняет hides. hide inserts row только с
проверенным key+origin, если key ужеactive — changedfalse/сохранить originalorigin.
unhide deletes samekey, если отсутствует — changedfalse. Это точный источник;
изменившийся файл/модель не наследует hide здесь. Unknown valid key не вводится
через API. Active hides≤10000/E1 limit, new insert сверх413, никогда не truncate.
get_state проверяет shape/canonical prefs/keys, count≤10000, hidden_at_revision
<=state.revision. Source references сохраняют provenance подтверждённого решения;
исторический анализ не запускается/не декодируется на каждом metadata read.
Текущий отображаемый результат всегда отдельно валидируется B2/E1 в E3.

SQL timestamps finite; revision определяет порядок. Updated_at=max(SQLnow,
previous_updated/created) для constraints при обратном wall jump; это metadata,
не timeout/lease authority. Новые rows explicit timestamps одним SQL sample.

Любая failure rollback сохраняет прежние данные. Неизвестный COMMIT возвращает
safe unavailable, samekey retry разрешает факт поreceipt. Не выдумывать rollback
по отсутствию HTTP ответа. Нет event/log payloads, rawSQL/paths/exceptionsнаружу.
Errors: validation422,not_found404,preferences_conflict409,idempotency_conflict409,
result_not_ready409,preferences_history_exhausted409,preferences_limit_exceeded413,
storage_error500,storage_unavailable503,preferences_schema_unavailable503.

## Independent acceptance

Synthetic realB2 persisted result из D fixture либо equivalent fullyvalidatedflow.
Virtual defaults/no mutation; flags/types preservehides; durable fresh runtime;
exacthide/repeatsamebytes/newattempt/revision; unhide/restore; исходный rawresult не менять (sharedquestions уже проверены E1, интеграцияviews — E3); differentdoc/project/models/source
не смешиваются. Invalid/non-success/corrupt origins no partialstate.

Two writers same revision one winner; samekey concurrent one receipt; changedkey
body409; oldreplay afterlatercommand no revert; precommit rollback; postcommit
lostACK samekey findsreceipt; receipt corruption; owner transfer betweendecode/
commit; invalidbody/counters/MAX/activekeybudget; V12 rejectedwithoutmutation.
No model inference/launch added by preferences. Target/full gate + hashes + main
V8 snapshot + result/localcommit, затем E3 explicit API.
