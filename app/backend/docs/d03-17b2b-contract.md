# D03-17B2B — canonical storage codec и проверенное восстановление

1 ноября 2026, Sol6.1 High, после B2A5f3dba2. F06/F08/F12, current-product-scope и B2 design прочитаны. Pure слой между B1 и будущим SQL lifecycle. **Не добавлять** SQL операции/модели/migrations, HTTP/worker/model import, процессы/файлы/сеть/секреты/dependencies. Не читать runtime при import. Поддержан только нынешний visible-main profile/policy; complex unsupported остаётся blocked.

Allowed implementation: новый `src/ara/docx_analysis/storage_codec/`, собственные `tests/docx_documents/test_analysis_storage_codec_*.py`. Parent preparation до freeze: этот контракт и новая `tests/acceptance/test_docx_analysis_storage_codec.py`. Затем result и ссылки B2/очереди. Старый source/B1/tests/DDL/contracts/runner/tasks/progress неизменны. Freeze/red перед source; targeted/full/read-only runtime baseline и отдельный local commit. После gate продолжать B3A на том же Sol по новому контракту.

## Public API

Все DTO frozen/slotted; bytes, snapshot, command, execution и models_version repr=False. Exact types, без coercion/hooks; constructors команд/spec/limits валидируют, операции повторяют validation (object.__setattr__/foreign/replace не доверять). Bundle records — storage DTO, не capability, не доказательство авторизации/ML.

- `SavedCheckCommand(document_id:UUID, registry_id:UUID, session_id:UUID, save_command_id:UUID, command_sequence:int, session_revision:int, storage_revision:int, source_sha256:str)`.
- `RetryCheckCommand(document_id:UUID, retry_of_run_id:UUID)`.
- `ExecutionSpec(execution_kind:str, engine_version:str, models_version:str, model_sha256:str, adapter_sha256:str)`; exactly B1 provenance без attempt. Fixture/local_model и engine0.1.0; models_version1..128 non-whitespace Unicode, NUL внутри допустим, surrogate нет; digest lowerhex64. Реальный pack/kind выбирает будущий trusted runtime, codec не доказывает наличие модели.
- `EncodedValue(data:bytes, sha256:str)`.
- `SourceBundle(document_id:UUID, storage_revision:int, source_data:bytes, source_sha256:str, profile:str, policy_version:str, snapshot_data:bytes, snapshot_sha256:str, command_data:bytes, command_sha256:str, execution_spec:bytes, execution_spec_sha256:str, execution_kind:str, format_version:int=1)`.
- `RestoredSource(snapshot:VisibleSnapshot, command:SavedCheckCommand|RetryCheckCommand, execution:ExecutionSpec)`.
- `AttemptBundle(attempt_id:UUID, request_data:bytes, request_sha256:str)`.
- `ResultBundle(reply_data:bytes, reply_sha256:str, result_data:bytes, result_sha256:str, findings_count:int, questions_count:int, no_findings:bool)`.
- `CodecLimits(max_source_bytes=33554432,max_manifest_bytes=33554432,max_command_bytes=16384,max_execution_bytes=4096,max_fragments=512,max_text_characters=1000000,review:ReviewLimits=default_factory)`. Int1..default, bool запрещён, только уменьшение, nested revalidate. JSON command/execution глубина≤8, прочий wire/depth/bounds — неизменный B1. Limits не включаются в сохранённую identity; при более строгом runtime oversize явно отклоняется.

Functions (все keyword limits=None):

```
encode_command(command, *, limits=None) -> EncodedValue
decode_command(data:bytes, *, expected_sha256:str, limits=None) -> command
encode_execution(execution, *, limits=None) -> EncodedValue
decode_execution(data:bytes, *, expected_sha256:str, limits=None) -> ExecutionSpec
capture_source(data:bytes, snapshot:VisibleSnapshot, *, command, execution, limits=None) -> SourceBundle
restore_source(source:SourceBundle, *, limits=None) -> RestoredSource
prepare_attempt(source:SourceBundle, *, attempt_id:UUID, limits=None) -> AttemptBundle
capture_result(source:SourceBundle, attempt:AttemptBundle, *, reply:bytes, limits=None) -> ResultBundle
restore_result(source:SourceBundle, attempt:AttemptBundle, result:ResultBundle, *, limits=None) -> ReviewEnvelope
```

UUID exact valid integer0..2**128-1; counters1..MAX_BIGINT, session_revision0..MAX. Wire decimal strings canonical `0|[1-9][0-9]*`,≤19 digits и≤MAX. UUID canonical lowercase hyphen string (nil допускается). У saved command document/revision/hash обязаны совпасть source; retry command только document, parent run/terminal/ownership проверяет будущий B3, не этот pure codec.

## Canonical wire / source proof

