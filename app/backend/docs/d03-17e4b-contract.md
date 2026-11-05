# D03-17E4B — scoped чтение действующих скрытий для нового результата

3 ноября 2026. После E4A4019passed (1b328df). F09/F12; pure mapper готов, здесь только resolver
над реальными V13 origin references. Нет HTTP wiring/записей/автоматического
переноса rows/новой схемы. Следующий E4C объединит explicit CAS hide/unhide и API.

Allowed: новый `src/ara/docx_review_resolution/{__init__,_models,_load,_resolve}.py`,
новый `tests/acceptance/test_docx_review_resolution.py`, docs contract/result/queue.
Все E1/E2/E3/E4A source/tests, migrations/models/runner/deps сохраняются.
Никаких secret/config/model/process I/O; PostgreSQL только через переданный
DocumentRuntime и существующий scoped V13 transaction. Пул предоставляет caller.

## API и authority

`get_resolution(runtime, *, document_id, run_id, result_sha256, limits=None)`
возвращает detached Resolution: state(PreferencesState), target(Origin),
origins(tuple[Origin]), decisions(tuple[DismissalRef]), finding_keys(E1 current),
hidden_keys(effective current keys), aliases(tuple[FindingAlias]).
DismissalRef: key,run_id,result_sha256,finding_id,hidden_at_revision.
FindingAlias: finding_id,key,origin_keys(sorted unique original active keys).
Сырые records/decisions/state fields repr=False; error не содержит text/SQL.
Пустое состояние не создаёт preferences и не обходит B2 проверку current result.

Initial scoped V13 read: snapshot preferences, exact successful target, active
rows, references. Проверить rowkeys == state.hidden_keys, revision bounds,
strict identities, same-document successful origins and exact result hashes.
Никакого join чужого документа по одному UUID. Current/each distinct origin
immutable records detached перед выходом из transaction.

SQL locks освобождены до codecs/remapping. Current E1 finding_keys revalidates
B2; каждый distinct origin проходит E4A.match_findings(origin,target), даже если
совпадения нет. Его body после B2 проверки снова даёт E1 keys: каждый активный
row обязан точно совпасть с origin finding ID/key. Hash-correct shape, но неверная
ссылка/fingerprint — storage_error500, не молчаливый пропуск.

Только E4A transfers, чей previous key активен, попадают в effective hidden_keys.
Несколько origin rows могут соответствовать одному current finding: aliases
содержит **все** keys, чтобы последующий explicit unhide не оставил старое решение,
которое снова скрывает то же замечание. Не создавать транзитивные/непроверенные
сопоставления и не изменять source rows при чтении. E1 no_findings semantics прежние.

Перед возвратом повторный scoped tx: ownership и prefs revision обязательны.
Изменение preferences за время decode →409 preferences_conflict, без unbounded
retry. Target остаётся pinned при новом current DOCX. Internal recheck_inputs
для будущего writer дополнительно сверяет exact active rows и все origin bundles;
она не декодирует под locks, не является authorization capability сама по себе.
Все входы вновь проверяются, constructors не заменяют проверку records.

## Конечные бюджеты

`ResolutionLimits(max_origins=64,max_record_bytes=268435456,
max_text_characters=8388608)`, exact positive ints≤default, no bool/subclasses.
Считаются current и distinct referenced runs, shared target не копируется второй раз.
Current buffers уже ограничены B2/schema; перед чтением дополнительных origin blobs
запросить octet_length всех7 buffers (source,snapshot,command,execution,request,
reply,result). Проверить общий размер и число origins ДО их загрузки, фактические
длины detached records должны совпасть. Нет silent truncation/LIMIT64-as-success.

Текстовая работа считает current validation плюс old+current для каждого E4A call;
проверять доступный остаток перед следующим call по bounded snapshot metadata,
после проверки сверять фактические размеры. Неверная metadata не способ снизить
бюджет: B2 verifies snapshot bytes/manifest; error fail closed.

Превышение →DocumentError413 preferences_resolution_limit, никакого частичного
набора hidden keys или записей. Это технический предел resolver, не продуктовый
лимит длины DOCX. Raw analysis и E2 exact-source commands остаются доступны.
На E4C до HTTP wiring отдельно определить доступный пользователю recovery при
накоплении многих старых origin records; не объявлять весь F09 готовым здесь.

Другие safe errors:422 validation_error,404 not_found,409 preferences_conflict/
result_not_ready,500 storage_error,503 storage_unavailable/preferences_schema_unavailable.
Чтение не запускает модель, не расходует preference revision и не меняет receipts.

## Приёмка

Настоящие disposable PostgreSQL transactions и synthetic B3 saved-target/result
fixtures. No hides/defaults/no mutation; exact repeated source; far edit mapping;
changed evidence/model no transfer; two origins same current finding→all aliases;
new runtime/reopen persistence; unknown/foreign/different doc; current/origin
corruption/false key/finding association; strict inputs/lower bounded budgets;
metadata preflight before extra blob reads; ownership/preferences race after
codecs, no SQL lock during them; current DOCX edits preserve pinned resolution;
recheck rejects changed origin/decisions; byte/receipt/schema preservation.
Freeze/red→targeted E1/E2/E4A regression→full/hash/main V8 snapshot/local commit.
