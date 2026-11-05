# Сервер лицензий — оператор и клиентский контракт

4 ноября 2026, D04-02. Отдельный компонент; он не хранит документы и не запускает
модель. Это код сервера и локальная приёмка, публичный адрес/сертификат/развёртывание
не подготовлены. Старый local editor пока не подключён к этому серверу.

## Подготовка оператором

Нужна отдельная PostgreSQL18 БД. В ~/secrets.env оператор задаёт только необходимые
настройки: AIRA_LICENSE_DATABASE_URL (postgresql+psycopg), AIRA_LICENSE_PEPPER
(случайные32–64bytes в hex). Для выдачи одного ключа дополнительно
AIRA_LICENSE_ISSUE_KEY в формате AIRA-XXXXXXXX-XXXXXXXX-XXXXXXXX-XXXXXXXX,
где32hex-символа генерируются случайно. Не передавать секреты в аргументах процесса,
логи или репозиторий. Pepper должен сохраняться: замена без отдельной миграции
лишит сервер возможности найти ранее выданные первичные ключи по их HMAC.

Команды из установленного Python-пакета:

```sh
python -m ara.licensing.server init
python -m ara.licensing.server issue --license-id <UUID> --duration-seconds <целое>
python -m ara.licensing.server disable --license-id <UUID>
python -m ara.licensing.server enable --license-id <UUID>
python -m ara.licensing.server serve --port 8766
```

init создаёт ровно две таблицы в пустой БД либо подтверждает известную схему.
Чужая/частичная схема отклоняется, не стирается и не исправляется автоматически.
Не направлять эти настройки на локальную БД документов AIRA. Serve не вызывает init.
Issue использует ключ из secrets.env и заданную длительность; тот же UUID/ключ/срок
безопасно повторить. При несовпадении выдача отклоняется. Уже активированная или
отключённая запись не сбрасывается повторной выдачей. Команды не выводят ключи.

Serve слушает только127.0.0.1. Перед ним нужен HTTPS reverse proxy на том же хосте;
приложение доверяет forwarded scheme только от127.0.0.1. Proxy обязан сам задавать
правильный X-Forwarded-Proto и не доверять этому заголовку входящего клиента.
Внешний доступ к внутреннему порту не открывать. Access logs API отключены;
proxy также не должен сохранять тела запросов. Сервер отвергает plaintext scope.
Certificate chain/hostname клиента проверяются в D04-03; ASGI тесты D04-02 не
заменяют проверку реального TLS-развёртывания.

Операторский API не опубликован в HTTP. Для embedding доступны ServerRuntime,
initialize_database,issue_license,get_license,set_enabled,process_request и
create_license_app. Caller owns engine; фабрики не подключаются к БД/не мигрируют
её и не загружают секреты. Default server clock — время PostgreSQL, не клиента.

## HTTP для приложения

Только POST /license/v1/activate и POST /license/v1/check, HTTPS, Content-Type:
application/json. JSON request schema aira-license-request/1, поля operation,
device_id (dv1-digest), nonce (32случайных bytes в64lowerhex). Для activate нужен
license_key; для check — canonical license_id UUID. Лишние/повторные поля/query
запрещены. Body≤8192bytes, чтение≤5s/128frames; одновременно не больше4 запросов.

Ответ200 — aira-license-grant/1: operation,license_id,device_id,nonce,
activated_at_ms,checked_at_ms,expires_at_ms. Времена — UTC epoch milliseconds
каноническими десятичными строками. Ключа в ответе нет. Nonce подтверждает только
текущую попытку; сохранять ответ как разрешение офлайн-запуска нельзя.

Первая успешная активация фиксирует начало/конец и одно устройство. Повтор тем же
устройством возвращает тот же срок с новым временем проверки. Потеря ответа после
COMMIT безопасно разрешается повтором ключа/устройства. Check не активирует запись.
Для нового запуска клиент обязан снова сделать check с новым nonce. Disable
запрещает следующие проверки, а не прерывает удалённо текущий локальный сеанс.

Все ответы, включая ошибки/404, имеют Cache-Control:no-store. Ошибка содержит
только code/message без входных значений. Основные отказы: invalid_license,
not_activated,license_disabled,device_mismatch,license_expired (403);
validation_error422,request_too_large413,unsupported_media415,request_timeout408,
https_required400; license_busy/license_storage_unavailable/
license_schema_unavailable/clock_unavailable503; invalid_record/
license_storage_error500. При503 повторить ту же пользовательскую попытку с
новым сетевым nonce; срок лицензии от этого не сдвигается.

Сохранение пользовательских документов, клиентский startup state/таймер и
интерфейс ошибок будут подключаться отдельными циклами. Реальную доступность
сервера и защиту всего приложения по этим изолированным тестам не заявлять.
