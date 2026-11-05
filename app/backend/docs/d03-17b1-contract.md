# D03-17B1 — versioned review request/result validation

1 ноября 2026, Sol 6.1 High, после b2 d3cedcc и native evidence c0. F06/F08/F10, [архитектура D03-17](d03-17-design.md), текущий product scope прочитан. Независимый от Word boundary/weights/frontend цикл. Native c остаётся blocked, сложные DOCX не допускаются молча. Engine source pinned036a4e8, engine VERSION0.1.0; remote main заново не проверяется, engine не импортируется/не запускается.

Allowed: новый `src/ara/docx_analysis/review/`, новый `contracts/docx-review-v1.json`, новая frozen `tests/acceptance/test_docx_review_v1.py`, собственные `tests/docx_documents/test_review_v1*.py`, этот контракт до freeze, `d03-17b1-result.md`, очередь/ссылки D03-17. Legacy source/contracts/tests/API/БД/dependencies/scripts/runner/tasks/progress/AGENTS не менять. Internal imports unchanged visible_main mapper/models/canonical tokens разрешены; не копировать reader. Freeze/red → source → targeted/full/baseline → result/local commit. Main V8. Никаких процессов/сети/секретов/модели/import app I/O.

## API и DTO

Публичный API `ara.docx_analysis.review`:

```python
prepare_review(data:bytes, snapshot:VisibleSnapshot, *,
    provenance:ReviewProvenance, limits:ReviewLimits|None=None) -> PreparedReview
validate_engine_reply(data:bytes, snapshot:VisibleSnapshot, *,
    provenance:ReviewProvenance, request:PreparedReview, reply:bytes,
    limits:ReviewLimits|None=None) -> ReviewEnvelope
```

DTO frozen/slotted, sensitive fields/вложенные records/bytes repr=False. Exact classes/primitives, повторная validation на входе, никаких произвольных объектов/hooks или implicit coercion. Все строки сохраняются буквально, кроме пустой issue.question→None как явное отсутствие вопроса. Внешний JSON только bytes UTF-8, duplicate keys/NaN/Infinity/extra fields запрещены. JSON depth проверять до materialization, bytes caps до decode. Unicode surrogate strings недопустимы. Никаких silent skips, clipping, fuzzy quotes или partial result.

- ReviewProvenance: `attempt_id:UUID`, `execution_kind:str`, `engine_version:str`, `models_version:str`, `model_sha256:str`, `adapter_sha256:str`. Exact UUID/int0..2**128-1, kind fixture/local_model, engine_version **0.1.0** для данного pinned adapter, models_version non-whitespace1..128, lower64hex digests. Constructor и API invalid→ReviewError.invalid_input. Эта trusted worker metadata не доказывает наличие весов; её верификация/выбор execution kind — C2, пользователь не присваивает local_model через будущий API.
- PreparedReview: `wire_json:bytes`, `engine_request_json:bytes`, `request_sha256:str`. Bytes repr=False. Из caller request использовать только после exact type/size checks, затем сравнить со вновь выведенным expected request; altered request invalid_input.
- ReviewEnvelope: `wire_json:bytes`, `result_sha256:str`, `findings_count:int`, `questions_count:int`, `no_findings:bool`. Immutable internal storage envelope, не готовый HTTP endpoint. Canonical result bytes создаются только validator; дополнительного encoder для caller-replaced DTO нет.
- ReviewLimits: max_reply_bytes4194304, max_wire_bytes8388608, max_issues10000, max_questions10000, max_metadata_characters4096, max_suggestion_characters100000, max_json_depth32, `view:VisibleLimits=default_factory`. Exact ints1..default, только уменьшение, exact nested limits/revalidation, bool запрещён. Invalid→invalid_input, exceed→review_limit_exceeded. Reply bytes/arrays/output budgets не обрезаются.

## Подготовка запроса

prepare_review сначала source-backed map_visible_spans с пустым requests; затем complete=True и хотя бы один fragment, иначе unsupported_document/empty_document. Принимается только final-visible-main-v1/final-visible-no-comments-v2; старый профиль не является fallback. Source/Docx/StyleContext errors делегируются. Все current fragments отправляются как active, включая headings/короткие строки без trim/parse_text/guess_status. Input payload: `fragments:tuple[{id,text,document='Документ',status='active',type='фрагмент',offset=analysis_start}]`, `disabled_types:[]`, `dismissed:[]`. UI filters не меняют генерацию. Empty checks и coverage blockers не обходятся fixture режимом.

Canonical request wire: exact keys `schema_version='docx-review/1'`, `kind='review_request'`, `source`, `snapshot_sha256`, `profile`, `policy_version`, `provenance`, `engine_request`. source: document_id canonical UUID string, storage_revision decimal string, source_sha256. provenance: все шесть полей, UUID строкой. engine_request_json содержит только engine_request; request_sha256=SHA256(wire_json). Fragments order исходный. Ни saved bytes, ни raw Word markup не передаются engine. Будущий C2 проверяет model/token limits отдельно, request validation не доказывает отсутствие tokenizer truncation.

## Ответ pinned engine

Exact top keys: engine,models,issues,questions,checked,seconds. engine/models равны expected provenance versions. seconds exact int/float (bool запрещён), finite0..300. checked exact keys fragments,active,skipped_status: exact int, fragments==active==submitted_count, skipped_status==0. Issues list ≤max_issues, questions list≤max_questions. Все strings bounded, no implicit conversion.

