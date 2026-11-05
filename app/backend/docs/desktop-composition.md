# Owned fixture desktop backend

`ara.desktop.composition.FixtureDesktop` связывает подготовленные компоненты в один
Mac runtime. Это programmatic integration для разработки/приёмки, не установщик,
не пользовательский UI и не настоящая ML-модель. Анализ всегда semantic fixture;
результаты/HTTP явно содержат fixture provenance.

Передать frozen `FixtureConfig`: absolute private Home, trusted PG18 PgTools,
UpgradeTools из того же bin, migrations, HTTPS license_origin. Optional explicit
D04 clock/device_provider/transport нужны синтетической приёмке; реальные запускаются
через native device/continuous clock и HTTPS client. Нельзя выдавать fixture transport
за TLS-развёртывание. Пакет/бинарники должен проверить доверенный внешний launcher;
конфигурация и VerifiedInstallation DTO сами по себе не capability/подпись.

Конструкторы инертны. `start()` запускает один owned controller. `view()` возвращает
phase/stage/error_code/resources_pending/fixture. `ready` означает готовый loopback
HTTP, а не активированную лицензию. `connection()` выдаёт LocalConnection только
при ready: origin и repr-hidden session_token; capability передаётся заголовком
X-AIRA-Session, не в URL. Нельзя публиковать/логировать этот токен.

Первый старт открывает Home, запускает свой PostgreSQL, проверяет upgrade D2 и
schema D1, создаёт source A, supervisor и HTTP. Повторный старт сохраняет Home IDs,
DOCX/черновики/результаты; license client заново обращается к серверу. Прежняя
активация не даёт offline доступ. Общий startup budget900s использует continuous
clock, учитывая длительную приостановку. Более узкие пределы компонентов сохраняются.

`shutdown(timeout=0..5)` закрывает вход и ждёт в пределах бюджета вызывающего.
False означает незавершённое/неподтверждённое закрытие, а не разрешение освободить
Home или убить PostgreSQL. Controller продолжает ожидание: HTTP accepted requests,
license worker, supervisor, preparation jobs, SQL connections, PG smart shutdown,
Home. Уже принятое сохранение документа и уже начатая атомарная запись активации
могут закончиться. Никакого force kill/отката пользовательской записи ради выхода.

`LicenseClient.close()` по-прежнему только сразу запрещает доступ. Новые
resources_pending()/shutdown() позволяют дождаться известного конца worker.
Неизвестный результат Thread.start не становится успешным закрытием только потому,
что Thread.is_alive=False. После такого исхода сохраняются strong ownership claims;
для повторного запуска нужен новый процесс. Это же относится к Home factory failure:
его существующий API может удержать невыданный native record без returned handle.

HTTP analysis reads имеют отдельный source-bound NullPool lane cap2 и прежние
короткие supervisor SQL timeouts. Сравниваются реальные issued Engines/IDs, не
одинаковые placeholder URLs. Штатный editor OptionEngine разрешён только как
непосредственная обёртка того же document Engine с тем же pool; foreign engine с
тем же URL не принимается. Старый URL-based runtime остаётся отдельным legacy path.

Пока отсутствуют: production ML pack, UI/launcher/package, native Windows PG
composition, подписанные установщики и публичная license TLS приёмка. Полная DOCX
матрица и Word visual/native parity также отдельны. Этот runtime не заявляет их
готовность; main development V8 не усыновляет и не мигрирует.
