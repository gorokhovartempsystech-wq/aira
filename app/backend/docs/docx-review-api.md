# DOCX review API — handoff для интерфейса

3 ноября 2026, D03-17E4C2. Это локальный проверочный API; frontend Ани и реальная
модель не объявляются готовыми. Подключение выполняется только вместе с явно
переданным `analysis_supervisor` в `create_app`. Bootstrap отвечает за V13,
start/shutdown supervisor; API не мигрирует базу и не запускает процессы сам.
Текущая рабочая база проекта остаётся V8. Базовый API анализа описан в
[docx-analysis-api.md](docx-analysis-api.md).

## Сценарий интерфейса

После успешного run запросить `GET /docx-documents/{doc}/analysis-review` для
последнего успешного результата либо `/analysis-runs/{run}/review` для конкретного.
Ответ `docx-review-http/1` содержит `run`, `preferences`, `view`, `view_sha256`,
`current_storage_revision`, `current_sha256`, `matches_saved_document`, `fixture`.
`view` — проверенный `docx-review-view/1`: findings/questions, точные координаты,
counts, hidden_finding_ids, no_findings/no_visible_findings и provenance.
Служебные rule/confidence/suggestion не отдаются. `view_sha256` относится к
каноническому JSON view, а не ко всему ответу HTTP.

`matches_saved_document` сравнивает с сохранённым DOCX; несохранённый RAM-текст
интерфейс проверяет отдельно через редактор. Старые anchors нельзя переносить
по поиску похожей цитаты. `fixture=true` явно показывать как учебный результат.
Пустой список после фильтрации не означает, что исходная проверка ничего не нашла.
При отсутствии результата404; незавершённый конкретный run409. Предыдущий
успешный результат остаётся доступным, пока новая проверка выполняется/ошиблась.

## Настройки и команды

`GET /docx-documents/{doc}/analysis-preferences` возвращает preferences:
document_id, revision, disabled_types, show_questions, show_hidden.
До первой команды revision="0", типы включены, вопросы видны, скрытые не видны;
чтение не создаёт запись. UUID и revision передаются каноническими строками.

`POST /docx-documents/{doc}/analysis-preferences`:
```json
{
  "command_id": "<новый UUID>",
  "expected_revision": "0",
  "disabled_types": ["formulation"],
  "show_questions": true,
  "show_hidden": false
}
```
Это полная замена трёх настроек, не patch. Допустимые типы текущего адаптера:
contradiction, duplicate, formulation. Фильтры меняют только представление;
исходные замечания, вопросы и запрос модели сохраняются.

`POST /docx-documents/{doc}/analysis-runs/{run}/findings/{finding}/visibility`:
```json
{
  "command_id": "<новый UUID>",
  "expected_revision": "1",
  "result_sha256": "<view.stored_result_sha256>",
  "hidden": true
}
```
Для возврата hidden=false. Finding берётся из проверенного view, result hash —
из его stored_result_sha256. Передавать dismissal key не нужно и нельзя.
При повторной проверке скрытие сохраняется и после изменения другой части
документа, когда E4 однозначно подтвердил прежний фрагмент, его контекст и смысл
замечания. Изменение самого абзаца, существенного контекста, модели или неоднозначное
совпадение не скрывает новое замечание. Поддерживается текущий main-body profile;
это не поиск похожей цитаты. Повторное hide уже скрытого finding даёт no-op;
unhide снимает все соответствующие решения из прежних проверок данного документа.

`POST /docx-documents/{doc}/analysis-preferences/clear-hidden`:
```json
{
  "command_id": "<новый UUID>",
  "expected_revision": "2"
}
```
Это явное действие «Вернуть все скрытые»: снимает все скрытия документа, сохраняя
фильтры, текст и результаты. Ответ receipt.kind="unhide". Его можно предложить
после413 `preferences_resolution_limit`, когда история соответствий превышает
технический бюджет. Не вызывать автоматически. Сброс не исправляет повреждённый
текущий результат анализа: для него сохраняется ошибка данных.

Все три команды200 возвращают `{schema_version,receipt}`: document_id,command_id,
kind,expected_revision,revision,changed. Каждый новый принятый command расходует
revision, включая no-op. Повторить тот же key/body после потери связи безопасно:
вернётся исходное подтверждение без повторного применения. Старый receipt не
означает текущее состояние: затем прочитать preferences/review заново.
В частности, повтор старого hide после clear возвращает старый ack, но не скрывает
замечание заново. GET review вычисляет соответствия без записи новых решений.

При409 preferences_conflict перечитать состояние и сформировать новую команду
с новым UUID, учитывая выбор пользователя. Тот же UUID с иным body даёт409
idempotency_conflict. При503 после команды исход COMMIT может быть неизвестен:
повторять тот же body/key. Нет молчаливого повторного анализа/автофикса.

## Ошибки и ограничения

Все ответы no-store; strict JSON≤64KiB, без лишних/повторных полей, queryparams,
GET-body или некорректных UUID/счётчиков. Два обычных запроса делят ограниченный
пул, Stop имеет отдельное место; при занятости503 analysis_busy. Во время чтения
view настройки могли измениться:409 preferences_conflict просит перечитать
результат. Смена владельца проверяется повторно перед выдачей ответа.

404 — чужой/неизвестный документ/run/finding или отсутствие successful result;
409 — конфликт/неготовый result;413 — технический предел;415 — media;
422 — форма запроса;500 — повреждённые сохранённые данные;503 — занятость,
недоступная база или preferences_schema_unavailable. На V12 прежний API анализа
работает, review routes требуют V13 без автоматического upgrade.

Не сохранять текст документа в логи ошибок. Raw `/analysis-result` и
`/analysis-runs/{run}/result` остаются неизменными: они отдают полный исходный
результат независимо от фильтров/скрытия.
