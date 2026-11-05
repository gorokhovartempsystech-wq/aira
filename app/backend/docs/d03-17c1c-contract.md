# D03-17C1C — закрытый bounded wire codec

1 ноября 2026, Sol6.1 High, после C1B23853de. F06–F08, [C1 protocol](d03-17c1-design.md) и current-product-scope обязательны. Pure encoding/incremental decoding `aira-worker/1`, без процессов/SQL/clock/model/HTTP. Allowed: новый `src/ara/docx_analysis_worker/wire/`, новая frozen `tests/acceptance/test_docx_analysis_wire.py`, собственные `tests/docx_documents/test_analysis_wire_*.py`, контракт/acceptance до freeze, result/queue/C1 status после gate. Прежний код/tests/contracts/runner/dependencies unchanged.

## API

- Frozen/slotted `WireBinding(run_id:UUID,attempt_id:UUID)`; exact UUID, повторная проверка при каждом construction codec, DTO не capability.
- Frozen/slotted `WireMessage(binding:WireBinding,kind:str,seq:int,values:Mapping,payload:bytes|None,execution_spec:bytes|None)`; values read-only detached metadata, payload/spec repr=False, base64 strings не сохраняются в values; metadata не содержит raw payload. DTO не доказательство ML/OS результата.
- `WireError(code)` с безопасным `validation_error` (неверный local API input) или `protocol_error` (неверные peer bytes/state), без raw input/context.
- `encode_message(binding,*,kind:str,seq:int,values:dict)->bytes`: значения уже wire-form, включая standard padded base64 строки; serializer проверяет полный frame schema/digests/caps, но не stream order. Возвращает prefix+canonical JSON.
- `StreamDecoder(binding,*,lane:str,expected_execution_spec_sha256:str|None=None)`; lane=request/events/control/status. events требует expected lowercase64 SHA; другие lanes не принимают непустой expected. `.feed(chunk:bytes)->tuple[WireMessage,...]`, chunk≤64KiB (больше — validation_error, без мутации); `.finish()->None`. Ни I/O, ни callback. Empty chunk разрешён до finish.

Canonical UTF8 JSON bytes: sort_keys=True, ensure_ascii=False, separators=(',',':'), no NaN. Принимаем только exact canonical форму с closed root fields; duplicate keys/constants/invalid UTF8/surrogates/nested object/array/extra keys запрещены. Root/version/kind/run/attempt/seq обязательны, `protocol='aira-worker/1'`, binding exact canonical UUID strings, seq exact int0..1024. Depth ограничена4 при parse, но closed flat schemas дополнительно запрещают containers. Timestamp strings canonical decimal0..2**63-1, без leading zero/sign/whitespace, decoded values получают int. Остальные metadata exact scalar types, bool не int.

## Frames/bounds

Length —4byte unsigned big-endian N, payload ровноNbytes; N0/выше lane cap reject до body allocation. Caps относятся к N, prefix добавляет4. Binary payload/spec передаются base64; до decode оценить decoded size по length/padding, потом strict validation и canonical re-encode. SHA256 exact decoded bytes, lowercase64. Не parse B1 payload/не импортировать B2B: его validation отдельная.

| Kind / lane | Exact values keys | N cap |
|---|---|---:|
| run / request | worker_instance_id canonical UUID, claim_fence exact1, request_sha256, execution_spec_sha256, request_b64 (decoded1..8MiB), execution_spec_b64 (decoded1..4KiB) |12MiB|
| ready / events | execution_spec_sha256, совпадает с decoder expected |4KiB|
| stage / events | stage=loading_model/analyzing |4KiB|
| result / events | reply_sha256, reply_b64 (decoded1..4MiB) |6MiB|
| error / events | code=model_unavailable/model_input_limit_exceeded/adapter_error/analysis_limit_exceeded |4KiB|
| permit / control | deadline_ns,lease_ns canonical strings, lease<=deadline |4KiB|
| stop / control | reason=user/deadline/lease/storage/shutdown/protocol |4KiB|
| closed / status | exit_kind=clean/stopped/crashed, exit_code exact signed32,cleanup_confirmed exactbool |4KiB|

Per-stream seq с0, без gaps/replay, scoped binding не меняется. Request ровно run. Events ready→loading_model→analyzing→result; error может заменить любой ещё не отправленный terminal, включая до ready. После terminal лишний byte/frame запрещён. Events≤4frames, total N≤6MiB+12KiB. Control≤512frames, total N≤1MiB; первый permit фиксирует D, следующие D не меняют, stop terminal. Status один closed. Request/status finish требует полный единственный frame; events finish требует terminal; control EOF (даже без stop) допустим и означает прекращение работы для будущего guardian. Обработка physical EOF/exit/Stop — C1D/F, не codec.

Incremental parser хранит≤одного bounded frame и≤4bytes header; читает произвольное разбиение/coalescing, выдаёт completed messages сразу. Не накапливает все payload frames до EOF. Limit счётчики включают announced N сразу после header; overflow отвергается до body. Любой peer protocol failure poison decoder, будущие calls protocol_error. Ошибка local chunk type/size не меняет state. finish повторно idempotent после валидного EOF; feed после finish запрещён. Trailing partial header/body/extra bytes — error, не silent ignore. При StreamDecoder binding detaches от input DTO. No raw data в repr/errors/traceback.

## Frozen acceptance

До implementation freeze/red. Проверки независимым stdlib prefix+JSON builder: exact canonical encoding, request/result bytes preserved, min/max/+1 cap,1byte delivery/coalesced frames, early header rejection, EOF/truncation/extra, wrong UUID/version/type/seq, duplicates/constants/UTF8/surrogate/base64/digests, closed fields, stage ordering/error positions, control D pin/seq/count/total, closed exit fields, poisoning/no mutation local error, readonly snapshots/detached binding/inert import. Синтетические payloads не выдаются за анализ.

Targeted+own и `bash scripts/check.sh`, read-only runtime baseline, result/local commit. Не запускать main migration/model/Word, не читать secrets/archive и не push. После C1C — C1D macOS guardian по отдельному точному OS контракту; режим Sol6.1 High, если native probe не выявит архитектурного противоречия.