Issue exact12 keys по pinned schema: id,type,severity,light,confidence,fragment_id,span,related,explanation,rule,suggestion,question. id=`iss-`+10lowerhex и unique. type formulation/duplicate/contradiction, affected запрещён. severity info/warning/critical; light red/yellow. confidence exact int/float finite0..1, bool запрещён. explanation non-whitespace1..max_metadata_characters. rule None либо non-whitespace1..max_metadata_characters. question None либо string0..max_metadata_characters; empty→None. suggestion None либо exact {before,after}, strings≤max_suggestion_characters; before==primary quote. Эти private suggestions не означают команду применения.

span exact {start,end,quote}, exact ints non-bool, exact str: primary проверяется source-backed mapper с actual fragment/quote. formulation требует related=None; duplicate/contradiction требуют related exact {fragment_id,quote,status}, status=active, другой submitted fragment и его **полный** exact text. Related span [0,len(quote)) тоже проходит mapper, после чего проверяется, что quote полный fragment text. Нет первого совпадения/переноса между fragments. Все primary/related requests собираются в один batch; map_visible_spans вызывается **один раз** на validation даже для zero issues (empty batch). Unknown fragment/invalid span→ReviewError.invalid_reply, source/snapshot/package/technical view errors сохраняются.

JSON parser проверяет shape до использования source fields; после mapping source snapshot доверенный. Затем повторно вычисляется expected request из этого snapshot/доверенного provenance без второго source rebuild и сверяется caller request. complete/empty admission повторяются. Invalid issue/request не публикует ничего. Questions raw list — unique nonempty strings; set точно равен set непустых issue.question. Нет потерянных/лишних/дублированных вопросов.

## Internal result wire / identity

Exact result keys: schema_version='docx-review/1', kind='review_result', source, snapshot_sha256, profile, policy_version, provenance, request_sha256, findings, questions, coverage, counts, no_findings, private_provenance. Identity повторяет проверенный запрос. coverage копирует exact snapshot ledger. counts exact {fragments,findings,questions}. Findings сохраняют порядок issues. Private provenance не выдаётся будущим public HTTP DTO и не задаёт ISO badge/confidence probability/apply endpoint.

Finding exact fields: `finding_id`, `type`, `severity`, `assessment`, `explanation`, `primary`, `related`, `question`. assessment сохраняет red/yellow как enum сигнала, не вероятность истинности. Evidence object exact {fragment_id,start,end,quote,slices}; slices — source-backed mapped slices с kind/anchor/run_anchor/paragraph_anchor/start/end. Related None либо полный mapped evidence. Текст вопроса None либо исходная непустая строка.

Finding ID `df-`+SHA256 canonical fingerprint: {domain='docx-review-finding/1', source, snapshot_sha256, profile, policy_version, engine_version,models_version,model_sha256,adapter_sha256,type,severity,assessment,explanation,primary,related,question,rule}. **Не включать attempt_id/upstream id/confidence/suggestion/elapsed**: новое транспортное выполнение не меняет семантическое finding identity. Дубли локальных IDs invalid_reply, не silent dedup.

Questions output сортируются по точному text. Каждый exact {question_id,text,finding_ids}; finding_ids sorted unique всех origin findings с этим text. question_id=`dq-`+SHA256 canonical {domain='docx-review-question/1',source,snapshot_sha256,text,finding_ids}. Утрата связей при dedup запрещена. private_provenance tuple issue-order: exact {finding_id,upstream_id,confidence,rule,suggestion}; suggestion без преобразования/исполнения, local output JSON защищён bytes limit.

no_findings true только при execution_kind=local_model, complete source, findings=questions=0. Fixture всегда false и явно помечен provenance; код validator не запускает ML. Если позже UI всё отфильтрует, исходные counts не меняются. result_sha256=SHA256(result wire_json). Canonical JSON: UTF-8 ensure_ascii=False/sort_keys/separators=(',',':')/allow_nan=False, массивы в заданном порядке, revisions как строки. Stream encoding с byte cap до append, не полный asdict/огромный dumps перед проверкой. Dict/tuple/known immutable evidence only; чужие DTO не сериализуются.

`contracts/docx-review-v1.json` — новая самостоятельная JSON Schema2020-12 с defs request/result/source/provenance/evidence/finding/question/private_provenance и additionalProperties=false на objects. Она описывает wire shape, а cross-field hashes/quotes/completeness/identity обеспечивает validator. Старые schemas не меняются. Error codes/message статические: invalid_input, unsupported_document, empty_document, invalid_reply, review_limit_exceeded. Нельзя показывать сырой JSON/parser errors/user text в diagnostics/repr.

## Приёмка и границы

До source freeze new acceptance: literal source/engine payload, short/mixed Unicode/hidden-gap evidence, exact wire/hash independent canonical calculation, all supported issue kinds/related full text and question dedup origins; empty fixture vs no_findings logical local_model branch (только synthetic protocol test, не реальный inference). Semantic IDs стабильны при смене attempt/upstream ID/confidence/suggestion, меняются при model/severity/evidence/explanation/question/rule.

Invalid matrix: extras/missing/duplicate JSON keys, nonfinite/bool numerics, unknown types/enums/versions/IDs/duplicate IDs, broken primary/related/quote/status, checked mismatch, orphan/duplicate/missing questions, altered prepared request, unsupported/empty/old snapshot, malformed UTF-8/Unicode/deep/oversize JSON, nested limits and exact/+1 budgets, malformed DTO without hooks/content leak. Один mapper/catalog rebuild на reply batch, bounds aggregate quotes/slices/output, fresh-process no I/O, existing readers/legacy regressions.

Полный check.sh и read-only baseline, local commit/result. Новые HTTP routes/schema migrations/supervisor/weights/front пока не создаются. Следующий B2 получает отдельный exact DDL/migration contract; сложные readers/native c продолжаются независимо при доступности evidence. Цикл B1 не объявляет целую AIRA или реальную модель готовой.
