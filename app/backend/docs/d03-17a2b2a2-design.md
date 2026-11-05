# D03-17A2b2a2 — видимость текста и границ Word

1 ноября 2026. Проектирование после `d35097e`, F06/F08/F11. Основание продукта — [current-product-scope.md](current-product-scope.md): итоговая редакция Word, комментарии и скрытый текст сохраняются, но не анализируются. Это уточнение технического чтения, не новая продуктовая спецификация. Поведение приложения в этом цикле не меняется.

## Решение и границы

Разделить три операции: получить текущие свойства стилей из сохранённого DOCX; определить видимость конкретных runs и paragraph marks в их контексте; собрать проверяемый текст с точными исходными диапазонами. Исключение скрытого run не удаляет его из DOCX и не разрешает редактировать защищённую revision structure. Успешное чтение styles не означает полноту анализа документа.

Технический режим чтения AIRA фиксирован: итоговая редакция, обычное постраничное представление, показ скрытого текста выключен. Сохранённый режим просмотра Word, пользовательский Show/Hide и настройки печати не переключают policy. Это конкретизация согласованного «Только видимый текст», а не управление Word. Белый цвет, перекрытие объектов, положение за страницей и шрифтовые подстановки не решаются булевым свойством hidden: соответствующие возможности остаются в матрице DOCX/визуальной приёмке. Проверяемое содержимое сохраняет исходный регистр/code points; здесь не создаётся пиксельный renderer.

Новая policy: `docx-analysis-policy/final-visible-no-comments-v2`. Старый `AnalysisPolicy` A2a, `final-main-v1` и `final-properties-v1` остаются неизменными. Новый opt-in builder `build_visible_snapshot` появится только в цикле **b2a2b**, с profile `docx-analysis/final-visible-main-v1` и отдельными DTO/mapper. Из старого complete=true нельзя вывести соблюдение новой policy. Будущий service admission выбирает конкретный разрешённый профиль, не fallback на старый reader при ошибке.

## Первичные основания

