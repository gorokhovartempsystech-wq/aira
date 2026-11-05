# D05-03 — проверяемый состав установки

4 ноября 2026. [Контракт](d05-03-contract.md), freeze **7612243**. Добавлены pure
parse_manifest и явный read-only verify_installation: pinned manifest, закрытые
пути/роли/лимиты, exact inventory, потоковые hashes и наблюдение за изменениями.
[Интерфейс и границы доверия](desktop-installation.md).

Учебный пакет требует explicit allow_fixture; режим остаётся fixture. Рабочий
inventory требует model manifest и его hash. Сами веса, работоспособность runtime,
модель и frontend этим не объявляются проверенными. Ни одного файла payload
verifier не изменяет, не запускает и не скачивает.

Red: **78failed,1skipped**,0.60s — отсутствовал namespace. После реализации:
**78passed,1skipped**,0.14s. Ещё8 review cases: large/empty streaming, позднее изменение
уже проверенного файла, непрочитанное лишнее содержимое, observed reparse,
explicit fixture files, Windows target без POSIX execute bits, fixed missing/permission.
Общий targeted: **86passed,1skipped**,0.19s. Frozen assertions не менялись.

`bash scripts/check.sh`: **4548passed,44skipped,24subtests,76warnings**,
668.96s,exit0. Ruff/format green. Все614 final hashes и606 previous hashes совпали.
Main `0008_docx_edit_drafts`, schema/counts прежние, ara_test пустая, temporaryDB0.
Логи `.runtime/d05-03-{red,targeted,regression,full}.log`, hash manifest
`d05-03-hashes.json`, snapshot `d05-03-runtime.json`.

Подтверждены обычная macOS filesystem preflight и portable fixtures. Native Windows,
OS signing, защищённый install root, реальная сборка PostgreSQL/Python/модели/UI,
публичная поставка остаются отдельными gates. Проверка файлов — снимок, а не
атомарная гарантия against concurrent same-user replacement после возврата paths.
Main PG, старые source/tests/runner/dependencies не менялись.

Далее **D05-04**: отдельная папка данных приложения, стабильная локальная identity
и владение одним экземпляром перед PostgreSQL bootstrap. Ориентир **11–26
самостоятельных циклов**; этот этап вычтен один раз. На выбранной Astra продолжаем.
