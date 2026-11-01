# D03-17A2b — итоговый текст Word и несколько исходных адресов

1 ноября 2026, Astra 6 High, после `26377a1`. Архитектурный цикл по команде Никиты «Давай дальше» после переключения режима. F06/F08/F10/F11, [действующий scope](current-product-scope.md). Изменения этого цикла: этот документ, d03-17a2b1-contract.md, d03-17a2b-result.md, ссылки/статусы в d03-17-design.md и development-queue.md. Код, тесты, схемы, зависимости, БД, runner/tasks/progress и продуктовые решения не менять.

## Решение и совместимость

Создать отдельный pure reader `ara.docx_analysis.final_view`, отдельные DTO и versioned profile. A1 build_snapshot/map_span/main-body-v1 остаются совместимыми. A2a inventory остаётся metadata inventory, его category не становится доказательством полноты. Исходные ZIP/XML/правки/комментарии никогда не изменяются ради анализа.

Проверяемая строка строится из **логических абзацев**, каждый может состоять из нескольких физических w:p и нескольких несмежных исходных текстовых узлов. Каждому символу соответствует конкретный исходный atom; отсутствие символов также учитывается в coverage. Удалённый paragraph mark хранится как связь между абзацами, а не как выдуманный символ. Политика Никиты уже согласована: итоговый текст revisions, comments сохранять без анализа. Новых переключателей Final/Original и кнопки «Принять все правки» не добавлять.

```mermaid
flowchart LR
    S[Неизменяемый DOCX] --> P[Проверенный пакет и XML]
    P --> R[Контекстные правила revisions и stories]
    R --> L[Логические абзацы и карта исходных атомов]
    L --> C[Учёт всех частей и пропусков]
    C --> A[Допуск к модели]
    A --> M[Замечание с точной цитатой]
    M --> H[Один или несколько диапазонов подсветки]
```

Вход downstream всегда server-built snapshot из pinned SavedTarget; не принимать недоверенный manifest как доказательство DOCX. Digest проверяет согласованность, не авторизацию/подлинность. Ни original data, ни ET nodes, DocxSource, ZipFile, родительские closures не удерживаются в DTO. Импорт/API инертны, text/quotes/raw metadata скрыты из repr/errors/logs.

## Основания, которые влияют на алгоритм

| Основание | Проверенное наблюдение | Наше решение |
|---|---|---|
| Локальный A1/projection/_project.py, audit .runtime/d03-17a2b-design-audit.json | Любые revisions дают opaque. В synthetic A + deleted mark + B остаётся один B, complete=false | Это корректная граница A1; не снимать его защиту, нужен новый reader |
| [Deleted, Microsoft](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.deleted?view=openxml-3.0.1) | Удаление paragraph mark соединяет текст с последующим абзацем и не удаляет автоматически его содержимое | Соединять output, сохранять оба source paragraph anchors; не удалять весь w:p |
| [MS-OI29500 §17.13.5.20](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oi29500/1d66ba8a-1eeb-4cff-ab8a-eaa79113cc89) | Уточнение поведения Word разрешает противоречие старого текста стандарта: ins на paragraph mark означает вставленную границу | Final оставляет такую границу; ins и del на mark не эквивалентны |
| [InsertedRun](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.insertedrun), [MoveFrom](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.movefrom?view=openxml-3.0.1) | Inline insertion и paragraph-mark movement относятся к разным уровням | Диспетчер по parent/context, не глобальное удаление всех элементов с одним local-name |
| [FieldChar](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.fieldchar?view=openxml-3.0.1) | Код и сохранённый результат complex field имеют отдельные области; nested/unclosed fields требуют особого поведения | Отдельный bounded field state machine, только сохранённый результат, без исполнения инструкций; до reader — blocked |
| [HeaderReference](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.headerreference), [Footnote type](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.footnoteendnotetype.type?view=openxml-3.0.1) | Колонтитулы наследуются между секциями, notes имеют normal/separator виды | Читать references/контекст, не считать каждый orphan частью активного текста и не анализировать separator как требование |

Первичные источники прочитаны 1 ноября; ссылки описывают формат, не результат нашего Word QA. Источник с ошибочным описанием ins не копировать в expected fixtures. Продукт не получает «проверку соответствия ISO» из-за использования документации OOXML.

## Представление и отображение

Новый profile начинает с `docx-analysis/final-main-v1`. Новая capability/семантика чтения требует явной следующей версии; старые snapshots/results не переинтерпретируются. Policy version A2a включается в manifest. Identity: document UUID/storage revision/source SHA/profile/policy. Порядок output детерминирован, все offsets — Unicode code points, не UTF8 bytes/UTF16 units. Frontend переводит единицы явно и проверяет hash источника.

