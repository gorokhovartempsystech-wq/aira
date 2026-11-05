# D03-17E4C1 — команды effective hide/unhide и явный сброс скрытий

3 ноября 2026. Цикл после полного E4B gate4052passed (f13c3e9); F09/F12. Дизайн в
[d03-17e4c-design.md](d03-17e4c-design.md). Здесь только service/receipts,
HTTP integration отдельно C2. Настоящей модели/новых UI/миграций нет.

Allowed new `src/ara/docx_review_commands/{__init__,_codec,_commands}.py`,
одна dispatch-ветвь `docx-review-clear/1` в существующем
`docx_review_preferences/_codec.py::restored_command`, новый
`tests/acceptance/test_docx_review_effective_commands.py`, docs contract/result/
design/queue. Старые v1 bytes/parser semantics, E2B set_hidden, E1/E4A/E4B,
source/schema/tests/runner/deps сохраняются. Work main V8 не мигрировать.

## Входы/выходы

`set_hidden(runtime,*,document_id,command_id,expected_revision,run_id,
result_sha256,finding_id,hidden,limits=None)` — строгие прежние аргументы v1,
возвращает прежний PreferenceReceipt. `limits` E4B ResolutionLimits, technical
execution budget, не часть semantic command identity. Valid smaller limit не
мешает old successful replay. New hide на already-effective target даёт
changed=false/revision+1 без duplicate origin. Unhide удаляет все aliases этого
current finding, оставляет остальные hides/filters/results. Не переносить rows
автоматически при чтении или новом анализе. Не добавлять caller-controlled keys.

Две scoped transactions: read receipt→CAS→target/E4B load_inputs; resolve внеSQL;
write receipt→CAS/counter→E4B recheck_inputs→atomic prefs/dismissals/receipt.
Final recheck проверяет all origins/active refs, без parse под lock. Same-key
concurrency один ack; different-key same revision409. Unknown COMMIT503→retry
samebody/key, original replay не требует source/decode. MAX_HIDDEN10000 и revision
2^63-1 сохраняются. Перед новым hide проверить prospective text work следующего
resolution: если target run ещё не активный origin, добавить2*target analysis_text
к уже проверенной работе. Record/origin limits E4B уже учитывают target. Проверка
вне SQL перед mutation; no-op ничего не раздувает.

`clear_hidden(runtime,*,document_id,command_id,expected_revision)` — explicit
снять все скрытия данного документа. Нужен recovery от накопления origin/work
budget: raw results/source/filters/receipts сохраняются; source codecs/ML не нужны.
Отказ/GET никогда не сбрасывает решения автоматически. No-op также revision+1,
первый clear создаёт default state. Metadata corruption/receipt corruption не
маскировать. Нет удаления истории результатов или reset command UUID namespace.

Clear Command: schema_version=docx-review-clear/1, document_id/command_id canonical
UUIDstrings, expected_revision decimalstring, kind=unhide, operation=clear_hidden.
Exact six fields; canonical data/hash≤16384. DTO прежний Command с kind=unhide и
values={operation:clear_hidden}. Новый make_clear/restore_clear. Shared
restored_command только по этой schema вызывает новый strict restore_clear;
весь прежний код ниже ветви неизменен. Existing read_receipt проверяет saved body,
identity/bytes/hash/response и caller intent. Clear/v1 reused UUID →409 в обе
стороны, не500. Existing response schema docx-review-receipt/1 unchanged.
Старый _commands._apply не вызывается с clear command.

Clear одна scoped write tx с replay первым, затем CAS/counter/defaults/delete
active rows/parent revision+time/receipt. COMMIT атомарен, unknown outcome safe
retry. Runtime/pool/SQL bounds E2B; safe fixed DocumentErrors, no external startup,
config/secrets/files/network. Результат — проверенный backend, не готовый frontend.

## Frozen acceptance

Defaults/noop clear; effective hide no duplicate; unhide all aliases; changed
source leaves unrelated origin; filters/source/raw/history preserved; explicit
clear works despite resolution budgets/origin corruption without codecs;
old hide/unhide/clear replay после нового состояния; shared key conflicts old/new
both directions; same/differentkey races; precommit rollback/aftercommit loss;
owner/prefs/origin change afterdecode, no SQL locks duringdecode; scope/finding/hash/
strict guards; counters/cap/prospective text work; hash-correct receipt clear schema
corruption. Existing E1/E2/E4A/E4B assertions unchanged. Freeze/red→regression/full→
hash/mainV8 snapshot/result/localcommit; затем C2 HTTP без остановки режима.