Command JSON exact fields: `schema_version='docx-analysis-command/1'`, `kind='saved'|'retry'` и соответствующие поля DTO. Execution JSON exact fields: `schema_version='docx-analysis-execution/1'` и все поля ExecutionSpec. Canonical JSON UTF-8, sorted keys, separators(',',':'), ensure_ascii=False, allow_nan=False. UUID/счётчики как выше. Byte-for-byte canonical input обязателен: whitespace/key-order/escaped spelling variation отклоняются, а не перекодируются молча. SHA над exact bytes. Duplicate keys/nonfinite/invalid UTF8/surrogates/depth/extras/wrong types запрещены; проверить bytes/depth **до** json.loads. JSON null/arrays не становятся objects. Огромные numeric literals не вызывают произвольную materialization. Для capture encoder streaming, size проверять до append; не менять B1 helpers.

SourceBundle snapshot_data — canonical tokens(snapshot,omit_hash=True), streaming с cap, SHA равен snapshot.snapshot_sha256. `capture_source` сначала strict command/execution/limits/source identity и bytes bounds, потом source-backed B1 prepare_review на fixed preflight UUID0. Это проверяет snapshot/complete/nonempty/request budget без модели. Потом admission≤512 fragments/1M fragment code points, без separators/trim; byte identity/source hash и command matching. Не доверять полям непроверенного snapshot. Source bytes unchanged, no I/O.

`restore_source` проверяет exact record field types, все byte sizes до hash/reader, digest matching, version/profile/policy. Decode canonical command/execution с digests; execution_kind совпадает scalar. Rebuild snapshot из source bytes и сохранённых document/revision/sourceSHA, сравнить exact canonical manifest/digest с записью. Повторить admission/B1 preflight и command binding; не decode большого manifest обратно в произвольный dataclass и не использовать current DOCX/model. Unknown format/profile/policy = unsupported_version; нет fallback. Запись того же пакета под другой revision имеет другой manifest и не переадресуется автоматически.

`prepare_attempt` восстанавливает source и строит B1 request с exact attempt_id и сохранённым ExecutionSpec. Attempt UUID от trusted lifecycle, сам codec не выбирает run/owner/worker. `capture_result` проверяет attempt exact types/size/hash, вновь выводит request и сравнивает **bytes и digest**, затем B1 validate_engine_reply(source,snapshot,provenance,request,reply); возвращает exact reply bytes + валидированный envelope/counts. Не принимать caller-supplied envelope как proof.

`restore_result` сначала bounds/types/hash всех source/attempt/result buffers и counters/bool до reader, потом тот же source/request/B1 reply validation; сравнить exact result bytes/SHA/counts/no_findings. Никаких inference, quote repair, пустого fallback или обновления source/result. Все первичные/related anchors, hidden gap slices/questions/private provenance остаются B1. Fixture no_findings всегда false. Изменённый result с пересчитанным SHA всё равно отклоняется; malicious администратор, переписавший все согласованные source/reply/bindings, вне cryptographic guarantees.

Ограничение работы: фиксированное число source rebuilds/B1 calls, без reader по одному finding, не писать новый reader. Повторный full revalidation может быть дороже metadata polling; SQL metadata-only read B3 будет отдельно. Не обещать process cancellation, actual persistence, migration рабочих данных, real ML или full DOCX.

## Errors / приёмка

`StorageCodecError(ValueError)` с code/message: invalid_input, corrupt_record, codec_limit_exceeded, unsupported_version; safe static messages без содержимого/paths/metadata. Encode/capture malformed command/spec/DTO input →invalid_input, size/admission→codec_limit_exceeded. Decode/restore malformed stored schema/hash/noncanonical/bindings/altered DTO →corrupt_record. Unknown well-formed schema/profile/version →unsupported_version. В capture_source/reply сохранять lower B1/DOCX errors; в restore_source/result known malformed lower errors→corrupt_record, lower technical limits→codec_limit_exceeded. Invalid limits всегда invalid_input. Не ловить произвольные programming exceptions как успешный результат.

Frozen acceptance: independent canonical command/execution UUID/counter/Unicode/NUL/digest; malformed JSON/schema/canonical/type/depth/size; source/command/execution/profile/revision tamper; exact manifest vs independent expected; attempt request substitution; mapped hidden-gap result/questions/private provenance retention и fixture empty case; forged counts/result/reply/rehashed DTO; reduced caps/inclusive boundaries; repr privacy/no external I/O. До source новые tests red; после targeted с B1/visible-main и полный check. Fresh-process restoration без inference/DB (тестовый subprocess допустим только приёмке), scalar SQL wire byte roundtrip можно проверить своими tests на disposable PG без изменения моделей. Native Word/render не требуется: источник не изменяется.
