# T02-01: исполняемый контракт анализа 0.1.0

Первый из трёх планируемых циклов T02: модели и проверка входа/результата. T02-02 добавит сохраняемые задания, API и идемпотентное создание; T02-03 — worker, аренду/попытки/повторы и адаптер fixture. Этот цикл не добавляет маршруты, БД, очередь, провайдера ML, preview или применение правок.

## Публичный интерфейс

Пакет `ara.analysis_contract` экспортирует:

- Pydantic-модели `AnalysisRequest`, `AnalysisResult` по contracts/README.md версии 0.1.0;
- `validate_request(payload) -> AnalysisRequest`;
- `validate_result(payload, *, request, has_import_omissions=False) -> ValidatedAnalysis`;
- `ContractValidationError(ValueError)` с code `invalid_request` или `invalid_result` и безопасным непустым message;
- `json_schemas() -> dict` с ключами request и result, содержащими JSON Schema соответствующих моделей.

payload — обычный dict либо соответствующая модель. request в validate_result — dict либо AnalysisRequest. В том числе повторно проверять уже созданные, а затем изменённые модели; нельзя доверять model_construct или прошлой валидации. Невалидный request → invalid_request; невалидный результат или неверный тип has_import_omissions → invalid_result. Ошибки str/repr/message не содержат входных значений, цитат, документов, provider payload или подробностей Pydantic. Исключения валидации подавляются через безопасную ошибку без отображаемой цепочки.

ValidatedAnalysis имеет result: AnalysisResult и incomplete_review: bool. Последнее вычисляет backend: true при любом coverage.status=skipped ИЛИ has_import_omissions=True. Флаг импортера — строго bool, доверенные метаданные backend, не поле ответа модели. Валидация не изменяет входные dict/модели. Возвращённые вложенные структуры не разделяют изменяемые объекты с входом.

Модули инертны при импорте и вызове валидаторов: без secrets/settings, БД, сети, файлового ввода-вывода, запуска команд или выполнения инструкций из текста. Схемы генерируются из моделей и сохраняются в contracts/schemas/analysis-request.schema.json и analysis-result.schema.json. json_schemas() сама ничего не записывает. Схемы проверяют форму; семантические междокументные правила выполняет validate_result.

## Строгая структура

Все поля из contracts/README.md обязательны, без неявных defaults для отсутствующих массивов и nullable reason. На каждом уровне extra=forbid и строгие типы: не приводить число к строке, bool к числу, tuple к JSON-array. ID — непустые после проверки strip непрозрачные строки; исходное значение не нормализуется. Остальные поясняющие строки (summary/title/explanation/rationale/prompt/reason) также непустые после strip.

Text блоков/контекста/новых блоков — точные строки, пустые или пробельные допустимы, поскольку пустой разделитель тоже часть Markdown. Quote имеет длину минимум 1 и проверяется буквально, без trim/нормализации. Строки должны быть корректным Unicode без NUL. Объёмы API здесь не назначаются. Contract version строго 0.1.0; enum и поля точно соответствуют README. Execution mode, scores/confidence и неизвестные поля не добавляются в ответ ML.

Уникальность ID проверяется отдельно внутри base.blocks, context.items, findings, change_groups и questions. Между пространствами одинаковый ID разрешён; ссылки base/context различаются source. Массивы ссылок на группы/вопросы не содержат повторов. Merge требует хотя бы один new_requirement; lint не допускает new_requirement. Примеры contracts/examples остаются неизменными и успешно проходят валидацию.

## Семантика результата относительно запроса

1. contract_version, run_id, base_version_id и context_revision_id должны точно соответствовать запросу.
2. Каждая evidence во findings, groups, questions, outcomes ссылается на существующий (source,id); quote — точная подстрока text именно этого источника. Findings, groups и questions требуют хотя бы одну evidence. У outcomes массив evidence обязателен, но может быть пустым, кроме специальных правил статуса ниже.
3. Contradiction требует минимум два разных (source,id,quote). Две разные цитаты одного блока допустимы; повтор одной ссылки/цитаты дважды недостаточен. Смысловая истинность противоречия этим не доказывается.
4. Coverage покрывает каждый (source,id) входа ровно один раз, без дополнительных или повторных ссылок. Analyzed требует reason=null, skipped — непустую строку. Unsupported всегда skipped. Ссылки evidence на skipped не запрещены: описание пропуска может обосновывать вопрос.
5. Непустые questions требуют needs_clarification; пустые — ready. Это явно выбранное уточнение обратной стороны правила README, без изменения wire-полей.
6. Все targets операций существуют в base, не в context. Replace/insert содержат >=1 new_blocks, delete — пустой массив. New blocks не имеют id и не допускают kind=unsupported. Replace/delete unsupported запрещены; вставка рядом с ним допустима.
7. Зависимости групп существуют, не ссылаются на себя и образуют ациклический граф; blocking_question_ids существуют. Конфликтующие альтернативы между разными группами допустимы. Проверка пересечений и удалённых якорей в выбранном наборе, включая preview/apply, относится к T03 и в этом цикле не реализуется.
8. Outcomes содержат каждый new_requirement ровно один раз и не адресуют другие context items. В lint outcomes пусты. Все их group/question references существуют. Proposed требует >=1 change_group_id; already_satisfied — >=1 evidence из base; needs_clarification — >=1 question_id; out_of_scope — непустой rationale. Не требовать принадлежности каждой группы только одному outcome или outcome для каждого clarification/reference.
9. Если new_requirement имеет skipped coverage, outcome может быть только needs_clarification либо out_of_scope, не proposed/already_satisfied. Это явно выбранная интерпретация «пропущенные новые требования нельзя показывать как обработанные». Поля контракта не меняются.

Импортер может сообщить дополнительные пропуски через has_import_omissions; модель не может снять incomplete_review. Ready не означает полноту проверки или правильность вывода. Этот валидатор проверяет форму и ссылки, не качество реального ML.

## Проверка и разрешённые пути

Независимая приёмка проверяет оба сохранённых примера, буквальную сохранность, структурные и семантические отрицательные случаи, одинаковые ID в разных пространствах, допустимые альтернативы, вычисление неполноты, отсутствие побочных эффектов и актуальность JSON Schema. Приёмка до реализации красная. Старые 144 теста и 24 подтеста сохраняются.

Разрешено: `src/ara/analysis_contract/**`, `tests/analysis_contract/**`, `contracts/schemas/**`. Не менять examples, README контракта, независимую приёмку, модели БД, маршруты, зависимости, задачи или runner. Общая проверка `bash scripts/check.sh`; PostgreSQL запущен для прежних проверок, стандартное разрешение доступа к локальному сокету допустимо. Не переходить к T02-02.
