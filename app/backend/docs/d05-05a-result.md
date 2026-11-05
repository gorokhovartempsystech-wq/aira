# D05-05A — закрытый PostgreSQL профиль

4 ноября 2026. [Контракт](d05-05a-contract.md), freeze **28b5fe9**. Pure PG18
configuration, peer/SSPI mapping, bounded connection metadata и exact readiness
observation. [Интерфейс/границы](desktop-postgres-profile.md).

Red: **71failed,2errors**,0.43s — отсутствовал namespace. Portable implementation:
**71passed**,0.06s. Первый native проход:1failed/1passed,0.74s — PG возвращает
archive_command `(disabled)` при archive_mode=off. Исправлено чтение effective
value в SQL, без ослабления обязательной проверки archive_mode. После исправления
**73passed**,0.57s. Frozen tests/contract не менялись.

Review добавил9 cases: forged metadata, Unicode, control/format separators,
uint64 boundary и Windows wrong drive/parent/ADS. Первый review4failed/5passed,
0.07s обнаружил недостающую проверку Unicode controls. Source исправлен. Итоговый
targeted/native **82passed**,0.70s. Это не Windows native acceptance.

Native fixture использует новый PG18.6 cluster: реальный initdb с sync/checksums,
foreground server с literal argument paths (включая апостроф/пробел), peer/closed
HBA, SQL observation с независимым offline system ID, запись synthetic row и
smart shutdown после закрытия connections. Чужая роль/БД отвергаются, TCP выключен.
Обнаруженное предупреждение libpq о /dev/null как passfile документировано:
секреты не читаются, будущий runtime ограничивает diagnostic output.

`bash scripts/check.sh`: **4680passed,45skipped,24subtests,79warnings**,
669.69s,exit0. Ruff/format green. Все633 final hashes и625 previous hashes совпали.
Main `0008_docx_edit_drafts`, schema/counts прежние, ara_test пустая, temporaryDB0.
Логи `.runtime/d05-05a-{red,targeted,native,review-red,regression,full}.log`, hash
manifest `d05-05a-hashes.json`, snapshot `d05-05a-runtime.json`.

Main V8/старые source/tests/runner не менялись. Процессное владение, подготовка/публикация durable cluster, backup,
schema и integration идут отдельными циклами. Следующий D05-05B сначала проверяет
native lifetime и отказ повторному запуску при неизвестном завершении процесса.
