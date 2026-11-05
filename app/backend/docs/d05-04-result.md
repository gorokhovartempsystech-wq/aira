# D05-04 — папка данных и стабильная identity

4 ноября 2026. [Контракт](d05-04-contract.md), freeze **b0e8600**.
Добавлен `ara.desktop.data_home`: private папка установки, неизменяемая identity,
эксклюзивное владение, восстановление прерванной первой публикации и сохранение
существующих пользовательских данных. [Интерфейс](desktop-data-home.md).

Red: **41failed**,0.38s — отсутствовал namespace. После реализации **41passed**,
0.44s. Windows ABI review добавил6 cases: Known Folder/GUID/free при успехе и
ошибке, private CREATE_NEW, publication без замены, reparse admission до чтения,
metadata-only inspection занятого owner file. После них **47passed**,0.53s.
Ещё3 macOS review cases: concurrent close, пустая существующая postgres папка без
identity, отсутствие FD leak при20 validation failures. Итоговый targeted:
**50passed,1skipped**,0.51s. Native Windows case пропущен на macOS.

На macOS проверены повторный запуск с теми же IDs/bytes, отказ второму процессу,
отдельный analysis owner, crash до/после публикации, повтор после write/flush
ошибки, quarantine неизвестного cleanup и сохранность sentinel. Frozen acceptance
и старые source/tests не менялись. Все пути синтетические временные; реальная
папка профиля и Main V8 не открывались этим компонентом.

`bash scripts/check.sh`: **4598passed,45skipped,24subtests,81warnings**,
672.25s,exit0. Ruff/format green. Все625 final hashes и614 previous hashes совпали.
Main `0008_docx_edit_drafts`, schema/counts прежние, ara_test пустая, temporaryDB0.
Логи `.runtime/d05-04-{red,targeted,regression,full}.log`, hash manifest
`d05-04-hashes.json`, snapshot `d05-04-runtime.json`.

Windows fixture не подменяет native приёмку. PostgreSQL bootstrap, schema/backup и desktop composition
остаются отдельными этапами. Нет автоматического ремонта повреждённой identity,
поиска прежней установки или миграции из dev БД.

Далее **D05-05A**: закрытый профиль конфигурации PostgreSQL18 и доказуемая привязка
проверки готовности к своей установке. Затем отдельное владение native процессом,
первоначальная подготовка cluster и graceful shutdown. На выбранной Astra продолжаем.
