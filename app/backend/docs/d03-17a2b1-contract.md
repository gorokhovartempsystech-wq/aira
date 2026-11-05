# D03-17A2b1 — первый reader итогового текста и multi-source ranges

1 ноября 2026, контракт реализации на Sol 6.1 High после [дизайна A2b](d03-17a2b-design.md). F06/F08/F11. Продуктовая policy: Final revisions, comments preserve/exclude; согласована Никитой, повторно не спрашивать. Это narrow main reader, не full Word/ML/UI.

## Файлы и цикл

Allowed: только новый пакет `src/ara/docx_analysis/final_view/` с __init__.py и приватными helpers; новая frozen `tests/acceptance/test_docx_final_view.py`, собственные `tests/docx_documents/test_final_view*.py`. Документы: этот контракт до freeze, d03-17a2b1-result.md, development-queue.md и d03-17a2b-design.md только статусы/ссылки. Existing ara.docx_analysis/__init__, A1/A2a/projection/package/native/editor/HTTP/ML/storage/schema/dependencies/scripts/old tests/runner/tasks/progress/AGENTS не меняются. Импортировать новый API по submodule; не добавлять exports в старый __init__.

Новая приёмка → отдельный локальный freeze commit → red → source → targeted/full `bash scripts/check.sh` → baseline schemas/counts → result/local commit без push. После freeze приёмка неизменна без конкретного разрешения. Никаких секретов, пользовательского архива, .env, БД/сети/процессов/файловых кэшей при import/API. Original ZIP не экспортируется заново. Main БД не мигрировать. Использовать synthetic in-memory packages; эталонные final strings фиксировать независимо от кода.

## API и вход

```python
from ara.docx_analysis.final_view import (
    build_final_snapshot, map_final_span, FinalViewLimits, FinalViewError,
    FinalSnapshot, FinalFragment, FinalPiece, ParagraphJoin,
    FinalCoverage, FinalMappedSpan, FinalSourceSlice,
)

build_final_snapshot(
    data: bytes, *, document_id: UUID, storage_revision: int,
    source_sha256: str, limits: FinalViewLimits | None = None,
) -> FinalSnapshot

map_final_span(
    snapshot: FinalSnapshot, *, fragment_id: str,
    start: int, end: int, quote: str,
) -> FinalMappedSpan
```

Exact bytes/UUID/int (bool запрещён), storage_revision1..9223372036854775807, lowercase64hex SHA, exact limits/None. Проверить размер archive≤32MiB до hash/parser, SHA должен совпасть. Использовать `open_docx(data)` с неизменными default DocxLimits; не принимать caller source/projection/inventory. Допустимо читать `inventory_docx`/AnalysisPolicy A2a и существующий `projection._parse.parse_main`/ProjectionLimits как helpers **без правок**. Либо свой bounded main parser с теми же validated ZIP boundary/chunks: EOCD signature в ZIP comment не должна менять выбранный archive. Не делать простой ZipFile на другой непроверенной directory.

XML parse main ограничен nodes/depth **до allocation**, включая deleted/unsupported subtrees; comments/PI не входят в element-only anchor paths, как A1. Стандартные Transitional и Strict namespaces, UTF8/UTF16 и nonstandard main part обязательны. Namespace определяется main document; одинаковые local names чужого namespace не становятся Word nodes. Прежние package/ProjectionError остаются безопасными ошибками своих типов.

FinalViewLimits (frozen/slotted) имеет exact positive int поля; default одновременно верхний технический предел, caller может только уменьшить его, не увеличивать и не получать silent clamp:

| Поле | Default/maximum |
|---|---:|
| max_nodes | 100000 |
| max_depth | 128 |
| max_paragraphs | 100000 |
| max_fragments | 10000 |
| max_pieces | 100000 |
| max_text_characters | 1000000 |
| max_coverage_items | 100000 |

max_paragraphs считает все w:p main tree до semantic pruning, max_nodes/depth — все XML элементы main. Остальные budgets — новые output records; text count включает synthetic separators, joins ограничены числом physical paragraphs. Проверять до расширения output сверх limit; превышение отвергает весь build. Все input package budgets остаются обязательными. Лимиты — технические, не согласованный максимум размера требований.

Точные error boundaries: archive/XML package oversize → прежний DocxError.package_limit_exceeded; main nodes/depth → ProjectionError.projection_limit_exceeded; max_paragraphs и output budgets → FinalViewError.view_limit_exceeded. Неправильные limits, в том числе выше maximum, → invalid_input. Empty logical groups не расходуют max_text_characters, но их исходные nodes/physical paragraphs расходуют входные budgets; вычислять длины nonempty output до materialization общего analysis_text.

## DTO и manifest

