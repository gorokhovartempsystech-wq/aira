# Профиль локального PostgreSQL

D05-05A, 4 ноября 2026. `ara.desktop.postgres_profile` строит неизменяемый план
PG18 без чтения файлов, запуска процессов, подключения к БД и получения секретов.
Это техническая подготовка внутреннего запуска; пользователь не настраивает БД.

`make_plan(target=..., installation_id=..., postgres_root=..., system_user=...,
windows_realm=..., port=...)` получает явные проверенные значения от будущего native
bootstrap. Профили — macos-arm64/macos-x86_64/windows-x86_64. Установка определяется
UUIDv4 из DataHome. OS account и Windows SAM realm должен получить native слой,
а не прочитать их из произвольных переменных окружения.

На macOS TCP отключён. Соединение идёт через короткую private Unix socket папку
в /private/tmp, связанную с installation UUID; PostgreSQL peer сверяет OS account.
На Windows слушается только127.0.0.1 на выбранном порту49152–65535, SSPI сохраняет
realm и сопоставляет ровно одного OS-пользователя. Другие роли/БД/адреса запрещены.
Ни пароль, ни trust authentication не нужны. Native Windows проверка ещё впереди.

Plan содержит data18, staging .data18.pending, три configuration файла, initdb и
foreground postgres arguments. Executable в arguments не входит: launcher добавит
проверенный bundled binary. Не передавать аргументы shell, не брать путь к binary
из PATH и не использовать plan как доказательство неизменности файлов установки.
Копирование metadata не предоставляет права на выполнение.

`initdb` сначала создаёт staging с reject authentication, checksums и обычным sync.
При ошибке partial data остаются для отдельной проверки; автоматического удаления
или повторного initdb поверх существующих файлов здесь нет. Следующий bootstrap
должен подтвердить завершение initdb и опубликовать новый cluster отдельно.

Критичные параметры задаются командной строкой: надёжная запись включена, фоновые
preload libraries/архивация выключены, серверные SQL-логи ограничены. Generated
server.conf содержит только служебный комментарий. В путях допускаются пробелы,
апостроф и обычный Unicode; управляющие/невидимые formatting characters запрещены.

`plan.connection('aira'|'postgres')` возвращает libpq metadata с bounded connect
timeout, точным endpoint и отсутствием пароля. passfile направлен на /dev/null
или NUL, чтобы не читать пользовательский .pgpass. libpq на macOS при этом пишет
фиксированное предупреждение о неполном типе файла; оно не содержит секретов.
Будущий launcher должен подавлять/ограничивать diagnostics и запускать Python/PG
с узким environment без PG*/DYLD*/PYTHON* overrides. Одни kwargs не отменяют
ambient service defaults libpq. Новые kwargs не передавать механически в старый
supervisor URL: его allowlist подключается в отдельном integration cycle.

В собственном подтверждённом connection выполняется `OBSERVATION_SQL` — один
read-only запрос. `check_observation(plan, result, expected_system_identifier=...,
database='aira')` проверяет версию18, cluster ID, текущую БД/пользователя, encoding,
endpoint/пути и полный закрытый набор параметров записи/загрузки/логирования.
Expected system ID берётся из независимого private cluster record/результата
первой подготовки. Нельзя просто скопировать его из того же SQL ответа.

PostgreSQL представляет отключённый archive_command как `(disabled)`; SQL приводит
его к пустому effective value только при archive_mode=off. Сам archive_mode также
обязательно проверяется. Это формат наблюдения отключённого действия, не исполнение
архивации и не принятие произвольного archive command.

Mismatch даёт fixed postgres_mismatch без содержимого/путей. Invalid input —
validation_error, неизвестный target — unsupported_target. Проверка не доказывает
подлинность соединения сама по себе: native owner должен отдельно удерживать свой
процесс, root и его identity до завершения всех HTTP/SQL операций.

Native macOS acceptance запускает только временный PG18.6, проверяет реальные
configuration/HBA/ident, запись и smart shutdown. Рабочий кластер не меняется.
Реального desktop startup, миграции пользовательских данных, backup или Windows
SSPI readiness этот цикл ещё не реализует.
