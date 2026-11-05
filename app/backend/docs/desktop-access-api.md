# Защищённый локальный API для desktop

D05-01, 4 ноября 2026. `ara.desktop.access.LicensedApplication` оборачивает
существующий DOCX/editor/analysis API. Это компонент запуска приложения; готовый
установщик, публичный сервер лицензий и frontend этим не создаются.

## Native bootstrap

1. Создать один новый LicenseClient для процесса и подготовить inner app через
   `create_app(document_runtime=..., analysis_supervisor=...)`.
2. Выбрать фактический свободный порт на127.0.0.1. Сгенерировать
   `new_session_token()` —32 случайных bytes, только в памяти запуска.
3. Создать `LicensedApplication(inner, client, origin="http://127.0.0.1:<port>",
   session_token=token)`; слушать ровно127.0.0.1, выключить proxy_headers и access_log.
4. Передать доступ доверенному native bridge по IPC. Не помещать token в URL,
   файл, cookie, командную строку, stdout или браузерный localStorage.
5. При завершении сначала сохранить/выгрузить принятый текст и закончить lifecycle
   приложения. Wrapper не владеет supervisor/engine/license client; закрывает их
   bootstrap, а не произвольный HTTP-запрос.

Каждый запрос передаёт `X-AIRA-Session: token.hex()`. Предпочтительно добавляет его
native bridge. В браузере разрешён только exact same origin; file:// / null Origin,
другая вкладка/порт/домен и CORS preflight не поддерживаются. Frontend на другом
origin должен использовать доверенный native bridge, а не ослаблять проверку.
Static assets старого проверочного workspace wrapper не публикует. Подключение
собранного frontend/его CSP — отдельная часть native host.

Конструктор не вызывает client.start/сеть/файлы. Bootstrap явно вызывает start()
для проверки сохранённой активации. Пока подтверждения нет, данные DOCX закрыты.
Ручное создание wrapper вокруг старого dev app не заменяет подготовку его БД,
правильный lifecycle и конфигурацию модели. Development launcher остаётся прежним.

## Активация и состояние

- GET `/desktop/license` — состояние.
- POST `/desktop/license/activate`, JSON `{"license_key": <введённая строка>}` —
  запустить активацию. Ключ не попадает в inner application.
- POST `/desktop/license/verify`, JSON `{}` — проверить сохранённую активацию.

POST возвращает202 с snapshot попытки; UI опрашивает GET. `checking` не означает
выданный доступ. `activation_required` требует ввода ключа; `failed`/`expired`
содержат безопасный error_code. Retry доступен по retry_available. Повтор того
же незавершённого намерения не создаёт ещё один сетевой worker.

Snapshot: schema_version=aira-desktop-license/1, phase,error_code,license_id,
expires_at_ms (decimal string или null),retry_available,preservation_available.
Ключа/device digest/nonce/offline permit здесь нет. Сохранённый snapshot и локальные
системные часы не разрешают действия: сервер повторно проверяет permit на admission.
Ошибки JSON имеют code/message; клиентские исключения не отражаются пользователю.

License JSON≤1024bytes, до32frames и3s на body; четыре места без очереди.
Ответы всегда no-store/nosniff/no-referrer. Локальные token/Host/Origin failures403;
неизвестный маршрут404; malformed422/media415/size413/timeout408/busy503.
Запрос с неправильным локальным доступом не читает body и не обращается к лицензии.

## Документы и истечение срока

Разрешённые операции — современный DOCX editor API, перечисленный в
[контракте](d05-01-contract.md). Старые Markdown/merge/runs/development endpoints,
сырой DOCX overwrite и старые writers не становятся частью desktop автоматически.
Чужой/неизвестный документ и устаревшие revisions по-прежнему проверяет backend.

После первой подтверждённой лицензии в этом процессе `preservation_available=true`.
Если срок истёк или повторная проверка потеряла сеть, UI закрывает новые create/import,
открытие сессии, команды правки, запуск/retry анализа и изменения скрытия. При этом
сохранение/checkpoint/reconcile/close существующей сессии, DOCX export, чтение результатов
и Stop уже принятого анализа остаются доступны. Ранее принятая транзакция/проверка
может закончиться; wrapper не убивает её в середине записи.

Новый процесс без online-подтверждения не наследует это право. Закрытый LicenseClient
не разрешает и сохранение; native shutdown должен вызываться после flush/export,
а не служить кнопкой «закончилась лицензия».

Гарантия этой границы относится к уже принятому backend тексту. Непереданный DOM/IME
buffer будущего UI нужно сохранять отдельно: корректно обрабатывать отказ команды,
держать несохранённый ввод и давать пользователю его забрать. Пока frontend не готов,
не обещать полную защиту его ещё не переданных изменений.

Проверено отдельно: exact RAM/saved DOCX после expiry; сохранность исходника;
выполняющийся fixture analysis может завершиться или получить Stop после expiry,
новый analysis admission отклоняется. Fixture заметно помечен и не считается
настоящей моделью. Native host/поставка, реальные веса и Windows release gate отдельно.