Прочитаны 1 ноября 2026. Официальный [ECMA-376, Part 1, 5th edition 2016](https://ecma-international.org/wp-content/uploads/ECMA-376-1_5th_edition_december_2016.zip), §17.7.1–3, печатные страницы 613–617: цепочка basedOn и уровни применения стилей — разные операции. Внутри цепочки используется ближайшее заданное значение; между уровнями toggle-свойства комбинируются; direct formatting задаёт окончательное значение. В §17.7.2 также есть уровни таблиц и нумерации, которые нельзя молча отбросить при их наличии.

[Microsoft MS-OI29500 §17.7.3](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oi29500/f7130225-2368-48f3-acae-a9d278d0fb25) уточняет обработку document defaults и toggle-свойств в Word. Поэтому простой XOR каждого предка basedOn или правило «последний тег во всём документе» непригодны. Алгоритм ниже — наша явная интерпретация этих правил для ограниченного контекста; сравнение с Word остаётся отдельной приёмкой.

[Vanish](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.vanish?view=openxml-3.0.1) относится к скрытию содержимого run и является toggle-свойством. [WebHidden](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.webhidden?view=openxml-3.0.1) относится к web view и не скрывает текст в выбранном постраничном режиме. [SpecVanish](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.specvanish?view=openxml-3.0.1) подавляет отображаемую границу абзаца, сохраняя возможность смены paragraph style; на обычном run это свойство можно игнорировать. Эти три свойства не объединять в один OR.

[BasedOn](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.basedon?view=openxml-3.0.1) допускает игнорирование отсутствующего/неподходящего родителя. Наш начальный reader намеренно строже: такой стиль имеет unresolved result, пока этот fallback не принят отдельной проверкой. [RunStyle](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.runstyle?view=openxml-3.0.1) описывает ссылку на character style; `link`/`next` не заменяют basedOn. [ParagraphMarkRunProperties](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.paragraphmarkrunproperties?view=openxml-3.0.1) задаёт оформление самого знака абзаца: direct `pPr/rPr/vanish` не означает скрыть все текстовые runs абзаца.

## Контекст и порядок расчёта

1. Проверить исходный ZIP, SHA и package limits. Найти styles/settings по relationships от настоящего main part и MIME, а не по фиксированному имени файла. Не загружать внешние связи/шаблоны; не искать определения стилей на компьютере. Необнаруженная часть и противоречивая часть — разные состояния.
2. Построить ограниченный каталог styles: docDefaults, идентификаторы, типы, default flags, basedOn, текущие свойства и их provenance. Старые rPrChange/pPrChange учитываются отдельно и не исполняются. Style `hidden`/`semiHidden` и latentStyles описывают доступность стилей в UI, не скрытый текст требований.
3. Распознать final content и structural boundaries. Сначала исключить удалённые ветви/comments/history по их правилам, сохранив входные budgets. Затем определить контекст retained runs и границ. Hidden run проверяется на допустимую структуру **до** исключения: он может содержать field/reference/unknown content, которое этот reader не умеет учитывать.
4. Выбрать paragraph style: явный корректный pStyle либо единственный default paragraph style. Не подставлять `Normal` по имени. Character style — конкретный rStyle; ссылки из histories не применяются. Неизвестные, повторные, циклические и несовместимые ссылки блокируют зависимый flow. Противоречия не устраняются прямым vanish=false.
5. Получить effective run properties; отдельно — свойства paragraph mark. Character-style ссылка у mark и direct mark properties не переносятся на текстовые runs. Не размножать paragraph style rPr как direct formatting: это изменит toggle-семантику.
6. Собрать видимые atoms и границы, затем exact pieces, coverage и manifest. Не добавлять пробел взамен скрытого run. Пример `ab` + hidden `secret` + `cd` даёт `abcd` с двумя source slices; quote не должен захватывать `secret`.

Для **обычного run вне таблиц/списков/удалённых границ** вычисление vanish определено так. `D` — docDefaults.vanish, при отсутствии false согласно фиксированному режиму AIRA. `P`/`C` — ближайшие заданные значения соответствующей цепочки либо D. Неактивный table level также равен D. При заданном direct vanish результат равен ему; иначе `D XOR P XOR C`. При D=false это привычное `P XOR C`. При D=true это интерпретация Microsoft-уточнения для трёх уровней; отсутствие стиля не означает автоматически false. Две true внутри одной basedOn-цепочки дают true, а не false. Значение false в дочернем стиле прекращает поиск предка. DocDefaults не вставляется как дополнительный предок каждой цепочки.

| D | P | C | vanish без direct |
|---:|---:|---:|---:|
| 0 | 0 | 0 | 0 |
| 0 | 0 | 1 | 1 |
| 0 | 1 | 0 | 1 |
| 0 | 1 | 1 | 0 |
| 1 | 0 | 0 | 1 |
| 1 | 0 | 1 | 0 |
| 1 | 1 | 0 | 0 |
| 1 | 1 | 1 | 1 |

`specVanish` и `webHidden` — обычные наследуемые on/off, не получают этот XOR. Для mark вычислять specVanish отдельно; для text run зарегистрировать specVanish как не влияющее на текст. WebHidden сохранить в evidence, но не исключать по нему содержимое. Отсутствие docDefaults не повод обращаться к локальному шаблону: выбранный baseline AIRA детерминирован и отражается в profile.

Неоднозначность implicit default character style нельзя закрыть предположением. Standalone b1 допускает default record без true, но это algebra convention, не Word proof. Уточнение b2 от 1 ноября: первый интегрированный reader требует отсутствующий default character либо resolved record со всеми тремя visibility values=None; даже explicit false получает `implicit_character_style` до отдельного evidence. Ни один record с false не объявляется нейтральным относительно любых docDefaults. Default records всё равно имеют provenance. Нумерация из paragraph style и conditional table formatting требуют своих context readers; direct formatting не обход их учёта.

## Границы абзацев и новые координаты

Две независимые вещи: граница отображаемого текста и граница применения стиля. Старый `ParagraphJoin.marker` всегда означает конкретный удалённый знак и не подходит для унаследованной видимости. Новый DTO не расширяет значение старого поля задним числом.

План для b2a2c: `VisibleBoundary(left, right, kind, effect, evidence)` с kind `retained|deleted_revision|hidden_vanish|hidden_spec_vanish`, effect `break|join`, evidence — tuple конкретных source anchors. Унаследованный hidden имеет witness в styles и ссылку/контекст в main; нельзя выдумывать direct XML marker. Отдельные context IDs связывают каждый piece с его исходным/разрешённым paragraph-style context. Объединение текста не стирает эти сведения. При совпадении причин есть один boundary event, kind по приоритету revision > specVanish > vanish, evidence содержит все причины.

| Случай | Правило допуска |
|---|---|
| Retained mark, visibility доказана false | Отдельные logical fragments, как прежде |
| Direct hidden run внутри обычного p | Пропустить atoms, сохранить gap evidence; граница p отдельно |
| specVanish у mark, следующий совместимый p | Один отображаемый fragment; сохранить две границы стилей/context IDs |
| vanish у mark | Отдельный hidden-boundary case; подтвердить на Word при выключенном показе скрытого текста |
| Deleted mark | Final join из b1 остаётся; выбор effective paragraph context требует проверки на разных стилях по обе стороны |
| Hidden последний mark / переход через section, table, story / mixed revision+hidden | До проверенного boundary contract весь flow blocked; не угадывать successor |

Особенно опасен deleted mark с разными paragraph styles: прежний b1 извлекал текст и не разрешал стили. Нельзя механически вычислить видимость каждого run по его физическому p, а затем склеить — итоговое оформление может отличаться. Первый b2a2b **блокирует все deleted/hidden mark joins**; b1 продолжает работать в своём профиле. В b2a2c вводится проверенный resolver контекста границ. Если Word fixture недоступен, реализуются независимые cases, сомнительная комбинация остаётся blocker; не объявлять всё DOCX готовым.

Полностью скрытые абзацы получают coverage исключения, но их physical marks продолжают участвовать в графе границ. Пустой вывод при полном учёте возможен; service позднее должен сообщить об отсутствии проверяемого текста, а не отправить модели пустой запрос. Whitespace-only и empty различаются с hidden по coverage.

## Снимок, coverage и ограничения ресурсов

`VisibleSnapshot` независим от FinalSnapshot: identity document/revision/source SHA/profile/policy, styles/context evidence, ordered fragments/pieces/coverage, exact text и manifest digests. В exact b2 contract первый профиль имеет один physical p на fragment, без joins/boundary records; будущие сложные boundaries потребуют другого profile/контракта. Старый map_final_span не принимает новый DTO; новый source-backed map_visible_span проверяет снимок повторной сборкой из оригинала. Изменение только styles меняет source SHA, snapshot и fragment identity даже при одинаковом тексте. При смене policy старые результаты/hide decisions не переносятся автоматически.

Piece возвращает только retained source atom ranges. Ни gap, ни boundary witness из styles не становится текстовым slice. Quote через hidden gap возвращает несколько slices. Полная проверка shape/hash не доказывает связь с реальным XML: trusted builder всегда строит снимок из pinned saved bytes, клиент не поставляет свой style context. В одном batch валидация/индексация выполняется один раз, не заново для каждого замечания.

Новые dispositions: `excluded/hidden_run`, metadata resolved visibility/context, excluded property history, blocked unresolved style/settings/boundary. Удалённая ветвь с hidden внутри учитывается один раз как deleted, без обхода properties. Parsed style catalog даёт только локальное свидетельство; нельзя снимать `unread_part` с settings/numbering/theme/fonts/media или даже со styles целиком по наличию MIME. Для styles нужно доказать, какие определения применены/не применены в полностью распознанном flow; opaque table styles не дают видимость обычных runs и не должны автоматически применяться к ним.

Новый reader сохраняет package limits и вводит общий XML budget для main + прочитанных auxiliary частей, отдельные пределы style count/chain depth, context records и boundary evidence. Длины hidden/history/opaque subtrees считаются до исключения; hash вычисляется по исходным bytes. Граф basedOn обходится с memoization и cycle detection без рекурсивного обхода всех предков для каждого run. Provenance — ссылки на единичные definitions, не копии всех цепочек в каждом piece. При превышении — статическая ошибка, без обрезки и частичного success. Не хранить XML/ZIP/ET/имена авторов/текст в diagnostics и repr.

## Реализация по отдельным циклам

| ID | Выход и проверка | Режим |
|---|---|---|
| D03-17A2b2a2a | Pure styles catalog, current values, basedOn resolution/provenance/budgets. [Реализован](d03-17a2b2a2a-result.md), полный gate2559+24, main V8 unchanged | Sol 6.1 High |
| D03-17A2b2a2b | [b1 ordinary-run visibility rules реализованы](d03-17a2b2a2b1-result.md); [b2 reader/mapper реализован](d03-17a2b2a2b2-result.md): versioned visible-main snapshot, XML-derived provenance, source-backed batch mapper, settings/auxiliary blockers. Gate2656+24 | Sol 6.1 High |
| D03-17A2b2a2c | Boundary/context resolver, Word comparison для hidden/specVanish/deleted combinations, затем opt-in extension profile; при недостатке evidence сохранять узкие blockers | Sol 6.1 High; Astra только если факты Word потребуют пересмотра архитектуры |

После этих задач возвращаемся к b2b moves, b3 tables, b4 stories, b5 containers/fields, b6 admission из [общего дизайна](d03-17a2b-design.md). Другие функции/ML/desktop не смешиваются с текущим циклом. Наличие неизвестного Word edge case не требует останавливать независимую работу.

Приёмка: XML-derived provenance; exact current-vs-history values; basedOn false/true/absent/cycles/missing/wrong type; default selection; all toggle-table rows + direct overrides; specVanish/webHidden отличны от vanish; hidden gap multi-range; полностью скрытые/пустые p; разные styles по сторонам deleted и hidden boundaries; no external I/O/unsafe repr; deterministic SHA/profile/policy; malformed XML/limits/EOCD; frozen legacy tests. Все данные синтетические.

Native corpus: Windows и macOS Word, точные версии/настройки/шрифты фиксируются при запуске. Открыть синтетический исходник в final view, hidden display off, отдельно проверить Show/Hide, получить ожидаемый видимый текст/границы, сравнить с reader и сохранением bytes. Источник не пересохраняется ради анализа; при необходимости создать отдельную копию для принятия revisions. Нужны прямой/inherited hidden, docDefaults=true, character/paragraph combinations, paragraph marks, revisions и история свойств. До такой проверки нельзя заявлять совместимость сложных границ с Word. В этом design-cycle Word и модель не запускались.

Исходный следующий шаг был a на Sol 6.1 High; a, b1 и затем b2 реализованы 1 ноября, результаты связаны в таблице. Архитектурный проход b2: [контракт](d03-17a2b2a2b2-contract.md), [результат дизайна](d03-17a2b2a2b2-design-result.md); [реализация](d03-17a2b2a2b2-result.md) прошла freeze/red/targeted/full/baseline. Source selectors не приходят от caller, mapping сверяется по original bytes один раз на batch. Актуальный следующий цикл — **b2a2c, evidence/контекст paragraph boundaries**, на Sol 6.1 High по собственному bounded contract; если native Word факты требуют пересмотра архитектуры — сначала завершить evidence-cycle и рекомендовать Astra. Без native evidence сомнительные joins остаются blocked, независимые B1/readers продолжаются. Runner/tasks/progress не менять.
