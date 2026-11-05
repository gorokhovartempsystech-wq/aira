# D03-17E1 — чистое представление замечаний и точная идентичность скрытия

3 ноября 2026. Следующий цикл F08/F09 после API D. Пользователь подтвердил, что
пакета модели пока нет; независимую работу продолжаем. Основание: основной
product scope и §5 d03-17-design. Это первый слой E: без SQL, HTTP и переноса между
изменёнными файлами. Дальше E2 persistence/CAS, E3 API и E4 conservative remapping;
только после них заявлять устойчивое пользовательское скрытие завершённым.

Allowed: новый namespace `src/ara/docx_analysis/presentation/{__init__,_view}.py`,
новый `tests/acceptance/test_docx_review_presentation.py`, этот контракт/result/
queue и уточнение основного scope о техническом presentation-only поведении.
Не менять B1/B2/D, старые tests, зависимости/runner/БД/модель. Freeze/red сначала.

## Pure API

`finding_keys(source,attempt,result)->tuple[FindingKey]`, immutable fields
finding_id/key. `present(source,attempt,result,*,disabled_types=(),show_questions=True,
hidden_keys=(),show_hidden=False)->Presentation` с wire_json/reprFalse,
view_sha256, total_findings, visible_findings, hidden_findings, visible_questions,
no_findings,no_visible_findings. Каждая функция заново вызывает B2 restore_result;
конструктор Source/Result DTO не является доказательством валидации. Никакого I/O.
Safe PresentationError codes invalid_input/corrupt_result/limit_exceeded/not_found.
Возвращаемые объекты не служат authority для записи в SQL.

Типы formulation/duplicate/contradiction отражают текущий B1 adapter, не новый
согласованный маркетинговый перечень. disabled_types list/tuple уникальных этих
строк≤3. show_questions/show_hidden строго bool. hidden_keys list/tuple уникальных
`dh-`+64lowerhex≤10000. Неверный тип/дубликат/oversize отклонить, не игнорировать.
Ограничения технические; никакого обрезания. B2 бюджеты неизменны, view ≤16MiB.

## Идентичность

Ключ sha256 canonical JSON domain docx-dismissal/1 включает document UUID,
source_sha256, profile/policy и execution_kind/engine/models versions/model SHA/
adapter SHA. Semantics: type,severity,assessment,explanation,question,private rule,
primary+related evidence(start/end/quote/slices), **без fragment_id**. Сlices и SHA
точно привязаны к байтам DOCX. attempt ID, upstream40bit ID, confidence/suggestion,
storage_revision/snapshot hash и finding_id не входят: они не меняют проблему в
тех же байтах. Изменение любой значимой части формирует новый key.

Разные occurrences повторяющегося текста имеют разные anchors и keys. Другой
документ/модель/rule/изменённый DOCX никогда не наследует скрытие в E1. Перенос
через изменённые bytes остаётся отдельным E4 с контекстом и доказанной
однозначностью; здесь нельзя скрывать по одной цитате или категории.

## Presentation

Wire schema docx-review-view/1. source/provenance/profile/policy/result SHA,
filtered findings/questions, hidden_finding_ids, preferences, counts, no_findings,
no_visible_findings, fixture. Private provenance никогда не включается.
Находки исходного B1 и SQL не меняются. По default скрытые и disabled types
отсутствуют в видимом списке. show_hidden включает скрытые в рамках выбранных
типов; hidden_finding_ids позволяют показать их состояние/вернуть.

Question включён только при show_questions и хотя бы одном видимом origin.
Question.finding_ids остаётся original; дополнительный visible_finding_ids
указывает отображаемые origins. В finding.question при show_questions=false
возвращается null (только view). Скрыть finding скрывает его отдельный вопрос,
если других видимых origins у вопроса нет.

Counts total_findings,total_questions,visible_findings,visible_questions,
hidden_findings,filtered_findings. Последние2 могут пересекаться, их нельзя
складывать для получения total. no_findings берётся только из validated B1;
пустое представление после фильтров/скрытия не превращается в «ошибок нет».
no_visible_findings означает len(visible_findings)==0. Fixture остаётся явно
учебным даже при пустом списке. Unknown valid hidden key не скрывает ничего.

## Приёмка

Synthetic complete B2 results: stable key across attempts/IDs/confidence and
same-source revision; sensitive changes model/kind/rule/severity/related/span,
source/doc change and duplicate occurrences never reuse; corrupt bundles fail
before presentation. Combination type/question/hide/showhidden, shared question,
all hidden vs true no_findings vs empty fixture, strict types/duplicates/bounds,
source/result unchanged, deterministic bytes/hashes, no text in repr/errors.
Targeted/full gate, old file hashes/main V8 snapshot, result/local commit.