Fragment содержит story anchor, flow anchor, ordered physical paragraph anchors, exact text, pieces и joins. Story — body/header/footer/одна note/textbox; flow — последовательность абзацев одного контейнера (например, body или конкретной ячейки). Join запрещён между разными stories, ячейками, неизвестными контейнерами. Между независимыми fragments — synthetic два LF в analysis_text; они не имеют исходного адреса и не входят в локальные offsets fragment.

Piece: kind text/tab/break, source anchor, run anchor, physical paragraph anchor, output [start,end), source [start,end) внутри декодированного значения atom. На первом reader atom переносится целиком: source_start0. Между pieces могут быть удалённые узлы; они не входят в quote и не подсвечиваются. Нулевые pieces не нужны. Source atom для TAB/LF — соответствующий XML element с виртуальным значением одного символа, не XML byte range.

Join: left/right physical paragraph anchors и anchor удалённого mark. Например p1=`A`, deleted mark, p2=`B` → `AB`, два pieces и один join; range `[0,2)` даёт два source ranges, между ними не добавляется пробел. A + deleted `old` + inserted `new` → `Anew`; вложенная вставка внутри удалённой ветки не возвращает эту ветку. Empty paragraphs остаются участниками цепочки до её закрытия; только затем whitespace-only logical paragraph становится empty, а не требованием.

Map_final_span проверяет snapshot/profile/digests, fragment ID, точный quote и ненулевые локальные offsets, возвращает ordered source slices. Нельзя отдавать один диапазон от первого до последнего XML node: он захватит удалённый текст. Нельзя чинить offsets поиском цитаты или адресовать другой похожий абзац. Для source view — несколько highlights; для final-view review — локальный range. Такая подсветка **не является разрешённой native edit command**. Существующий редактор защищает opaque revisions; редактирование этих структур/UI Ани требует отдельного контракта.

Готовый B1 ML result adapter должен валидировать snapshot один раз за bounded batch, затем пользоваться внутренним проверенным индексом pieces; публичный map остаётся строгим. Не пересчитывать огромный manifest на каждом из10000 issues. Engine получает exact final fragment text/IDs; его parse_text/эвристический status не используется. Скрытие замечания fingerprint включает profile/policy/source evidence; смена способа чтения не переносит hide автоматически.

## Контекстная семантика и безопасные границы

| Контекст | Final-view правило | Реализация/ограничение |
|---|---|---|
| Inline w:ins / w:del | Читать ins, исключать целиком del; descendant deletion имеет приоритет над insertion внутри исключённой ветки | b1; XML/size/depth limits действуют и на исключённые ветки |
| pPr/rPr ins / del | ins сохраняет границу; del соединяет со следующим совместимым physical p | b1; marker без successor, противоречивые markers, переход через table/section/story — blocked |
| rPrChange/pPrChange/tblPrChange… | Текущие свойства отдельно от исторических; old properties не становятся текстом | b2a; неизвестные/конфликтующие property histories не угадывать |
| moveFrom/moveTo runs и ranges | Source исключается, destination читается в своей позиции; paragraph mark имеет собственное правило | b2b: сначала структурный индекс pairs/ranges и контекст, uniqueness/nesting/overlap fixtures; malformed pair не превращать в обычный ins/del |
| Row/cell insertion/deletion, cellMerge, grid changes | Состояние контейнера и revisions его содержимого обрабатываются раздельно | b3: явная таблица переходов, текущая logical grid и source cells. Нельзя удалять текст всей строки только потому, что найден где-то w:del |
| SDT/customXml/AlternateContent | Только распознанный тип content control и одна выбранная совместимая ветвь; bindings не исполняются | b5; неизвестная branch/control блокирует, не склеивать Choice+Fallback и не дописывать невидимый placeholder |
| fldSimple/complex fields | Читать cached result только в доказанной final ветви; code/instrText не требования | b5; не обновлять field/TOC/PAGE/LINK/DDE, не открывать external target. Неполный/неоднозначный result — blocked до отдельного правила |
| Comments и comment markers | Исключённые из анализа, но сохранённые в bytes; не равны AIRA findings | Части comments и простые markers b1; новые threaded-comment metadata только после явного inventory rule |
| Unknown, hidden/visibility-affecting structures, glyph substitutions | Отсутствие текстового узла не доказывает отсутствие видимого требования | Blocked до reader/visibility resolver. Стили, настройки и источники numbering не становятся автоматически safe по MIME |

Ни одно blocked не означает удаление документа или снятие поддержки из продуктового scope. Первые readers являются промежуточными этапами; success анализа запрещён при любой оставшейся неоднозначности. B1 блокирует весь main flow при неподдержанной main structure, чтобы не выпускать неверно разрезанные абзацы. Позднее допускается локальная блокировка только при доказанных границах flow и сохранении complete=false для всего запуска.

## Stories, references и полнота

