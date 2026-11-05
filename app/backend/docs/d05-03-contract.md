# D05-03 — проверяемый состав установки

4 ноября 2026, после D05-02/7b98a18. Один цикл: pure manifest decoder и read-only
preflight содержимого установки. Установка, распаковка и запуск сюда не входят.

Разрешены новые `src/ara/desktop/installation/`,
`tests/acceptance/test_desktop_installation*.py`, этот contract/result/guide и
`development-queue.md`. Старые source/tests/dependencies, миграции и runner/tasks/
progress неизменны. Основная БД V8 не меняется.

## Интерфейс

- `parse_manifest(raw, *, expected_sha256, target, allow_fixture=False)` возвращает
  `InstallationManifest`. Pure: без файлов, сети, настроек и native calls.
- `verify_installation(root: Path, *, expected_sha256, target, allow_fixture=False)`
  возвращает `VerifiedInstallation`. Явно читает только указанный payload; ничего
  не создаёт, не меняет, не скачивает и не запускает.

Импорт инертен. `expected_sha256` — exact str lowercase hex64; `target` — exact str
из `macos-arm64`, `macos-x86_64`, `windows-x86_64`; `allow_fixture` — exact bool.
Ошибка аргумента: `validation_error`. Root — абсолютный Path без `..`, не symlink
или reparse point. Названия target — профили сборки, не подтверждённая совместимость
с реальным компьютером или обещание минимальной версии ОС.

`PackageError` содержит только fixed code/message. Коды: validation_error,
package_unavailable, package_invalid, package_mismatch, unsupported_target,
fixture_not_allowed; неизвестный код нормализуется в package_invalid. Сырые пути,
исключения и содержимое файлов не отражать в сообщениях или логах.

DTO frozen/detached. Manifest: version,target,kind,sha256,files(tuple FileRecord),
entrypoints(immutable mapping),model_manifest_sha256,total_bytes.
FileRecord: path,size,sha256,executable. VerifiedInstallation: root и manifest;
`role_path(role)` возвращает Path только для известной непустой роли, иначе
validation_error. Repr DTO не раскрывает root, paths, file contents или digest.
Это снимок проверки, не разрешение на запуск и не security capability.

## Закрытая схема manifest

Файл `aira-installation.json`: до4MiB, UTF8 без BOM. SHA проверяется до разбора.
JSON depth<=8; duplicate keys, NaN/Infinity и неизвестные поля запрещены.
Поля ровно: schema_version="aira-installation/1", product="aira", version,target,
kind,files,entrypoints,model_manifest_sha256. Version — release label по regex
`[A-Za-z0-9][A-Za-z0-9._+-]{0,63}`, без отдельной semver-политики.
Kind: production либо fixture. Target должен совпасть с ожидаемым, иначе
unsupported_target. Fixture запрещён по умолчанию; explicit allow_fixture=True
разрешает его, но kind остаётся fixture.

Files — sorted ascending list из1..32768 records с полями ровно path,bytes,sha256,
executable. Bytes: exact int от0 до8GiB; суммарно до16GiB. Executable: exact bool;
digest: lowercase hex64. Path — relative ASCII, длина1..1024, глубина<=32,
компоненты1..180 из `[A-Za-z0-9_.+-]`. Запрещены `.`, `..`, пустые компоненты,
завершающая точка, Win reserved CON/PRN/AUX/NUL/COM1..9/LPT1..9 с любым расширением.
Нет casefold aliases файлов или каталогов, duplicates либо file-parent conflict.
Корневой aira-installation.json в любом регистре не включается в files.

Entrypoints содержит ровно python,application,postgres,initdb,pg_dump,pg_restore,
pg_controldata,frontend,model_manifest. Все кроме model_manifest — различные пути
из files, с size>0. Python и пять PG roles требуют executable=True; application,
frontend и model_manifest — False. Production требует непустой model_manifest;
его record digest равен model_manifest_sha256. Fixture требует null в обоих этих
полях. Проверка внутренней схемы модели C2, работоспособность бинарников, модели
и UI находятся за пределами проверки inventory.

## Чтение файлов

Root — выделенное поддерево payload. Подписанный launcher/descriptor находится
снаружи; доверенный pin приходит от него, а не из самоподписанного соседнего файла.

Читать по одному файлу, chunks<=1MiB; manifest ограничен4MiB+1. Размер и SHA должны
совпасть; короткое/лишнее содержимое — package_mismatch. Metadata dev/ino,size,
mtime/ctime до и после чтения сравниваются; observed replacement — package_invalid.
Только regular single-link files и обычные каталоги; запрещены symlinks, reparse,
FIFO/devices. POSIX использует O_NOFOLLOW/O_NONBLOCK и dirfd traversal. Windows
проверяет наблюдаемые lstat/fstat/reparse flags; устойчивость loader к атакующему,
который одновременно меняет дерево, здесь не заявляется. До чтения содержимого
проверить metadata открытого файла.

Inventory ровно manifest+files и их подразумеваемые каталоги. Непредусмотренные
файлы и пустые каталоги отклоняются без чтения содержимого; missing expected file
— package_unavailable. После hashing повторить inventory/metadata для обнаружения
наблюдаемых изменений. Нет неограниченного walk: сверять имена с ожидаемым деревом,
число nodes/depth ограничено manifest. File buffers не возвращаются. OSError,
FileNotFound/permission — package_unavailable с фиксированным сообщением.

Preflight — не атомарный snapshot файловой системы. Доверенное install root не
должно меняться во время и после проверки; OS signing/root permissions и владение
запуском проверяются отдельно. Отказ на наблюдаемую гонку не доказывает защиту от
владельца, способного переписать всю установку. Mutable documents/PG data/activation
живут вне payload. Builder не оставляет symlinks/pycache/посторонние файлы и
сохраняет исполнительные права. POSIX проверяет execute bit у executable records;
при проверке Windows target на POSIX этот бит не требуется.

## Приёмка

Freeze/red до source. Pure production/explicit fixture; target/hash mismatch;
exact shape/duplicates/limits/path aliases; immutable metadata/inert parser.
Synthetic payload: все hashes, missing/corrupt/size/additional/empty directory,
symlink root/file/parent, hardlink, FIFO без зависания, execute bit, bounded streaming
и observed mutation, fixed errors, исходные файлы неизменны. Windows native gate
отдельно. Targeted/full/hash/main V8 snapshot/result/local commit.

Ошибки подготовки новых tests допустимо исправлять с записью причины без ослабления
приёмки. Старые assertions/source не менять. Не публиковать installer/downloads и
не объявлять настоящую модель готовой по synthetic manifest.

Источники: [Python os](https://docs.python.org/3.12/library/os.html),
[Windows file handles](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew).
