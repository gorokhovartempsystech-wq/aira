# Локальный сервер настольного приложения

D05-02, 4 ноября 2026. Компонент `ara.desktop.server.LoopbackServer` владеет
HTTP-портом, потоком и жизненным циклом переданного ASGI-приложения. Приложение
и новый `LicenseClient` передаются явно; создание объекта не запускает работу.
Это инфраструктурный компонент, не готовый desktop launcher.

## Использование из оболочки

1. Создать приложение и новый клиент лицензии. Передать их `LoopbackServer`.
2. Вызвать `start()` один раз. Повтор возвращает состояние того же запуска.
3. Читать `view()`. `ready` означает готовность HTTP и ASGI startup; подтверждение
   лицензии проверяется отдельно через `/desktop/license`.
4. Только при `ready` получить `connection()`: точный origin на `127.0.0.1` и
   32 случайных байта capability. Передавать capability в заголовке
   `X-AIRA-Session` как 64 строчных hex-символа, согласно [API доступа](desktop-access-api.md).
   Не сохранять её, не помещать в URL, логи или HTML. Каждая копия connection detached.
5. Перед закрытием оболочка обязана передать накопленный текст редактору и
   подтвердить checkpoint/save. Непереданный DOM/IME buffer серверу неизвестен.
6. Вызвать `shutdown(timeout=...)`, где timeout от0 до5 секунд. `False` означает,
   что завершение ещё не подтверждено: показать ожидание, повторно опрашивать тот же
   объект. Не создавать новый сервер/клиент для обхода этого состояния.

`view()` отдаёт frozen `phase`, `error_code`, `resources_pending`, `clean_shutdown`.
Фазы: new, starting, ready, stopping, closed, failed. При остановке connection
исчезает сразу, но ранее принятый HTTP/COMMIT дорабатывает. После HTTP drain
выполняется app shutdown и закрывается клиент лицензии. Нормальное завершение —
`closed`, `clean_shutdown=True`, `resources_pending=False`.

Ошибка и освобождение ресурсов — разные сведения. Например, startup_timeout
остаётся ошибкой даже после позднего чистого shutdown. Напротив, неправильный
lifespan acknowledgement или failed cleanup не превращается в успех после
завершения потока. Такой app/client нельзя заново передать другому host в этом
процессе. Завершение DNS worker клиента отдельно ограничено контрактом D04-03;
сервер не обещает его насильственно остановить.

## Границы протокола

Native IPv4 socket создаётся на случайном свободном порту, non-inheritable;
на Windows применяется EXCLUSIVEADDRUSE, повторное использование порта отключено.
Нет внешнего bind, proxy headers, WebSocket, HTTP access logs. ASGI lifespan ведёт
сам host в том же event loop, что HTTP. Требуется startup.complete и последующий
shutdown.complete с завершением application task. `scope.state` копируется поверхностно.

Порядок обработки: shutdown fence → проверка локального caller/лицензии →
полное ограниченное чтение body → существующий API. До передачи app body ограничен
32MiB для import,8MiB для editor commands,64KiB для остальных POST,0 дляGET/create;
ожидание до15s, до32768frames. Это технические transport caps существующих операций,
не обещанный предельный размер текста модели. Два ordinary requests могут исполняться
одновременно; Stop имеет отдельное место, license status/activation — собственные
ограничения. Занятое место не создаёт очередь.

Startup deadline15s и caller shutdown deadline не отменяют application task и
не прерывают принятую запись. Если приложение зависло, сервер честно остаётся
pending; никакого force_exit/cancel принятого COMMIT. Неполное тело отклоняется до
вызова API, поэтому этот путь не создаёт частичную запись документа.

## Что подключается отдельно

Автоматическая PostgreSQL-поставка, её данные/миграции/резервирование, supervisor
и модель, frontend/static serving, сохранение вкладок и DOM/IME flush, OS window,
установщики и подпись. Внутренние компоненты приложения должен закрывать его lifespan.
Старый development launcher этим модулем автоматически не изменён.

Native loopback/macOS и disposable PostgreSQL проверяются локально. Проверка
Windows socket option через fixture не заменяет запуск установщика на Windows.
