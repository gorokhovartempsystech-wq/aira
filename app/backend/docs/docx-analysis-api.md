# Подключение проверки DOCX к редактору

D03-17D, 3 ноября 2026. API опционален и пока работает с **учебным** supervisor.
Настоящие веса модели не предоставлены; это не готовый ML-анализ и не релиз UI.

## Bootstrap

Передать `create_app(document_runtime=runtime, analysis_supervisor=supervisor)`.
Оба объекта принадлежат одному серверному user/project/database. Default app без
этого аргумента сохраняет прежний набор маршрутов. Bootstrap отдельно готовит
тестовую/поставляемую БД, явно запускает supervisor и дожидается ready. HTTP
не мигрирует БД и не запускает процессы при установке routes. Shutdown приложения
закрывает свой read pool; start/shutdown supervisor остаются у bootstrap.
Local-dev labels сохранены; это не активация лицензии и не авторизация.

## Кнопка «Проверить»

1. Сохранить editor session через её `/save` с новым command_id; при потерянном
   ответе сначала `/reconcile` той же команды. Не анализировать неподтверждённый save.
2. Из успешного save взять registry_id, session_id, command_sequence,
   document.session_revision, base_storage_revision и base_sha256.
3. POST `/docx-documents/{document_id}/analysis-runs`:

```json
{
  "client_request_id": "<новый canonical UUID>",
  "registry_id": "<registry_id>",
  "session_id": "<session_id>",
  "save_command_id": "<command_id подтверждённого save>",
  "command_sequence": "<command_sequence после save>",
  "session_revision": "<document.session_revision после save>",
  "storage_revision": "<base_storage_revision>",
  "source_sha256": "<base_sha256>"
}
```

Пример показывает подстановки, не готовый валидный запрос. UUID должны быть
строчными canonical UUID; counters — десятичные строки, SHA —64 lowercase hex.
После сетевого сбоя повторить тот же key и **то же тело**, не создавать новый key.
Другой body с известным key — конфликт.

202 подтверждает намерение, а не транзакцию. Читать `Location` через GET:
`phase=admitting`, `run_id=null`, `state=null` — допустимое ожидание. Затем
queued/active/settling/finished. `state` содержит только подтверждённые SQL
metadata; pending не означает, что записей в БД точно нет. not_admitted и safe
error_code показывают неудачный admission. Новый явный POST того же непринятого
намерения может повторить admission; автоматически гонять его бесконечно не надо.

## Остановка и повтор

POST `{Location}/stop` с `{}` возвращает202 и `stop_requested`. Это локальное
намерение; дождаться SQL `state.status=cancelled` либо другого окончательного
исхода. Уже опубликованный результат остаётся успешным. Известный ticket
останавливается независимо от чтения БД и выдачи больших результатов. Незнакомый
активный запуск после перезапуска требует recovery; HTTP не получает право
убивать процесс по произвольному run_id.

Повтор анализа после terminal: POST
`/docx-documents/{document_id}/analysis-runs/{run_id}/retry` с единственным
`client_request_id`. Он проверяет сохранённый источник старого запуска. Чтобы
проверить новый текст, снова save→POST analysis-runs, а не retry старого run.

## Результаты

GET `/docx-documents/{document_id}/analysis-runs/{run_id}` — metadata.
GET того же пути +`/result` — проверенный успешный результат; иначе409.
GET `/docx-documents/{document_id}/analysis-result` — последний успешный run по
accepted_order. Неудачный новый запуск не стирает прежние замечания.

`result` — docx-review/1 без private_provenance. Точные адреса primary/related,
questions, counts, coverage и provenance сохраняются. `fixture=true` требует
явной пометки «Учебный пример». confidence/rule/suggestion не выдаются.
`stored_result_sha256` относится к полному сохранённому envelope, а не к JSON
после удаления приватных полей.

`current_storage_revision`, `current_sha256`, `matches_saved_document` описывают
совпадение с сохранённым DOCX в момент чтения. Несохранённые изменения в RAM нужно
сравнить с editor state отдельно. Не переносить старую подсветку поиском похожей
цитаты. Ответ всегда сверяет result/source/request hashes и заново проверяет
scope после декодирования. Повреждённый результат даёт500 без частичных замечаний.

JSON request ≤64KiB. Лишние поля/параметры, duplicate keys, GET body и неверные
media/encoding отвергаются. Ответы no-store. Одновременно допускаются2 обычных
HTTP операции и1 Stop; лишние получают503 analysis_busy без очереди. Формат
описан в OpenAPI. Фильтры и запоминаемое скрытие — следующий отдельный этап E.
