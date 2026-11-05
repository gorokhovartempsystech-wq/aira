# D03-17E4A — консервативное сопоставление замечаний между source

3 ноября 2026. Цикл F09/F12 после E3 gate3974passed (bfe420a).
Контракт/приёмка фиксируются до source и красного прогона.
Пакета ML нет, только synthetic validated B2 records. Это pure mapper, не запись
preferences и не новая продуктовая спецификация. Следом E4B effective visibility
и explicit unhide с CAS, затем отдельная сквозная приёмка. Полный F09 по одному
mapper не заявляется.

Allowed: новый `src/ara/docx_analysis/remapping/{__init__,_models,_context,_match}.py`,
новый `tests/acceptance/test_docx_review_remapping.py`, docs contract/result/queue.
Старые E1/E2/E3 source/tests/schema/runner/deps не менять. Import/call без I/O,
БД, модели, clock, глобального состояния. Всё source/metadata только in-memory;
диагностика/DTO repr не содержат документ. Existing package bounded parser reuse.

## Контракт

`match_findings(previous, current, *, limits=None) -> tuple[FindingTransfer,...]`.
Оба аргумента exact tuple(SourceBundle,AttemptBundle,ResultBundle), не готовый
непроверенный snapshot. Оба результата заново проходят B2 restore_result;
constructor/hash-only не доказательство. Снимок JSON разрешено использовать
только после этого. Existing E1 internal key derivation можно переиспользовать
на проверенном body; key algorithm неизменен. FindingTransfer хранит только
previous_finding_id/previous_key/current_finding_id/current_key. Детерминированный
порядок по previous finding ID. Функция не принимает решения, какие findings
пользователь скрыл; следующий storage слой применяет только активные решения.

`RemapError.code`: invalid_input/corrupt_result/limit_exceeded; фиксированный
текст без фрагментов. `RemapLimits(max_paragraphs=10000,max_findings=10000)` —
positive exactint≤default, bool/forged/subclass отвергаются. Существующие B2
source/manifest/reply/text limits обязательны. Проверить обе стороны целиком;
нет частичного результата при corruption/budget. Только current B2 profile
final-visible-main-v1; tables/stories/complex sections не объявляются поддержанными.

Оба документа должны иметь одинаковый UUID, иначе invalid_input. Profile/policy
и все model/adapter/engine/execution provenance кроме attempt_id должны совпасть;
иначе нет переносов (не считать разные модели эквивалентными). На exact source
использовать совпадение E1 ключей; revision/attempt не влияют. Даже этот shortcut
выполняется после B2 проверки обеих сторон и лимитов.

## Cross-source paragraph evidence

Поддерживаемая сейчас структура B2 — direct paragraphs единственного main body.
Другие структуры/профили не выдумывать. Из bounded source XML берётся дерево
каждого paragraph, включая direct formatting, скрытое/удалённое содержимое и
inline wrappers. Это намеренно строже visible text: изменённая структура/скрытый
контекст не наследуют hide. Дерево hash включает expanded tag names, sorted attrs,
text и порядок children; container whitespace/tails можно игнорировать только
там, где проверенный grammar допускает лишь whitespace. Leaf text сохранять точно.

Контекст включает main_part/root namespace/body ancestry, общий hash всех
non-main parts кроме core/custom/extended document properties (metadata dates не
меняют смысл), terminal sectPr tree. Любые изменения style definitions/relations/
section settings conservatively снимают cross-source matching. Для heading и
другого paragraph formatting дополнительно prefix hash последовательности
предыдущих paragraphs с pPr; это консервативно блокирует перенос через изменённый
заголовок даже дальше непосредственного соседа. Нет эвристики по имени Heading.

Полный visible text (не отдельная quote) должен быть уникален в каждом документе.
Повторяющийся/пустой paragraph не участвует в переносе. Base candidates:
exact visible text + exact paragraph tree + ancestry/formatting prefix context.
Однозначные candidates по всем paragraphs задают пары индексов. Удаляются **все**
пары, участвующие в пересечении порядка (не выбирать один LIS/nearest/first).
После этого у evidence должны совпасть text hashes непосредственных retained
paragraph соседей (включая пустые) либо явные boundary sentinels. Вставка/удаление
далеко от evidence разрешена; adjacent/context/split/join/moved-crossing запрещены.
Это текстовое консервативное сопоставление, не доказательство семантической
эквивалентности после произвольных внешних перестановок.

Primary и related каждого finding обязаны пройти mapping. Совпадают start/end/
quote и каждый slice: kind, source start/end, paths относительно собственного
paragraph; не пересчитывать offsets по substring search. Target fragment получает
его реальные current anchors. Semantics type/severity/assessment/explanation/
question/private rule совпадают. Upstream issue ID, confidence, suggestion
исключены как в E1; новое related evidence/более сильная severity не скрывается.
Неоднозначный finding fingerprint не переносится. Никаких partial issue matches.

## Приёмка до кода

Exact source/newattempt/revision; archive metadata only; far insert/delete/edit;
adjacent edits, changed rest of evidence, duplicate paragraphs, split/join,
moving intact paragraph group across unchanged text; headings/format/style/section;
repeated quotes in distinct paragraphs; Unicode and discontiguous hidden-run slices;
primary+related pair; model/rule/severity/context changes; private noise ignored;
corrupt source/manifest/request/reply/result and limits, cross-doc, immutable bytes,
no source text in repr/error. Independent matrix checks expected candidate IDs/keys,
не просто вызывает helper реализации для ожидаемого ответа. Freeze/red→targeted
E1/B2 regression→full/hash/main V8 snapshot→local commit.