Coverage — две связанные проверки: каждая package part учтена; каждый потенциально значимый content/reference внутри прочитанной части включён, исключён по policy, классифицирован как metadata/nontext либо blocked. Один inventory classification не удовлетворяет второй проверке. Excluded branch имеет явный reason/anchor, unknown не становится empty. Все XML nodes/depth/bytes учитываются до семантического исключения.

После b4 порядок stories: main, затем используемые header/footer по canonical part name; normal footnotes/endnotes по порядку первого retained reference; вложенные textbox stories по parent story/path. Сам текст каждой story читается один раз, список occurrences/section/reference anchors сохраняется отдельно. Не дублировать один header по страницам, не имитировать pagination. Наследование и потенциальные first/even/default variants определяются final section properties/settings; до этого reader gate остаётся закрыт.

Normal note ID связывается с retained reference; duplicates/missing/wrong relationship types дают blocked. Separator/continuationSeparator учитываются как служебные, не определяются по одному магическому ID. Generated note marker — reference metadata, не выдуманный текстовый символ с ложным XML offset. Способ передачи контекста note в ML фиксируется в b4 contract; нельзя склеить соседние слова через пропущенный значимый marker без проверки, такому месту нужен boundary/reference event.

Orphan/неактивный header/note/glossary можно исключить только после полного распознавания всех потенциальных references и активных ветвей. Пока ссылки могут скрываться в unsupported markup, это blocked/unresolved, а не разрешение анализировать phantom requirements из всех parts или молча отбросить orphan. Glossary/building blocks/custom XML не являются обычным main text по одному MIME. Данные charts/embedded docs/altChunk и SVG text требуют собственных readers; внешние связи никогда не загружаются.

Images/OCR: OCR исключён; actual image может быть accounted nontext после проверки связи и отсутствия неучтённого текстового контейнера. Caption/textbox/alt text, drawings/VML и SVG нельзя объявлять уже обработанными по расширению .png/.svg. До соответствующего b5 reader image/drawing остаётся blocking; это этап реализации. Layout, обновление fields, Word-render parity и модельное качество не следуют из complete coverage.

## Реализация по циклам

| ID | Проверяемый выход |
|---|---|
| D03-17A2b1 | Реализован 1 ноября на Sol6.1 High, [результат](d03-17a2b1-result.md): final-main-v1 DTO/map, narrow main reader, inline ins/del и paragraph boundaries |
| D03-17A2b2a | b2a1 current-vs-old direct properties реализован, [результат](d03-17a2b2a1-result.md); [b2a2 visibility/styles спроектирован](d03-17a2b2a2-design.md), следующий bounded цикл — [b2a2a styles catalog](d03-17a2b2a2a-contract.md) |
| D03-17A2b2b | Moves: indexed matching/context и source mapping, сначала bounded run cases, затем paragraph marks/ranges; при необходимости два contracts |
| D03-17A2b3a/b | Physical table flows, затем revision grid/row/cell semantics; ни cross-cell join, ни дублирования текста merged cells |
| D03-17A2b4a/b | Sections/header/footer references, затем notes; story identity, dedup occurrences, completeness ledger |
| D03-17A2b5a/b… | Field result state machine, затем SDT/textbox/AlternateContent/media accounting отдельными задачами |
| D03-17A2b6 | Versioned assembler/coverage admission и batch mapping handoff к ML B1; malformed/limits/unknown regression corpus, native Word acceptance |

Все implementation cycles — Sol6.1 High при зафиксированном контракте, без повторного архитектурного переключения для каждого файла. На исходном design-pass полный контракт был только у b1; на 1 ноября реализованы b1/b2a1 и подготовлен [контракт b2a2a](d03-17a2b2a2a-contract.md). Следующие contracts готовятся перед кодом в рамках этого дизайна. Смысловая неоднозначность не даёт права выбрать случайную ветвь ради зелёных tests. Независимые B/C циклы возможны после фиксации новых source coordinates; реальные веса по прежнему разрешению Никиты можно ждать отдельно.

Проверки для каждого reader: exact expected text и независимое XML разрешение каждого piece; excluded gaps; mixed runs/Unicode; inserted/deleted boundaries/chains/empty p; scope barriers; повторяющиеся слова; malformed duplicate/overlapping revision structures; limits на excluded content; XML DTD/entity/EOCD traps; complete false для unsupported; source hashes/bytes неизменны. Для сложных Word revision semantics отдельный corpus с эталонной final редакцией, полученной в Word на целевых платформах; LibreOffice/строковый тест не заменяет эту проверку. Не менять исходник ради получения эталона — использовать отдельную синтетическую копию.

Этот дизайн закрывает архитектурный проход, а не full DOCX implementation. Первым шагом был b1 на Sol6.1 High. Актуальный следующий шаг после уточнения visibility от 1 ноября — b2a2a на Sol6.1 High, freeze новых acceptance до source. Старые tests/contracts/модели/БД не требуют изменения.