Все DTO frozen/slotted, collections tuple. Text/quote и содержащие их агрегаты repr=False; никакого исходного ZIP/XML/ET node/DocxSource/closure в snapshot. Anchors — существующий SourceAnchor, SHA совпадает, path tuple exact nonnegative int; main body/path пустым не бывает. Piece/source ranges — code points, не byte/UTF16 units.

В новых DTO также скрыть из repr main_part/part_name, anchor-поля и содержащие их tuples: имена package parts могут быть произвольными пользовательскими строками. Старый SourceAnchor и его собственный repr не менять; новый код его не логирует. Показывать в repr допустимо только static profile/policy/kind/code, hashes/IDs, offsets/counters.

| DTO | Поля |
|---|---|
| FinalSnapshot | document_id, storage_revision, source_sha256, profile, policy_version, main_part, fragments, analysis_text, coverage, complete, text_sha256, snapshot_sha256 |
| FinalFragment | fragment_id, story_anchor, flow_anchor, paragraph_anchors, text, pieces, joins, analysis_start, analysis_end |
| FinalPiece | kind (`text\|tab\|break`), anchor, run_anchor, paragraph_anchor, start, end, source_start, source_end |
| ParagraphJoin | left, right, marker (все SourceAnchor) |
| FinalCoverage | status (`included\|empty\|excluded\|metadata\|blocked`), code, part_name, anchor(nullable), fragment_id(nullable) |
| FinalMappedSpan | fragment_id, start, end (локально в logical text), slices |
| FinalSourceSlice | kind, anchor, run_anchor, paragraph_anchor, start, end (локально в source atom) |

profile строго `docx-analysis/final-main-v1`, policy_version строго `docx-analysis-policy/final-no-comments-v1`. Story и flow в b1 — один main body anchor; все paragraph/piece/join anchors принадлежат той же part/story/flow. Future profiles/другие stories не принимать молча. Последующие readers получают новый opt-in builder/profile; default этой функции и A1 не переопределяются задним числом.

paragraph_anchors — ordered tuple всех physical p логической цепочки, включая empty участники, без повторов; соседи соединены joins ровно N−1. Join.marker — конкретный del под pPr/rPr левого p, right — непосредственно следующий physical p body. Не join через p с retained boundary. Pieces упорядочены по XML preorder; каждый run/atom находится внутри своего physical paragraph. Piece source_start=0, source_end=end-start в b1; atom переносится целиком. Ненулевые pieces покрывают text без gaps/overlaps. Text literal U+FFFC допустим и отличается от unsupported structure. Empty text atoms не создают pieces.

В b1 run_anchor у piece/slice обязателен SourceAnchor, не None: atoms разрешены только как direct children run. Поэтому atom.path=run.path+(child_index,), physical p — direct child body, marker.path имеет форму left.path+(0,rPr_index,marker_index), где pPr обязателен первым. Left/right paths отличаются на1 в последнем индексе. Проверка формы адреса в DTO не заменяет проверку реального XML на build.

Canonical JSON: UTF8, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False; UUID str, storage_revision decimal str, остальные int — JSON integers, tuples — arrays; anchors имеют ровно source_sha256/part_name/path. manifest включает все поля FinalSnapshot кроме snapshot_sha256, все перечисленные поля вложенных DTO, без derived/private/runtime полей.

text_sha256 = SHA256 exact analysis_text UTF8. snapshot_sha256 = SHA256 canonical manifest. fragment_id = `lf-` + SHA256 canonical объекта с ровно keys: domain=`docx-final-fragment/1`, profile, policy_version, source_sha256, story_anchor, flow_anchor, paragraph_anchors, joins. Source SHA/profile/policy защищают смену чтения; ID не постоянен после edit. Document UUID/revision различают snapshot identity даже при одинаковом package, но не включаются в fragment_id. Manifest bytes/текст не логируются и не удерживаются дополнительно.

## Grammar первого reader

Два прохода: сначала context/grammar и границы main flow, затем emission. Если вне доказанно excluded subtree найдена неподдержанная main structure/двусмысленная граница, вернуть snapshot с fragments=(), analysis_text='', complete=false и blocked main-flow record. **Не выпускать соседние fragments из неизвестного разбиения.** Package validation/budget errors при этом остаются errors, а не incomplete snapshot. Это временная capability b1, не сужение полного DOCX scope.

Root: document с одним body; разрешён optional leaf background. Body содержит direct p и optional единственный последний sectPr. В b1 tables/SDT/customXml/AlternateContent/другие children блокируют main flow. Element text/tails вне текстовых atoms допускаются только whitespace; содержимое не терять через itertext/strip.

Tail у excluded del принадлежит окружающему активному контейнеру: правило исключения subtree не должно проглатывать непустой текст после закрывающего тега. XML comments/PI пропускаются лишь как нетекстовые nodes при построении element-only paths; текст atoms до/после них сохраняется стандартным parser.

