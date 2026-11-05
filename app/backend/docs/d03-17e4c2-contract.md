# D03-17E4C2 — effective review и явный сброс через HTTP

3 ноября 2026, после E4C1 full4085passed (a91bc63). F08/F09/F12. Команды и resolver уже
проверены отдельно; здесь соединение с optional E3 API и handoff Ане.
Allowed `src/ara/docx_review_api/{_http,_view,_wire}.py`, новые independent tests
`test_docx_review_effective_http.py`, `test_docx_review_effective_http_native.py`,
docs design/contract/result/API guide/queue/current-product-scope (технический
статус F09, источник автономное поручение, не новое согласование команды).
Никаких изменений E1/E2/E4A/E4B/C1/S/native/schema/runner/deps/старых tests.

GET specific/latest review: scoped V13 tx получает prefs,target и E4B load_inputs;
SQL заканчивается до resolve и existing E1 present. В present передаются
resolution.hidden_keys. Final scope/prefs revision recheck остаётся. No GET writes,
raw D results не фильтруются/не меняются. Existing _view.present hook сохраняется;
фикстуры/пустые списки/точные anchors/current durable freshness прежние.
Дополнительная E1 validation после resolver ограничена B2, учитывается как extra
fixed decode поверх8Mi work. Нет resolver cache или новых pool/thread executors.

POST visibility вызывает C1 set_hidden; wire body прежний. Новый POST
`/docx-documents/{document_id}/analysis-preferences/clear-hidden`, exact JSON
command_id/expected_revision,200 existing docx-review-http/1 receipt(kind=unhide).
Strict64KiB/unknown&duplicate keys/canonical UUID/counter/media/query/GET-body rules
прежние; same D admission2 ordinary+1Stop и review limiter2. Default create_app
без explicit S не получает routes. OpenAPI body/200/errors соответствует runtime.

На preferences_resolution_limit413 UI может предложить explicit сброс скрытий;
после выбора пользователя POSTclear и GETreview. Не вызывать clear автоматически,
не изменять фильтры/результаты/текст. Невалидные текущие analysis данные остаются
ошибкой независимо от clear. Oldack replay требует fresh GET, не повторного apply.
На V12 новый clear также503 preferences_schema_unavailable без migration.

Приёмка portable + **native Mac fixture**: multi-paragraph DOCX, save/check/hide,
editor capture caret в последнем paragraph, ручная вставка/save/check; первый
fixture finding не меняется, effective hide сохраняется. Затем showhidden/unhide/
clear/reopen; raw result/source untouched by visibility; model launches только
по explicit checks. Это уточнение предыдущего design: менять fixture на middle
paragraph не нужно, far edit после первого также проверяет correspondence.
Native Windows gate отдельно; real ML без весов не заявляется.

Дополнительные HTTP guards: no-op hide после переносa не создаёт second origin;
снятие aliases из нескольких прошлых records; changed primary visible; raw endpoint
unfiltered; clear preserves filters/raw and old replay never re-hides; malformed
clear commands/query/large/media/counter/UUID; foreignscope; bounded resolver413→
explicit clear recovery; full API native retry/Stop gates прежней E3 приёмки.

Freeze/red до hooks; targeted D/E1/E2/E3/E4+C1 regression, full/hash/mainV8snapshot,
result/локальный commit. После F09 пересмотреть оставшуюся очередь самостоятельно;
не ждать моделей/frontend для независимого лицензирования/поставки/readers.
