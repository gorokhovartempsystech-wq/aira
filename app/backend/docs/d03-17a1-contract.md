# D03-17A1 — точный снимок текста DOCX и адреса замечаний

31 октября 2026. Первый implementation cycle после [проекта D03-17](d03-17-design.md), рекомендован Sol 6.1 High. Pure подготовка документа; не запуск анализа. Продуктовые границы — current-product-scope.md. Этот контракт не разрешает менять их или старые проверки.

## Разрешённые изменения и порядок

Новый пакет `src/ara/docx_analysis/`: `__init__.py`, `snapshot.py` и необходимые приватные helpers только для snapshot/mapping. Новая frozen приёмка `tests/acceptance/test_docx_analysis_snapshot.py`; собственные дополнительные `tests/docx_documents/test_analysis_snapshot*.py`. Документы: этот контракт до freeze, `d03-17a1-result.md`, development-queue.md и d03-17-design.md только статус/ссылки на фактический результат. Технические уточнения после freeze не должны ослаблять критерии; существенный конфликт требует отдельного решения.

Нельзя менять projection/native/editor/storage/API/старый analysis contract, существующие тесты, schemas/migrations, scripts/check.sh, dependencies, runner/tasks/progress/AGENTS. Нельзя импортировать код Артёма, запускать ML/HTTP, читать секреты/архив или мигрировать main. Нет новых endpoints, daemon/таймеров, файловых кэшей, очереди или UI.

Порядок: новая приёмка → локальный freeze commit → ожидаемый red → реализация → targeted и полный `bash scripts/check.sh` → сверка baseline БД → результат/локальный commit без push. Приёмка после freeze неизменна без конкретного разрешения пользователя. Эта задача не требует Word render: bytes не преобразуются и новый DOCX не создаётся. Проверять точность XML-address/text на синтетических packages, а не визуальной догадкой.

## Публичный API

Экспортировать из `ara.docx_analysis`:

```python
build_snapshot(
    data: bytes, *, document_id: UUID, storage_revision: int,
    source_sha256: str, limits: SnapshotLimits | None = None,
) -> AnalysisSnapshot

map_span(
    snapshot: AnalysisSnapshot, *, fragment_id: str,
    start: int, end: int, quote: str,
) -> MappedSpan
```

Также экспортировать DTO ниже и `SnapshotError`. Только concrete bytes, UUID (не строка), exact int (bool запрещён), revision в 1..9223372036854775807, lowercase hex SHA256 длиной64, limits точного типа/None. Hash переданных bytes обязан совпадать; никакого чтения current версии из БД. До SHA/parsing проверить default package size32MiB. Вызывать существующий `project_docx(data)` с его неизменными default package/projection limits; не принимать непроверенную caller projection. UUID принадлежность scope не проверяется pure функцией: это обязанность будущего сервиса.

Все DTO frozen/slotted; коллекции tuple, вложенные anchors — существующий `SourceAnchor`. Строки документа/цитаты и содержащие их агрегаты `repr=False`. Никаких DocxSource/DocxProjection/original bytes или скрытой копии package в возвращаемом snapshot. Импорт/создание limits/обе функции не открывают сеть/БД/пользовательские файлы, не читают env и не логируют; штатная загрузка Python-модулей не считается прикладным I/O. Чтение ZIP в памяти разрешено.

`SnapshotLimits` имеет exact positive int поля:

| Поле | Default | Значение границы |
|---|---:|---|
| max_fragments | 10000 | Число included paragraphs |
| max_text_characters | 1000000 | len(analysis_text), включая synthetic separators |
| max_segments | 100000 | Суммарное число ненулевых mapped spans |
| max_coverage_items | 10000 | Все записи coverage, включая notices |

Границы включительные; превышение отвергает весь build, ничего не обрезает/возвращает частично. Эти limits — пределы pure builder, будущий ML adapter вводит свой более узкий предел512 fragments. Caller может задать меньший или больший positive предел, неизменные package/projection limits продолжают действовать. Проверять бюджеты до роста результирующих коллекций/конкатенации сверх них; входной XML уже ограничен существующим projection.

## DTO и адреса

`AnalysisSnapshot`: document_id, storage_revision, source_sha256, extractor_version=`docx-analysis/main-body-v1`, main_part, body_anchor, fragments, analysis_text, coverage, has_unprojected_content, complete, text_sha256, snapshot_sha256. Версия строго константная в A1; не давать caller выбрать неизвестный extractor.

`AnalysisFragment`: fragment_id, paragraph_anchor, ancestry, text, analysis_start, analysis_end, segments. Ancestry — tuple anchors: body первым; для каждого уровня таблицы добавляются table→row→cell, затем вложенный уровень по тому же правилу. Paragraph anchor хранится отдельно. В fragment и его segments все anchors принадлежат source SHA/main_part; path — tuple неотрицательных exact int. Global [analysis_start,analysis_end) указывает ровно на text в analysis_text. Coverage anchors могут указывать на другую part: её имя должно совпадать с part_name записи, SHA остаётся общим.