Контекстная таблица разрешённых children (везде namespace текущего Word document):

| Parent | Children |
|---|---|
| p | не более одного pPr первым; r, hyperlink, inline ins/del; leaf bookmarkStart/bookmarkEnd/commentRangeStart/commentRangeEnd |
| hyperlink | r, inline ins/del; те же leaf bookmark/comment markers; hyperlink внутри hyperlink не поддержан |
| inline ins | r, hyperlink, nested inline ins/del и те же leaf markers; сохраняется весь допустимый active content |
| inline del | исключается всё subtree; не возвращать вложенный ins. Grammar descendants не интерпретировать, но XML/node/depth/byte budgets уже проверены |
| r | не более одного rPr первым; leaf t/tab/br/cr, leaf commentReference; остальное blocked |
| pPr | не более одного каждого: pStyle, spacing, ind, jc, outlineLvl, keepNext, keepLines, pageBreakBefore; numPr; paragraph-mark rPr |
| numPr | только leaf ilvl/numId, каждый не более одного |
| paragraph-mark rPr | разрешённые leaf formatting из следующей строки + не более одного leaf ins **или** del |
| обычный rPr | только leaf b/bCs/i/iCs/u/strike/dstrike/color/highlight/sz/szCs/vertAlign/lang/rFonts, каждый не более одного |
| body/sectPr | только leaf pgSz/pgMar/cols/docGrid, каждый не более одного |

Все перечисленные простые pPr formatting children — leaf; никаких спрятанных w:t внутри properties. Обычный rPr не содержит revision container/mark. pPrChange/rPrChange/sectPrChange и другие histories, pPr/sectPr, moves/ranges, fields/instrText, sym/vanish/specVanish/webHidden, drawings и другие элементы в active ветви пока blocked. Не использовать substring/local-name.endswith('Change') как разрешение игнорировать произвольную XML ветку. Attributes оформления сохраняются в source и не исполняются; t сохраняет exact decoded text/xml:space без trim, tab→TAB, br/cr→LF. br type отсутствует либо textWrapping/page/column; неизвестный type — blocked, рендер страниц не обещан.

Разрешённые revision nodes требуют w:id, matching `[+-]?[0-9]{1,20}`; это узкая техническая grammar, не полный OOXML validator. Автор/дата не используются, не выводятся и не сравниваются для решения видимости. Повтор id в независимых ins/del не склеивает узлы; identity основана на anchors. Missing/nondecimal id, children у paragraph-mark revision, одновременно ins+del или duplicate singleton properties — unsupported main flow. Не принимать body-level ins/del как inline wrapper. Semantic attributes/parents перечислены выше; extension attributes не дают права интерпретировать неизвестные children, mc:AlternateContent не выбирается в b1.

Комментарий Word: leaf markers/reference не дают текста; comments parts сохраняются и исключаются по policy. Bookmark leaf тоже не даёт текста, но не удаляет текст между start/end. External hyperlink target никогда не загружается; переносится только явно записанный display text.

## Итоговые paragraphs и coverage

Для каждого supported physical p получить sequence active atoms и mark decision: обычный/ins → retain, del → join-next. Paragraph-mark revision относится только к границе, не ко всем runs. Сначала применить inline исключения, затем объединить maximal цепочки join-next. Между составляющими цепочки не вставлять ни LF, ни пробел. Last p с deleted mark (нет successor) блокирует main flow, не бросать молча хвост. Пустой p с deleted mark остаётся в chain, с retained mark закрывает chain. Только после сборки: text.strip()=='' → empty logical group, иначе один FinalFragment с исходным text без trim/normalization. analysis_text — nonempty fragments, соединённые ровно '\n\n', без начального/конечного synthetic delimiter.

Каждая part inventory получает один record с anchor=None/fragment_id=None. Main: metadata/main_part; package_metadata и три exact doc-properties MIME из A2a: metadata/package_metadata. Comments: excluded/comments_policy. **Все прочие parts**, включая styles/settings/numbering/theme/fonts/media/stories/unknown, в b1: blocked/unread_part. Не ослаблять этот gate по одному MIME: последующие b2…b5 readers доказывают поддержанный контекст по отдельности. Extraction supported main может сохраняться при blocked другой part, complete всё равно false.

Если main supported, добавить metadata/main_flow_read(body). Для каждого physical p: included/paragraph с fragment_id его logical group, либо empty/empty_paragraph без fragment_id. Дополнительно для каждого посещённого active ins wrapper — metadata/inserted_content, внешнего semantic del — excluded/deleted_content (descendants не дают records), paragraph mark ins — metadata/inserted_boundary, del — excluded/deleted_boundary, leaf comment markers/reference — excluded/comments_policy, pPr и rPr properties roots — metadata/supported_properties. Одинаковый rPr root один record; вложенные простые properties отдельных records не требуют. Bookmark leaves — metadata/bookmark. Для неподдержанного main вместо всех main node records — один blocked/unsupported_main_flow(body); part records остаются.

