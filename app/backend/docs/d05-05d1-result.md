# D05-05D1 — current schema/local identity preparation

4 ноября 2026. [Контракт](d05-05d1-contract.md), freeze **1ba496b**. Новый
SchemaPreparation создаёт V13 и Home-derived user/project/Fence в одной transaction,
подтверждает durable provenance и закрывает собственные SQL/file resources перед
ready. Repeat сохраняет DOCX, локальную identity и существующий analysis fence.
[Интерфейс](desktop-postgres-schema.md).

Preflight реальными migrations на временной PG:22 tables, differences0 по columns,
types/nullability/PK/FK. Red **20failed**,11.47s — namespace отсутствовал. Initial
targeted/native **20passed**,20.15s, включая пять crash cuts вокруг intent/COMMIT/
ready/cleanup и exact synthetic DOCX roundtrip. Дополнительный lifetime review
**8passed**,9.56s: rollback после DDL/Stop, exclusion разных clusters, partial intent,
deadline/env до IO, thread/SQL close/Engine.dispose quarantine.

Review финальной границы дал **2failed,1passed**,3.47s: deadline или Stop во время
cleanup могли опоздать к проверке ready. Source исправлен: после known cleanup
повторяется admission; уже durable данные/receipt остаются для нового запуска.
Final combined targeted/native **31passed**,29.84s. Frozen contract/20 acceptance
cases unchanged; новых test preparation fixes не было.

`bash scripts/check.sh`: **4801passed,45skipped,24subtests,77warnings**,
693.17s,exit0; Ruff/format green. Все667 final hashes и657 previous hashes совпали.
Main `0008_docx_edit_drafts`, schema/counts прежние, ara_test пустая, temporaryDB0.
Логи `.runtime/d05-05d1-{preflight,red,targeted,review,review-red,regression,full}.log`,
hash manifest `d05-05d1-hashes.json`, readonly snapshot `d05-05d1-runtime.json`.

Старые source/tests/migrations/dependencies/runner не менялись. Native приёмка —
temporary macOS PG18.6; Windows, backup/upgrade, desktop composition/real model/UI
остаются отдельными gates. Следующий **D05-05D2** готовит backup и bounded upgrade
с повтором после COMMIT; сначала native dump/restore preflight и exact contract.
Текущая Astra подходит, продолжаем. Ориентир20–31 оставшийся самостоятельный цикл;
внешняя команда/платформенная release приёмка отдельно.