`AnalysisSegment`: kind=`text|tab|break`, anchor, run_anchor (nullable), start, end. Диапазон локален внутри fragment, ненулевой; текст сегмента берётся как slice fragment.text. Ненулевые сегменты без дыр/перекрытий покрывают весь fragment: первый start0, последний end=len(text). Zero-length spans из projection не создают сегменты. Сегменты не объединять даже при одинаковом run — каждый сохраняет исходный XML anchor. Hyperlink text поддерживается через его w:t/run anchors; URL не открывается.

`CoverageItem`: status=`included|empty|blocked`, code, part_name, anchor (nullable), fragment_id (nullable). Порядок: сначала обход body blocks в XML order, затем notices ровно в порядке projection. Для каждого Paragraph/OpaqueBlock одна запись; для каждого notice ещё одна, даже если относится к уже blocked paragraph. Table/row/cell сами не создают запись — покрытие текста ведётся по leaf blocks. Codes:

- чистый непустой paragraph: `paragraph`, included, fragment_id;
- чистый empty/whitespace-only paragraph: `empty_paragraph`, empty, fragment_id=None;
- paragraph с has_opaque/opaque span: `opaque_paragraph`, blocked, fragment_id=None;
- OpaqueBlock: `opaque_block`, blocked, fragment_id=None;
- notice: `notice:` + исходный notice.code, blocked, fragment_id=None, part_name/anchor из notice.

Не копировать unknown XML/element text в code/error. `has_unprojected_content` копирует projection flag; если он true при отсутствии обычных blocked records, добавить в конец blocked `unprojected_content` с main_part/body_anchor. Это defensive учёт, а не разрешение игнорировать flag. `complete` равно отсутствию blocked и false-флагу has_unprojected_content; included count может быть0. Сам snapshot не имеет status «проверен» или «замечаний нет».

`SourceSlice`: kind, anchor, run_anchor, start, end; offsets относительно исходного Span.text (не всей XML строки/UTF8 bytes). `MappedSpan`: fragment_id, paragraph_anchor, start, end (локально в paragraph), slices (tuple SourceSlice). Отдельную копию quote не хранить.

## Извлечение без потерь внутри поддержанного абзаца

Обходить существующую projection рекурсивно blocks→rows→physical cells→blocks. Никакого размножения gridSpan/vMerge, row flattening или восстановления визуальной сетки. Каждый чистый paragraph с `text.strip() != ''` — отдельный fragment. strip используется только как проверка пустоты: сохраняемый текст не изменяется. Заголовки, пункты списков, строки короче12 символов, повторяющиеся абзацы и параграфы таблиц обязательно включаются. Не добавлять synthetic list labels, Markdown, section titles, пробелы или значения properties/fields.

Перенести exact paragraph.text и supported spans. TAB/LF остаются исходными code points; не нормализовать CR/LF сверх уже выполненного projection, Unicode NFC/NFD, nonbreaking spaces или emoji. Opaque paragraph целиком blocked: не выделять пригодные куски по обе стороны объекта. Буквальный U+FFFC в обычном text span включается, opaque определяется по структуре. Чистый whitespace-only paragraph получает empty; opaque имеет приоритет даже при пустой видимой строке.

`analysis_text = '\n\n'.join(fragment.text for fragment in fragments)`. Между adjacent included fragments ровно два LF, начального/конечного synthetic LF нет. Сепараторы не принадлежат fragment/segment и не получают Word anchor. Empty/blocked не дают separators сами по себе. При blocked такой текст пригоден только как внутренний артефакт, не как разрешение частичного product run.

## Детерминированные digest и проверка span

Canonical JSON: UTF8, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False. UUID — canonical lowercase str, storage_revision — decimal str, paths/tuples — JSON arrays; отсутствующее значение — null. Anchor JSON имеет ровно source_sha256, part_name, path. Никаких dataclass repr/pickle/process hash, sorting paragraphs по тексту или unordered sets.

fragment_id=`f-` + SHA256(canonical JSON объекта с keys domain=`docx-analysis-fragment/1`, source_sha256, part_name, path). SHA берётся от UTF8 bytes, lowercase64hex. Doc UUID/revision не включаются в fragment ID; отдельная snapshot identity их сохраняет. Одинаковый текст по разным путям даёт разные IDs; изменение package SHA меняет IDs. Не обещать стабильность IDs между редактированиями.