Coverage сортируется `(part_name, 0 если anchor=None иначе 1, anchor.path или (), code, fragment_id или '')`. Exact duplicates запрещены. included paragraphs соответствуют всем paragraph_anchors fragments; excluded deletions не создают source pieces, joins имеют corresponding deleted_boundary. complete равен отсутствию blocked. Empty supported DOCX может быть complete с0 fragments; запрет empty_document принадлежит будущему запуску модели. Coverage не означает ML success и не предоставляет UI-маркер «частично проверено».

У всех records, кроме included/paragraph, fragment_id=None. Code/status пары ограничены перечисленной таблицей правил; произвольные комбинации/код из XML не допускаются. При validation output counts/anchor depth проверяются по hard maxima FinalViewLimits до expensive manifest serialization. Это проверяемые output ограничения; скрытые input nodes без исходного package повторно посчитать нельзя.

## Map и ошибки

map_final_span перед отображением проверяет точные DTO/types/константы, identity, canonical hashes/IDs, tuple paths, descendant/same source/flow relations, physical paragraph и piece order, отсутствие повторного включения одного physical p, непрерывность output intervals, joins N−1 и их marker locations, correspondence coverage. Проверяет ненулевой exact int range и quote == fragment.text[start:end]. Неизвестный fragment → unknown_fragment, неправильный quote/offset/type аргумента → invalid_span, повреждённый DTO → invalid_snapshot. Любое object.__setattr__/dataclasses.replace изменение без согласованности обнаруживается; полностью согласованный forged DTO всё ещё не является аутентификацией package. Будущий сервис строит сам.

Для каждого непустого пересечения [a,b) с piece возвращается FinalSourceSlice со start=piece.source_start+a-piece.start, end=piece.source_start+b-piece.start. В FinalMappedSpan нет единственного paragraph anchor: range может относиться к разным p. Не объединять соседние slices через разные XML atoms или исключённые участки. Сумма длин slices равна end-start, independent source-node reconstruction даёт exact quote. Existing editor command не вызывается и не принимается как output.

FinalViewError(ValueError): статические code/message invalid_input, source_mismatch, view_limit_exceeded, invalid_snapshot, unknown_fragment, invalid_span. Не добавлять цитаты/paths/авторов/raw XML в диагностику. Malformed DTO не порождает неожиданный IndexError/KeyError или traceback с source data. Existing DocxError/ProjectionError безопасно проходят; непредвиденную programming error не выдавать за «пустой документ».

## Frozen приёмка до source

1. `A + del(old) + ins(new)` → `Anew`, exact pieces/quote; nested ins/del, deletion dominates; excluded subtree budgets, literal U+FFFC/emoji/combining/TAB/LF/whitespace/empty atoms.
2. Deleted paragraph mark p1 A + p2 B → один AB, два source p, join marker; inserted mark → два A/B и separator только между fragments. Chains из3+ p, пустые p с обоими mark states, no added spaces; dangling/duplicate/conflicting marks → blocked main.
3. Все subranges короткого mixed/merged fragment независимо восстановлены по XML nodes, включая range через deletion gap/paragraph join. Repeated text не путает source, UTF16 ошибку не чинить. Нулевые/negative/bool/out-of-range/wrong quotes отвергнуты.
4. Exact grammar отказа: tables, moves, fields cross-p, unknown active namespace, hidden properties/old-properties, section-crossing, child text/tail вне atoms. Не превращать неподдержанные элементы в частично чистый main text. Excluded del может содержать unsupported markup, но package/XML/limits остаются обязательными.
5. Inventory ledger всех частей, comments policy и markers, blocked style/story/media/unknown, empty complete/0fragments; source bytes/hash неизменны. Ни part classification, ни ignored comments не снимают unrelated blocker.
6. Independent canonical JSON/hash/IDs; identity/profile/policy mutations, rehashed malformed piece/join/coverage/source/flow, immutability/repr, safe malformed objects. Freeze old A1/A2a совместимость.
7. Strict/Transitional, UTF8/UTF16, renamed main, XML comments/PI, EOCD-comment signature fixture; package/depth/node/excluded-content limits и exact/+1 output budgets. Fresh subprocess import/build/map при запрещённых application file/env/network/DB operations, без ML/upstream/UI imports.

Для b1 автоматическая приёмка проверяет текст/адреса, не Word layout. Native Word final-view comparison остаётся общим release gate; исходный DOCX не модифицируется. Отчёт содержит red/targeted/full/baseline и оставшиеся ограничения. После b1 можно продолжать b2a по отдельному contract на Sol6.1 High; не возвращаться к Astra для обычной реализации уже заданных правил.
