# D03-17C2 — сквозной review fixture

3 ноября 2026. Следующий checkpoint того же C2 после
[пакета/токенов](d03-17c2-contract.md). Цель — проверить настоящий путь
saved DOCX → отдельный процесс → B1/B2 validation → SQL result. Это учебный
ответ с явным execution_kind=fixture, а не подключение настоящей модели.
Не требует весов и не меняет upstream engine response/контракт Артёма.

## Точные изменения

Новые `ara.docx_analysis_worker.review_fixture` (pure reply + фиксированный
ExecutionSpec), `supervisor.review_fixture` (explicit новая factory).
Существующие macOS `_launch.MODES`, Windows `_adopt.MODES` получают только
дополнительный mode `review`; оба `_fixture_child.py` вызывают новый pure reply
только в этом mode. Default success/opaque reply и все fault modes сохраняются.
Никаких изменений guardian/driver/clock/locks/Job/permit/SQL/wire.

`create_review_fixture_supervisor(settings,user_id,project_id,installation_id,
root)` (все kwargs) использует прежний issued Supervisor и trusted native adapter,
но фиксирует mode review через отдельный subclass/backend wrapper. Нет caller
mode/execution/model/executable path. Factory инертна, OS выбирается как F3,
unsupported host отвергается. Старый create_fixture_supervisor сохраняет opaque
поведение и прежние tests. Provision/migration при start не добавляются.

Pure `fixture_execution()` возвращает новый immutable ExecutionSpec с
execution_kind=fixture, engine_version=0.1.0, models_version=aira-review-fixture-1,
стабильными domain-separated SHA для этой версии учебного генератора.
Это метаданные fixture, не digest реальных весов. `reply_for(request:WireMessage)`
при отказе бросает safe `ReviewFixtureError`; не имеет I/O, не исполняет текст и выдаёт bytes через прежний canonical codec.

Input guard: exact run message/kind/binding; strict bounded request JSON (8MiB,
depth8, duplicates запрещены); hash payload/execution spec совпадают с transport;
decode_execution + exact equality fixed fixture spec; docx-review/1 request,
attempt/provenance совпадают с WireBinding/spec. Exact source UUID/revision/hash,
snapshot/profile/policy, engine_request shape. Все fragments имеют уникальные
vf-SHA IDs, exact nonempty text≤1M total, document=Документ/status=active/type=фрагмент,
целочисленные неотрицательные offsets;1..512 fragments; disabled_types/dismissed
пустые. Нет parse_text/guess_status/trimming. Это проверка transport request,
а source-backed доказательство остаётся у прежнего B1/B2 после выхода child.

Генератор создаёт ровно **одно явно учебное** замечание formulation/info/yellow
на первые≤64 codepoints первого fragment. Quote совпадает с исходным текстом;
пояснение и вопрос явно говорят «Учебный пример». Suggestion/related/rule=null,
confidence=0; deterministic upstream ID. checked содержит число всех fragments,
active то же число, skipped_status=0; seconds=0.0. Fixture не доказывает проверку
требований и никогда не выдаётся как реальный no_findings.

В обоих children прежние ready/loading_model/analyzing frames сохраняются;
при ошибке pure generator передаётся последний bounded error(adapter_error),
exit76, без exception/private payload. Успех — один result frame и exit0.
Transport/native cleanup остаются прежними; parent не подменяет candidate bytes.

## Проверки

Новый `tests/acceptance/test_docx_analysis_review_fixture.py`: pure reply→real B1
validation с exact source span/fixture provenance, tampered hashes/spec/attempt/
request/fragment/duplicate/oversize rejection без private diagnostic; оба child
entry body shaped tests с реальными wire bytes; новый native factory запускает
на доступном host полный supervisor→native process→SQL success, restart read-only
restore и второй run; Stop не превращается в success. Unsupported host/inert
constructor. Native Windows full process case — честный skip до Windows среды;
Mac success проверяется настоящим process, не FakePlatform.

Freeze/red до source, targeted вместе со всеми F3/native tests, полный check,
main snapshot/result/commit. Ни один прежний test/assertion не меняется.
Реальные ONNX/ML pack/новый upstream partial/pairwise adapter остаются отдельным
незавершённым C2 gate; этот checkpoint даёт рабочую учебную цепочку для следующего
D end-to-end API. Отсутствие весов не задерживает D, согласно поручению Никиты.

Harness correction после freeze6f743f1: events StreamDecoder требует
expected_execution_spec_sha256. В четыре shaped cases передаётся существующий
digest request; все assertions неизменны (AST comparison). Это исправление
подготовки нового теста, сохраняющее проверку binding; старый wire API не меняется.