text_sha256 — SHA256 от exact analysis_text UTF8. snapshot_sha256 — SHA256 canonical JSON manifest. Manifest имеет все поля AnalysisSnapshot кроме самого snapshot_sha256; JSON имя каждого поля совпадает с DTO, вложенные fragment/segment/coverage/anchor objects содержат ровно перечисленные здесь поля, в том числе text/analysis_text. extractor_version задаёт домен manifest. Поэтому identity, порядок, segments, coverage и separators связаны digest. Текст может повторяться внутри manifest; не сохранять manifest bytes в DTO/логе. Смена revision/doc ID меняет snapshot digest даже при одинаковых bytes.

map_span работает только с AnalysisSnapshot, возвращённым builder; API wire deserialization в A1 отсутствует. На boundary проверить форму/внутренние инварианты DTO, source/profile, ordered ranges/segments/IDs и manifest/text digests; malformed/replaced DTO отвергать invalid_snapshot. Included coverage соответствует fragments взаимно однозначно, empty/blocked не ссылаются на fragment; complete/flag/статусы согласованы. Это проверка согласованности, **не аутентификация DOCX**: без original bytes нельзя доказать, что полностью пересобранный злоумышленником DTO соответствует package. Будущий сервис всегда сам строит snapshot из pinned source, не доверяет присланному manifest.

Проверить exact types для fragment_id/quote и start/end (bool не int), известный fragment и `0 <= start < end <= len(fragment.text)`, затем точное равенство quote slice. Все индексы — Python Unicode code points. Не искать похожий quote и не пересчитывать UTF16 offsets молча. Пересечь диапазон с segments в исходном порядке; для каждого непустого пересечения [a,b) вернуть SourceSlice(start=a-segment.start, end=b-segment.start). Объединённые slices обязаны реконструировать exact quote; один issue может пересекать несколько runs, TAB и LF. Диапазон не может пересечь paragraph boundary или synthetic separator: API принимает fragment-local offsets.

## Ошибки

`SnapshotError(ValueError)` с безопасными code/message без аргументов/текста источника:

- invalid_input — неверная входная identity/тип/limits;
- source_mismatch — SHA валидной формы не совпадает с bytes;
- snapshot_limit_exceeded — один из новых budgets превышен;
- invalid_snapshot — нарушены DTO/profile/manifest invariants;
- unknown_fragment — валидный по типу ID отсутствует;
- invalid_span — offset/quote неверны.

Существующие DocxError/ProjectionError из package/projection могут проходить без изменения их безопасного сообщения/code. Не оборачивать неизвестные programming errors как «документ пустой». Ошибки не содержат bytes/text/quote/path файлов пользователя. Repr агрегатов тоже не должен раскрывать text или opaque payload.

## Обязательная приёмка

1. Детерминированный snapshot; exact короткий/heading/list/mixed-run text, пробелы по краям, hyperlink/TAB/LF, emoji+combining code points. SHA/manifest/IDs проверены независимо через canonical expected JSON, а не вызовом приватного production helper.
2. Nested tables/physical merged cells: точный порядок и ancestry, ни один paragraph не потерян/не размножен. Два одинаковых текста имеют разные anchors/IDs; doc/revision identity влияет на snapshot digest.
3. Exact span через несколько text/runs/TAB/LF; reconstruct quote из original projection spans, anchors указывают на правильные XML nodes. Emoji не сдвигает code-point mapping. Wrong quote/UTF16 indices/zero/negative/bool/out-of-range/unknown ID отвергнуты, нет поиска первого похожего текста.
4. Opaque paragraph/whole-body complex field/tracked revision/unsupported story или notice: blocked coverage, complete=false, оригинальные bytes неизменны; полный источник не выдаётся за полностью проверяемый. Literal U+FFFC включён, empty/whitespace и empty DOCX учитываются без фальшивых fragments.
5. Точные лимиты и +1 для fragments/chars с separators/segments/coverage, включая notices; package/projection errors сохраняются; неверные hash/revision/types/limits не вызывают I/O. Large budget не отключает package limit.
6. dataclasses.replace/tampered digest/text/range/anchor/source/profile/ID/coverage отвергнуты map_span; malformed DTO не даёт случайный IndexError/KeyError с пользовательским содержимым. Fully consistent DTO не считать cryptographic proof источника.
7. Frozen immutable graph, без source ZIP/DocxSource; repr/error не содержат synthetic secret-like markers из документа. Subprocess import + build/map при запрещённых network/DB/file/env access подтверждает inert API; пакет не импортирует upstream/ML/HTTP.

Синтетические DOCX создавать в memory/test helpers без копирования пользовательского архива. Main/runtime DB baseline остаётся прежним. Полный gate должен сохранить все существующие проверки. В результате указать число tests/subtests/exit, фактические ограничения и local commit; не закрывать runner task вручную.

После A1 возможны независимые B1 strict validation/fixtures и A2 inventory по собственным контрактам. Настоящий запуск требует worker/coverage/weights/token guard; остановка/пять минут, persistent filters и frontend здесь не реализованы. Не добавлять их в A1 ради «готовности проверки».
