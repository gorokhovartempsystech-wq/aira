# F2 — implementation preflight

3 ноября 2026, Sol6.1 High. Основание [контракт](d03-17c1f2-contract.md), F1 `72fb8f8`. Source/migration F2 ещё нет. Baseline475 hashes совпал с финальным F1. Main V8, PG оставлен работающим.

Parent-only preparation V10 migration tests:5 calls pin V10 и fixture world на isolated V10 engine; AST всех прежних assertions сохранён в .runtime/d03-17c1f2-v10-pin-asserts.json, совпадает до/после. Generic latest-head tests/conftest без изменений. Independent F2 acceptance отдельно покрывает V11 head и preservation/downgrade. Никаких изменений проверок внутри implementation.

Allowed source: models.py additive class, новая V11 migration и пять новых SQL modules supervisor из контракта. F1/B3/C1B source и schemas unchanged. Internal ledger services доверяют доказательству физической очистки от S; не экспортируются через F1 __init__ и не имеют product endpoint/force-reset. Не объявлять low-level SQL transition native proof. Startup/slot/jobs и production provisioning — F3/desktop gate.

Freeze новой acceptance/контракта/DDL/pin до source, red по отсутствию API/V11. DB tests только ara_check UUID fixtures. Snapshot main schema/counts перед/после; baseline old hashes допускает только additive models.py и exact parent pin. После source targeted/full/result/local commit, затем F3 preparation без смены модели, если контракт не конфликтует с frozen native API.

## Согласованные поправки подготовки

3 ноября Никита явно разрешил оба запроса в чате: убрать SQL comment перед split в новой oracle acceptance; дать direct exact V10 oracle отдельную V10 БД. Применён заранее подготовленный .runtime/d03-17c1f2-pending-test-preparation.patch: одна preprocessing строка, узкая fixture/one apply(V10) для старого oracle.52/29 assertions AST unchanged относительно86871c2. Это дополнение только к подготовке tests; критерии/DDL/source не менялись. Targeted204passed,32,83s; итоговый full запущен отдельно.
