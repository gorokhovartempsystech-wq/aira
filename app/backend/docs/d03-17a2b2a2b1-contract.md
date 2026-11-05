# D03-17A2b2a2b1 — расчёт видимости обычного run

1 ноября 2026, Sol 6.1 High, после styles catalog `1dd3238`. F06/F11, часть b2a2b по [дизайну](d03-17a2b2a2-design.md). До snapshot/mapper отдельным bounded циклом фиксируем и проверяем комбинацию paragraph/character/direct свойств. Это pure batch resolver для будущего main reader, без утверждения, что queries получены из реальных runs. Текст документа не извлекается и не передаётся модели.

Allowed: новые `src/ara/docx_analysis/visibility/rules.py`, `_rules_models.py`; существующие visibility/final_view/A1/A2a/__init__/package/DB/HTTP/ML/editor/dependencies/scripts/tests/runner/AGENTS неизменны. Импорт нового API только из visibility.rules, без правки __init__. Новая frozen `tests/acceptance/test_docx_visibility_rules.py`, own `tests/docx_documents/test_visibility_rules*.py`; этот контракт до freeze, result/queue и статусы/ссылки design. Freeze→red→source→targeted/full→baseline→result/local commit. Main V8, без push. Политика пользователя прежняя; нового продуктового вопроса нет.

API:
```python
from ara.docx_analysis.visibility.rules import (
    resolve_run_visibility, RunVisibilityQuery, RunVisibilityLimits,
    RunVisibilityError, RunVisibility, RunVisibilityBatch,
)
resolve_run_visibility(
    data: bytes, *, source_sha256: str,
    queries: tuple[RunVisibilityQuery, ...],
    limits: RunVisibilityLimits | None = None,
) -> RunVisibilityBatch
```

Все новые DTO frozen/slotted, коллекции tuple. Query поля: `paragraph_style_id: str|None=None`, `character_style_id: str|None=None`, `direct_vanish: bool|None=None`, `direct_spec_vanish: bool|None=None`, `direct_web_hidden: bool|None=None`. ID exact str 1..253 code points, без strip/case normalization, repr=False. Bool exact (0/1 запрещены). Query валидируется и в constructor, и повторно на входе API. Constructor/API invalid→RunVisibilityError.invalid_input, без значений в message/repr. Query обозначает уже распознанный ordinary run, не адрес XML и не команду редактирования.

Limits поля: `max_queries=10000` (exact int1..10000), `styles:StyleContextLimits=default_factory`. Exact nested class, повторная проверка bounds на API. Только уменьшение. Exact tuple queries, включая пустой, no lazy iterable/list/subclass; exact Query records. Проверка длины до обхода/parse, excess→RunVisibilityError.resolution_limit_exceeded. Никакой обрезки. Вход data/SHA и StyleContextErrors/DocxErrors делегируются неизменному read_style_context с exact styles limits; даже empty queries проверяют package/hash. Новые errors только invalid_input и resolution_limit_exceeded со static code/message. Import/API без app I/O/секретов/env/сети/процессов/DB/модели.

Batch поля: `source_sha256`, `profile='docx-visibility/run-rules-v1'`, `policy_version='docx-analysis-policy/final-visible-no-comments-v2'`, `context_sha256` (тот же catalog digest), `results:tuple[RunVisibility,...]` (repr=False). Порядок один к одному с queries; duplicate queries не теряются. RunVisibility поля: `status` (`visible|hidden|blocked`), `code:str|None`, `hidden:bool|None`, `spec_vanish:bool|None`, `web_hidden:bool|None`. Resolved code=None, status определяется только hidden. Blocked: три bool=None, один static code. Batch не имеет complete/analysis_text/anchors/собственного manifest и не является допуском ML. Новый snapshot/mapper получает отдельный contract b2a2b2, не расширяет meaning этого результата.

Прочитать catalog ровно один раз на batch. Подготовить ID index и defaults один раз, не искать definitions для каждой query по tuple и не строить весь context повторно. O(catalog + queries) после catalog parser; никаких cache/retained ZIP/XML. Consumer не передаёт свой context/вычисленные свойства: resolver сам читает pinned bytes и возвращает их fingerprint. Actual main reader позднее должен доказать, что queries соответствуют этим же bytes, и добавить direct-property provenance.

Порядок для каждой query:
1. Catalog.status=blocked → code `style_context_blocked`, даже при direct_vanish=false. Absent catalog обрабатывается как отсутствие default/definitions, не ошибка сам по себе.
2. Paragraph selection: explicit ID, иначе catalog.default_paragraph_style, иначе отсутствие. Выбранного ID нет→`missing_paragraph_style`; wrong type→`paragraph_style_type_mismatch`; selected record не resolved→`unresolved_paragraph_style`.
3. Character selection: explicit ID; ошибки соответственно `missing_character_style`, `character_style_type_mismatch`, `unresolved_character_style`. При отсутствии explicit ID: отсутствующий default character style либо resolved default без единого true visibility property считается нейтральным; никакой style не выбирается. Blocked default или любой true→`implicit_character_style`. Neutral default не подмешивается вместо C. Default character wrong type невозможен из trusted catalog, не угадывать альтернативу.
4. D — default vanish (None→false), P/C — выбранные style vanish (None→D), отсутствующий style также D. Effective hidden = explicit direct_vanish, если задан, иначе `D XOR P XOR C`. False — заданное значение. Внутри basedOn уже взято nearest, новый XOR предков запрещён.
5. spec_vanish и web_hidden: default (None→false) → заданное paragraph value → заданное explicit character value → direct value. Обычное наследование/override, без XOR. Значение None пропускает уровень; false выключает. На ordinary run specVanish не скрывает текст, webHidden в выбранном постраничном режиме тоже не скрывает. Их effective bool возвращается как metadata для дальнейшего reader, hidden определяется только vanish.

Прямые свойства не отменяют unresolved style/context blockers. Не разрешать paragraph mark, table/numbering/section/revision context через этот API. Отсутствие соответствующих параметров не доказывает, что run вне такого контекста: это обязанность будущего reader, до интеграции реального анализа нет. Native Word comparison/default-character semantics остаются release gate из design; synthetic truth table не заменяет Word.

Независимая приёмка до source: восемь буквальных строк D/P/C truth table, absent levels при D=false/true, nearest basedOn false/true, direct true/false overrides, отдельное обычное inheritance spec/web и их отсутствие влияния на hidden. Default paragraph/character selection, exact-case IDs, all static blocker reasons, precedence и невозможность bypass direct=false. Duplicate/empty batches, source/style digest identity, original bytes unchanged; strict inputs/limits повторно, max_queries exact/+1, batch10000 с общим context, fresh-process no I/O, legacy catalog/projection regressions. Только синтетические данные; frozen tests после freeze не менять.
