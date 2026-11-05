# Последовательные циклы разработки AIRA

**5 ноября — самостоятельная интеграционная последовательность завершена.**
По прямой команде Никиты устранены тайм-ауты обработки Word и выполнены D03-18A3–A7.

- [D03-18A2-S](d03-18a2-stability-result.md): повторная проверка одного Word-источника
  внутри запроса устранена; старые тайм-ауты и проверки сохранены.
- [D03-18A3](d03-18a3-result.md): сохранение → проверка → ожидание/остановка/повтор.
- [D03-18A4](d03-18a4-result.md): результаты, фильтры, скрытие и устаревание после правки.
- [D03-18A5](d03-18a5-result.md): вкладки, восстановление и закрытие без потери ввода;
  восстановление Word строит источник один раз, сохраняя валидацию.
- [D03-18A6](d03-18a6-result.md): создание/импорт и экспорт подтверждённой версии DOCX.
- [D03-18A7](d03-18a7-result.md): целый воспроизводимый сценарий и общая очередь
  одновременного автосохранения вкладок. Остановка анализа идёт отдельным каналом.

Финальный gate: **7009 passed,45 skipped,24 subtests,exit0**; main schema/counts
unchanged. Отдельный сквозной запуск прошёл за37.77s на трёх синтетических DOCX,
с перезапуском host, восстановлением, повторной проверкой, экспортом и повторным импортом.
Команда: `bash scripts/check_docx_workflow.sh`. [Инструкция и передача](docx-workflow-handoff.md).
Автосохранение использует ускоренные тестовые часы и настоящие HTTP/DB операции.
Модель и внешний лицензирующий transport — явные fixtures.

**Самостоятельных циклов этой backend/client-интеграции осталось:0.** Это не готовый
пользовательский релиз. Внешние gates: настоящий пакет модели и качество анализа;
финальный интерфейс Ани/native shell и file picker; нативная приёмка Windows и визуальная
Word; публичный TLS-сервис лицензий и подписанные установщики с реальными assets.
Полная совместимость Word/layout не доказана. Эти gates не скрыты числом тестов.

Ниже сохранена история прежних этапов и оценок; их остатки не заменяют текущий итог.

За последние сутки реализованы код серверного и клиентского лицензирования с настраиваемым
сроком/одним устройством/онлайн-проверкой при запуске; собственное локальное хранилище,
PostgreSQL и безопасный жизненный цикл macOS; существенно расширенное чтение DOCX
(таблицы, стили/нумерация, сноски/колонтитулы, поля, content controls, изображения/MC),
правка простого текста ячеек; хранение/учебный анализ/фильтры/перенос скрытий; сборщик
подготовленного пакета; последовательный клиент редактора с автосохранением. Это в основном
backend и интеграционные модули, **не готовый пользовательский MVP**. Настоящей модели
нет; fixture явно помечен. Приоритет следующей работы — целый пользовательский путь,
а не новые узкие расширения DOCX без конкретной необходимости.

**5 ноября, D03-18A1 завершён:** [client/autosave core](d03-18a1-result.md).
Full **6897 passed +24 subtests**,45 skipped;1066 hashes, mainV8 unchanged. Команды
последовательны, неизвестный исход сохраняет точный запрос, двухминутный checkpoint не
откладывается набором текста.48 новых проверок и реальная wheel-упаковка пройдены.
Далее **D03-18A2** — ограниченный HTTP transport к своему actor и сквозное восстановление
черновика через owned licensed desktop. Затем save-before-check, вкладки/экспорт и handoff.
Финальный UI/realML/native Windows/Word/release не объявляются готовыми. Продолжаем автономно.

**5 ноября, D03-17A2b9C1 и B9B завершены:** [table editor](d03-17a2b9c1-result.md),
[Word integration](d03-17a2b9b-result.md). Full **6849 passed +24 subtests**,45 skipped;
1060 hashes, mainV8 unchanged. Table-only DOCX открываются в явном word_fixture режиме;
правка ячейки, checkpoint/recovery/save, анализ и экспорт проверены. Прежний default не
изменён. Далее **D03-18A1** — координация команд DOCX и двухминутного автосохранения,
затем реальный HTTP transport. Старый workspace-клиент новых editor/analysis маршрутов
не использует. RealML/GUI/native Word/Windows/release остаются внешними gates. Astra.

**5 ноября, D03-17A2b9B — промежуточная точка, НЕ завершён:**
[result](d03-17a2b9b-result.md). Pure25/native9 проходят; три HTTP тайм-аута устранены
локальным продолжением уже выполненной проверки исходника. Остаётся table-only opening:
прежний body-only editor по контракту отказывает. Следующий отдельный prerequisite
**D03-17A2b9C1** добавит явный table-aware режим, сохранив прежний default и все тесты B9B.
Полный gate после устранения зависимости; B9B до этого не считать готовым.

**5 ноября, D03-17A2b9A завершён:** [ordinary Word package reader](d03-17a2b9a-result.md),
full **6774 passed +24 subtests**,45 skipped;1041 hashes, mainV8 unchanged. Шесть независимых
синтетических DOCX теперь читаются целиком с точными адресами исходного XML; служебные части,
MC-нумерация и contextualSpacing проверены отдельно. Далее **D03-17A2b9B** — сквозная
интеграция нового фиксированного profile. Затем приоритет F05: двухминутное автосохранение
DOCX с последовательной координацией команд, без конфликтов со счётчиками редактора.
RealML/GUI/native Word/Windows/release и оставшаяся матрица DOCX открыты. Astra, автономно.

**5 ноября, D03-17A2b8B завершён:** [style-list integration](d03-17a2b8b-result.md),
full **6697 passed +24 subtests**,45 skipped;1021 hashes,994 прежних файлов unchanged
вне согласованных hooks. MainV8 unchanged. Review4/storage/native fixture/hides/owned desktop
проверены. Независимая проверка шести обычных python-docx шаблонов выявила блокирование
стандартных служебных частей: далее **D03-17A2b9A** — точная совместимость пакета и MC
нумерации, затем вертикальная интеграция. Это reader gap, не native Word/импорт-приёмка.
RealML/UI/native Word/Windows/release открыты; старый остаток циклов требует переоценки.
Astra, продолжаем автономно.

**5 ноября, D03-17A2b8A завершён:** [style-linked numbering](d03-17a2b8a-result.md),
full **6630 passed +24 subtests**,45 skipped;1008 hashes,996 прежних файлов unchanged.
MainV8 unchanged. Прямые и унаследованные через стиль номера имеют физический источник;
одинаковые счётчики, ручное снятие нумерации, поля/таблицы/скрытый текст проверены.
Далее **D03-17A2b8B** — review4/storage/fixture/native/hides/owned desktop. После интеграции
пересмотреть самостоятельный остаток по пользовательскому сценарию, включая editor/export/
launch preparation. RealML/UI/native Word/Windows/release остаются внешними gates. Astra.

**5 ноября, D03-17A2b7B завершён:** [outline integration](d03-17a2b7b-result.md),
full **6571 passed +24 subtests**,45 skipped;996 hashes,972 прежних файлов unchanged
вне12 source hooks и одной точной metadata-проверки. MainV8 unchanged. Review3/view3,
saved native checks, pinned retries, hides и explicit outline_fixture desktop проверены
сквозным сценарием на macOS. Далее **D03-17A2b8A** — source-proven paragraph-style
numbering с физическими адресами свойств стиля; затем отдельная вертикальная интеграция.
RealML/UI/native Windows/Word/release и оставшаяся DOCX matrix открыты. Astra, продолжаем.

**5 ноября, D03-17A2b7A завершён:** [direct outline reader](d03-17a2b7a-result.md),
full **6533 passed +24 subtests**,45 skipped;985 hashes,976 прежних файлов unchanged.
MainV8 unchanged. Прямые уровни0–8, перезапуск счётчиков и decimal/bullet/Roman labels
читаются отдельно от literal evidence; исходный DOCX не переписывается. Далее
**D03-17A2b7B** — один сквозной цикл review3/storage/fixture/native/presentation/hides/
desktop integration. Старые profiles/defaults сохраняются. Полная DOCX matrix, realML,
UI/native Word/Windows/release gates ещё открыты. Astra, продолжаем автономно.

**5 ноября, D05-07A завершён:** [offline payload builder](d05-07a-result.md),
full **6469 passed +24 subtests**,45 skipped;976 hashes,969 прежних файлов unchanged.
MainV8 unchanged. Явно подготовленные файлы копируются в новый каталог, затем проверяется
полный inventory; CLI возвращает pin/summary, ошибки не перезаписывают и не удаляют данные.
Это ещё не установщик/подписанный релиз. Далее **D03-17A2b7A** — прямые многоуровневые
списки DOCX: сначала source reader/mapping, затем отдельная сквозная интеграция хранения/
runtime/desktop. Семантика счётчиков и отличия Word проверяются до freeze; native Word
паритет не заявляется. DOCX matrix/UI/ML/native/release gates открыты. Astra, продолжаем.

**5 ноября, D03-17A2b6c5 завершён:** [structured desktop integration](d03-17a2b6c5-result.md),
full **6410 passed +24 subtests**,45 skipped;969 hashes,963 прежних unchanged вне4 hooks.
MainV8 unchanged. Явный structured_fixture mode проверен через настоящий loopback/ownedPG:
create/import→edit→check→hide→full restart→online grant→retry/show→exact export. Legacy default
сохранён; реальной модели/GUI нет. Далее **D05-07A** — сборщик проверяемого payload из явно
подготовленных файлов, без запуска компонентов и публикации. DOCX matrix и UI/native/release
gates ещё открыты; прежний ориентир18–28 крупных блоков требует сверки. Astra, продолжаем.

**5 ноября, D03-17A2b6c4 завершён:** [structured correspondence](d03-17a2b6c4-result.md),
full **6399 passed +24 subtests**,45 skipped;967 hashes,959 прежних unchanged вне2 hooks.
MainV8 unchanged. Скрытие переносится только при доказанном соответствии текста,
структуры, нумерации и всех ссылок на сноску; изменённый/неоднозначный контекст вновь
показывает замечание. Далее **D03-17A2b6c5** — явный structured fixture desktop mode,
HTTP create/import→check→hide→restart→retry/export. Реальная модель, UI/native Windows/
Word/release gates отдельно; ориентир18–28 крупных блоков требует сверки. Astra, продолжаем.

**5 ноября, D03-17A2b6c3 завершён:** [structured presentation](d03-17a2b6c3-result.md),
full **6342 passed +24 subtests**,45 skipped;961 hashes,957 прежних unchanged вне1 hook.
MainV8 unchanged. View2 сохраняет полный context списков/сносок при фильтрации; старый
view1 побайтово совместим. Далее **D03-17A2b6c4** — доказуемое соответствие структурных
фрагментов для скрытия замечаний, затем HTTP/desktop integration. Реальная модель,
UI/native Windows/Word/release gates отдельно; ориентир18–28 крупных блоков предварительный.
Astra, продолжаем автономно.

**5 ноября, D03-17A2b6c2 завершён:** [native structured fixture runtime](d03-17a2b6c2-result.md),
full **6321 passed +24 subtests**,45 skipped;958 hashes,946 прежних unchanged вне7 hooks.
MainV8 unchanged. Native macOS fixture2 проверяет сохранённый структурный документ,
останавливается, перезапускается и повторяет исходные old/new profiles после последующих
правок. Далее **D03-17A2b6c3** — versioned structured presentation; затем correspondence
и desktop integration. Реальная модель не запускалась. UI/native Windows/Word/release
отдельно; ориентир18–28 крупных блоков предварительный. Astra, продолжаем автономно.

**5 ноября, D03-17A2b6c1 завершён:** [structured semantic fixture2](d03-17a2b6c1-result.md),
full **6294 passed +24 subtests**,45 skipped;953 hashes,946 прежних unchanged вне1
private hook. MainV8 unchanged. Учебный исполнитель проверяет контекст списков/сносок,
цитирует literal text, явно обозначает отсутствие реальной модели; pinned legacy requests
поддержаны отдельной точной парой. Далее **D03-17A2b6c2**: native review2, явный source
policy и retry исходного snapshot. Затем presentation/remapping и desktop integration.
UI/real ML/native Word/Windows/release gates отдельно; ориентир18–28 крупных блоков
предварительный. Astra, продолжаем автономно.

**5 ноября, D03-17A2b6b завершён:** [structured source storage](d03-17a2b6b-result.md),
full **6228 passed +24 subtests**,45 skipped;947 hashes,943 прежних unchanged вне1
codec hook. MainV8 unchanged. Новый source profile сохраняет и восстанавливает списки,
сноски и точные literal spans; старые записи/SQL layout сохранены. Далее **D03-17A2b6c1**:
явный semantic fixture2 с новым контекстом и поддержкой pinned legacy requests; затем
native/runtime admission и presentation/remapping перед desktop default. Реальной модели
нет; UI/native/release gates отдельно. Ориентир18–28 крупных блоков предварительный. Astra.

**5 ноября, D03-17A2b6a завершён:** [structured review v2](d03-17a2b6a-result.md),
full **6188 passed +24 subtests**,45 skipped;944 hashes,936 прежних unchanged вне1
private hook. MainV8 unchanged. Запрос/результат сохраняют проверяемый контекст
списков/сносок отдельно от literal spans; старый wire1 неизменен. Далее **D03-17A2b6b**:
source codec capture/restore/attempt/result для двух фиксированных profiles. Затем
fixture2, presentation/remapping и runtime/desktop integration до app default. Модель,
UI/native/release gates отдельно; ориентир18–28 крупных блоков предварительный. Astra.

**5 ноября, D03-17A2b5e2 завершён:** [direct list evidence](d03-17a2b5e2-result.md),
full **6153 passed +24 subtests**,45 skipped;937 hashes,924 прежних unchanged вне1
private hook. MainV8 unchanged. Собственные bullet/decimal списки сохраняют логические
подписи и исходные адреса отдельно от буквального текста. Далее **D03-17A2b6a**:
структурированный review wire v2 с явным контекстом списков/сносок; затем codec,
fixture/runtime и application admission. Реальная модель отсутствует; UI/native/release
gates отдельно. Ориентир18–28 крупных блоков предварительный. Astra, продолжаем.

**5 ноября, D03-17A2b5e1 завершён:** [unlisted template reader](d03-17a2b5e1-result.md),
full **6095 passed +24 subtests**,45 skipped;925 hashes,911 прежних unchanged вне4
private hooks. MainV8 unchanged. Собственные body/heading1/2/3 и пустые DOCX AIRA
проходят новый opt-in reader; widowControl и unused numbering не теряют источник.
Далее **D03-17A2b5e2** — прямые одноуровневые bullet/decimal списки, отдельные generated
labels и literal mapping. После базовых списков приоритет B6: source codec/worker/app
admission, чтобы проверить create→check→reopen. Inherited/multilevel и остальные DOCX
capabilities остаются работой. Ориентир18–28 крупных блоков предварительный; внешние
UI/ML/native/release gates отдельно. Astra, продолжаем автономно.

**5 ноября, D03-17A2b5d2 завершён:** [floating raster anchors](d03-17a2b5d2-result.md),
full **6036 passed +24 subtests**, 45 skipped; 915 hashes,906 прежних unchanged
вне двух private hooks. MainV8 unchanged. Плавающий объект не создаёт inline glyph
или выдуманный разрыв текста; foreground wrapNone остаётся gate. Далее **D03-17A2b5e1**:
обычный текст/заголовки шаблона AIRA, widowControl и доказуемо неиспользуемые definitions
списков. Активные списки и их generated labels — отдельный следующий цикл. Ориентир
18–28 крупных самостоятельных блоков требует уточнения; это не счётчик мелких readers.
App/codec/worker admission, editor/export/packaging и внешние UI/ML/native/release gates
ещё открыты. Astra, продолжаем автономно.

**5 ноября, D03-17A2b5d1 завершён:** [inline PNG/JPEG accounting](d03-17a2b5d1-result.md),
full **5982 passed +24 subtests**, 45 skipped; 908 hashes, 894 прежних unchanged
вне трёх private hooks. Main V8 unchanged. Closed picture/raster proofs и image boundaries
сохраняют source slices и не склеивают слова через видимую картинку. Далее
**D03-17A2b5d2** — floating raster anchors без выдуманного inline glyph/разрыва;
затем **defaults и numbering шаблона AIRA**, где synthetic probe выявил unsupported_defaults.
Ориентир 18–28 остаётся предварительной оценкой крупных оставшихся блоков, не обратным
счётчиком каждого малого reader. App/codec/worker admission ещё не подключён к этим
profiles; editor/export/packaging и внешние UI/ML/native/release gates отдельны.
Astra, продолжаем автономно.

**5 ноября, D03-17A2b5b3 завершён:** [saved plain-text controls](d03-17a2b5b3-result.md),
full **5919 passed +24 subtests**, 45 skipped; 897 hashes, 886 прежних unchanged
вне трёх разрешённых private hooks. Main V8 unchanged. Inline/block/cell controls
с доказуемым uniform current formatting сохраняют существующие soft breaks и
исходные адреса. Далее **D03-17A2b5d1** — inline PNG/JPEG, source-bound nontext
accounting и границы текстовых фрагментов. Ориентир **18–28 самостоятельных циклов**
остаётся предварительным: нужен отдельный проход application admission/codec/worker,
редактор/export и packaging. UI/ML/native/release внешние gates отдельно. Astra,
продолжаем автономно.

**5 ноября, D03-17A2b5c2c завершён:** [visible selected stories/mapping](d03-17a2b5c2c-result.md),
full **5868 passed +24 subtests**, 45 skipped; 889 hashes, 870 прежних unchanged
вне11 разрешённых private hooks. Main V8 unchanged. Whole-story reader и mapping
используют один coherent selected view, сохраняя original addresses, table/revision/
move proofs, note targets и атомарные отказы. Далее **D03-17A2b5b3** — сохранённые
plain-text controls, uniform formatting и existing soft breaks. Ориентир **18–28
самостоятельных циклов** требует сверки крупных блоков; внешние UI/ML/native/release
отдельно. Astra, продолжаем автономно.

**5 ноября, D03-17A2b5c2b завершён:** [coherent selected metadata](d03-17a2b5c2b-result.md),
full **5827 passed +24 subtests**, 45 skipped; 881 hashes, 864 прежних unchanged
вне восьми разрешённых private hooks. Main V8 unchanged. Styles/table styles,
sections/settings и notes читаются из одного view с исходными anchors и новыми
явными profiles; raw bounds покрывают unused/ambiguous candidates до DOM.
Далее **D03-17A2b5c2c** — whole-story snapshot/mapping на тех же selected contexts.
Ориентир **18–28 самостоятельных циклов** требует сверки крупных блоков;
внешние UI/ML/native/release отдельно. Astra, продолжаем автономно.

**5 ноября, D03-17A2b5c2a завершён:** [immutable original-address view](d03-17a2b5c2a-result.md),
full **5786 passed +24 subtests**, 45 skipped; 872 hashes, все 865 прежних unchanged.
Main V8 unchanged. Выбранные логические дети сохраняют исходные XML addresses/text/attrs;
root/mixed-text boundaries дают явный атомарный отказ. Далее **D03-17A2b5c2b** — styles,
table-style proof, sections/settings и note definitions из одного view; затем whole-story
reading/mapping. Ориентир **18–28 самостоятельных циклов** требует сверки крупных блоков,
внешние UI/ML/native/release отдельно. Astra, продолжаем автономно.

**5 ноября, D03-17A2b5c1 завершён:** [MCE selection catalog](d03-17a2b5c1-result.md),
full **5751 passed +24 subtests**, 45 skipped; 865 hashes, все 855 прежних unchanged.
Main V8 unchanged. Streaming source-bound выбор Choice/Fallback, URI-scoped Ignorable/
ProcessContent/MustUnderstand и полные raw bounds. Каталог не является чтением текста.
Далее **D03-17A2b5c2a** — immutable original-address logical view; затем coherent
styles/sections/notes и весь story reader. Ориентир **18–28 самостоятельных циклов**
требует сверки крупных блоков, внешние UI/ML/native/release отдельно. Astra, продолжаем.

**5 ноября, D03-17A2b5b2 завершён:** [original table controls](d03-17a2b5b2-result.md),
full **5688 passed +24 subtests**, 45 skipped; 855 hashes, 843 прежних unchanged,
четыре разрешённых private hooks. Main V8 unchanged. Rich controls вокруг таблиц,
строк, ячеек и nested cell blocks сохраняют исходные адреса и настоящие field flows.
Далее **D03-17A2b5c1** — original-source Markup Compatibility decisions; затем
отдельная интеграция единого view во все читатели. Ориентир **18–28 самостоятельных
циклов** требует сверки крупных блоков, внешние UI/ML/native/release отдельно.
Astra, продолжаем автономно. Число мелких циклов не равно готовности полного DOCX.

**5 ноября, D03-17A2b5b1 завершён:** [saved rich-text controls](d03-17a2b5b1-result.md),
full **5634 passed +24 subtests**, 45 skipped; 847 hashes, все 839 прежних unchanged.
Main V8 unchanged. Nested block/inline controls читаются с прежней visibility/source
mapping; поля не пересекают control boundaries. Bound/placeholder/plain types и
table/row/cell wrappers остаются gates. Далее **D03-17A2b5b2** — original table controls
и настоящие cell flows. Ориентир **18–28 самостоятельных циклов** требует сверки крупных
блоков; внешние UI/ML/native/release отдельно. Astra, продолжаем автономно.

**4 ноября, D03-17A2b5a1 завершён:** [сохранённые результаты полей Word](d03-17a2b5a1-result.md),
full **5573 passed +24 subtests**, 45 skipped; 839 hashes, 828 прежних unchanged,
три разрешённых private reuse hooks. Main V8 unchanged. Simple/complex/nested fields
читаются без исполнения инструкций; dirty и неоднозначные переходы остаются gates.
Далее **D03-17A2b5b1** — сохранённый текст rich-text content controls, с исходными
адресами и прежними правилами видимости. Ориентир **18–28 самостоятельных циклов**
требует сверки крупных блоков; UI/ML/native/release отдельно. Astra, продолжаем.

**4 ноября, D03-17A2b4b2 завершён:** [текст сносок, ссылки и mapping](d03-17a2b4b2-result.md),
full **5528 passed +24 subtests**, 45 skipped; 831 hashes, 813 прежних unchanged,
три разрешённых shared hooks. Main V8 unchanged. Generated markers не подменяются
цифрами; видимые ссылки сохраняют связь с исходным примечанием, repeated use не
дублирует текст. Custom marks и сложные/native случаи остаются gates. Далее
**D03-17A2b5a1** — stored simple/complex field results. Ориентир **18–28 самостоятельных
циклов** до сверки крупных блоков; UI/ML/native/release отдельно. Astra, продолжаем.

**4 ноября, D03-17A2b4b1 завершён:** [каталог определений сносок](d03-17a2b4b1-result.md),
full **5467 passed +24 subtests**, 45 skipped; 816 hashes, все 808 прежних unchanged;
main V8 unchanged. Проверены реальные parts/relationships, типы и уникальность ID,
исходные адреса и общие лимиты. Каталог не утверждает видимость или полноту анализа.
Далее **D03-17A2b4b2** — видимые ссылки, текст сносок и source-backed mapping.
Ориентир **18–28 самостоятельных циклов** до сверки крупных блоков; UI/ML/native/
release отдельно. Astra, продолжаем автономно.

**4 ноября, D03-17A2b4a2 завершён:** [main/header/footer reading и mapping](d03-17a2b4a2-result.md),
full **5429 passed +24 subtests**, 45 skipped; 808 hashes, 793 прежних unchanged,
три разрешённых shared hooks. Main V8 unchanged. Исходные адреса, общие лимиты,
таблицы и видимость колонтитулов проверены; ошибка активной части не выдаёт частичный
текст за полный. Далее **D03-17A2b4b1** — определения сносок/концевых примечаний,
затем их retained references, текст и mapping. Ориентир **18–28 самостоятельных
циклов** требует сверки крупных блоков; внешние UI/ML/native/release отдельно.
Astra, продолжаем автономно без переключения.

**4 ноября, D03-17A2b4a1 завершён:** [current sections/reference inheritance](d03-17a2b4a1-result.md),
full **5387 passed +24 subtests**,45 skipped;796 hashes, все787 previous unchanged;
main V8 unchanged. Определения header/footer наследуются независимо, settings/history
и исходные адреса проверены. Каталог пока не читает содержимое stories и не разрешает
самостоятельно исключать orphan parts из полного анализа. Далее **D03-17A2b4a2**:
main/header/footer reading + source-backed mapping. Ориентир **18–28 самостоятельных
циклов** до сверки крупных блоков; внешние UI/ML/native/release отдельно. Astra,
продолжаем автономно без переключения.

**4 ноября, D03-17A2b3c1 завершён:** [logical grid/text/mapping](d03-17a2b3c1-result.md),
full **5332 passed +24 subtests**,45 skipped;787 hashes/775 previous unchanged,
main V8 unchanged. Missing/empty/undersized grids читаются для регулярных retained
rows без выдуманных XML anchors. Unequal rows/gap fallback/сложные revision/native
boundaries остаются отдельной работой. Далее **D03-17A2b4a1** section/header/footer
reference catalog, затем story reading/mapping. Ориентир **18–28 самостоятельных
циклов** пока требует сверки крупных блоков; внешние UI/ML/native/release отдельно.
Astra, продолжаем автономно без переключения.

**4 ноября, D03-17A2b3b2 завершён:** [retained table revisions/text/mapping](d03-17a2b3b2-result.md),
full **5292 passed +24 subtests**,45 skipped;776 hashes, все763 previous unchanged,
main V8 unchanged. Inserted row/cell и deleted cell читаются с сохранением исходных
путей и проверкой текущей сетки. Current row deletion/cellMerge/hMerge/native boundaries
остаются отдельной работой. Далее **D03-17A2b3c1** missing/undersized current grid и
source-backed text/mapping. Ориентир **18–28 самостоятельных циклов** до сверки крупных
блоков; внешние frontend/ML/native/release gates отдельно. Astra, продолжаем автономно.

**4 ноября, D03-17A2b3b1 завершён:** [current table history/text/mapping](d03-17a2b3b1-result.md),
full **5250 passed +24 subtests**, 45 skipped; 763 hashes/747 previous unchanged,
main V8 unchanged. Четыре вида прежних свойств исключаются без изменения исходника;
current grid/style и source slices проверены. Далее **D03-17A2b3b2** retained grid
и текст при вставке строк/ячеек и удалении ячеек. Сложные row/merge/native boundaries
не закрыты. Ориентир **18–28 самостоятельных циклов** сохранён до сверки крупных
блоков; frontend/ML/native/release gates отдельно. Astra, продолжаем автономно.

**4 ноября, D03-17A2b3a4 завершён:** [styled table text/mapping](d03-17a2b3a4-result.md),
full **5197 passed +24 subtests**, 45 skipped; 750 hashes/740 previous unchanged,
main V8 unchanged. Одна 503 в первом полном прогоне не воспроизвелась в модуле и
повторном полном прогоне; причина не установлена, тесты не менялись.
Далее **D03-17A2b3b1** current table properties/history + source-backed text/mapping.
Ориентир **18–28 самостоятельных циклов** до сверки крупных оставшихся блоков;
внешние frontend/ML/native/release gates отдельно. Astra, продолжаем автономно.

**4 ноября, D03-17A2b3a3 завершён:** [neutral table-style catalog](d03-17a2b3a3-result.md),
full **5155 passed +24 subtests**,45 skipped;743 hashes/734 previous unchanged,
main V8 unchanged. Все conditional regions/ancestors проверяются без угадывания
visibility; неоднозначные определения остаются blocked. Далее **D03-17A2b3a4**
source-backed style selection/table reading/mapping и conditional metadata.
Ориентир **18–28 самостоятельных циклов** сохранён до следующей сверки крупных
блоков; UI/ML/native/release gates отдельно. Astra, продолжаем автономно.

**4 ноября, D03-17A2b3a2 завершён:** [visible table flows/mapping](d03-17a2b3a2-result.md),
full **5081 passed +24 subtests**, 45 skipped; 734 final hashes/724 previous unchanged,
ровно три разрешённых shared changes, main V8 unchanged. Body/cell/nested порядок,
точные исходные адреса, merged origin once и bounded source rebuild проверены.
Далее **D03-17A2b3a3** table-style neutrality catalog, затем его source-backed
versioned integration. Ненейтральные стили/правки таблиц/native boundaries и остальные
DOCX структуры остаются в объёме. Ориентир **18–28 самостоятельных циклов**, внешние
UI/ML/native/release gates отдельно. Astra, продолжаем автономно.

**4 ноября, D03-17A2b3a1 завершён:** [physical table catalog](d03-17a2b3a1-result.md),
full **5042passed +24subtests**,45skipped;727 final hashes/718 previous unchanged,
main V8 unchanged. Grid spans/vertical origins/nested cell blocks сохраняют исходные
адреса и содержимое continuation. Далее **D03-17A2b3a2** final table flows/mapping;
табличные стили/revisions/native boundary work остаются незавершёнными.
Ориентир **18–28 самостоятельных циклов**, внешние UI/ML/native/release gates отдельно;
уточнять по реальным оставшимся блокам, без обещания full DOCX по catalog. Astra,
продолжаем автономно.

**4 ноября, D03-17A2b2b2 завершён:** [итоговое чтение inline moves](d03-17a2b2b2-result.md),
full **4991passed +24subtests**,45skipped;718 hashes/707 previous unchanged,
пять разрешённых shared source changes, main V8 unchanged. Destination text и
source-backed mapping готовы в отдельном opt-in profile; application/native parity
gates остаются. Далее **D03-17A2b3a1** physical table grid catalog, затем b3a2 reader.
Ориентир **19–29 самостоятельных циклов** сохранён: table grid/reader явно разделены,
paragraph-boundary/native работа не отменена. Внешние frontend/ML/Windows/Word/release
gates отдельно. Astra, продолжаем без переключения.

**4 ноября, D03-17A2b2b1 завершён:** [структурный каталог moves](d03-17a2b2b1-result.md),
full **4961passed +24subtests**,45skipped;712 final hashes/704 previous unchanged,
main V8 unchanged. Пары range/member привязаны к исходным XML anchors; это ещё не
итоговый текст или ML admission. Далее **D03-17A2b2b2** versioned pure inline move
reader/mapping. Native Word control снова timeout, gate сохраняется. Остаток пока
**19–29 самостоятельных циклов**: уточнение reader/boundary разбиения не позволяет
механически вычитать каждый подцикл. Внешние UI/ML/native/release gates отдельно.
На выбранной Astra продолжаем без переключения.

**4 ноября, D05-06B завершён:** [owned fixture desktop lifecycle](d05-06b-result.md),
full **4912passed +24subtests**,45skipped,704 final hashes/main V8 unchanged.
Проверены real HTTP/PG import/edit/save/check/restart, fresh online license check,
accepted-write drain и crash recovery. API binding prerequisite выделен в daea453;
ни один старый тест не изменён. Следующий независимый **D03-17A2b2b1** — структурный
каталог перемещений текста Word. Режим менять не требуется, продолжаем автономно.
Ориентир **19–29 самостоятельных циклов**; frontend/weights/native Windows/Word/
release gates отдельно. D05 package/launcher/Windows остаются в очереди, не отменены.

**4 ноября, D05-06A завершён:** [owned SQL bridge](d05-06a-result.md), full
**4869passed +24subtests**,45skipped;690 final hashes,679 previous unchanged,
два разрешённых additive supervisor bridge changes. Main V8/schema/counts unchanged.
Native DOCX/fixture check/restart, actual PG identity, Stop/COMMIT и unknown cleanup
проверены. Далее **D05-06B** общий backend lifecycle и явное ожидание license worker
до освобождения Home. GUI/установщик/Windows и оставшиеся DOCX readers отдельно.
Ориентир **20–30 самостоятельных циклов**, реальные ML/UI/native release gates
отдельно; на выбранной Astra продолжаем без переключения.

**4 ноября, D05-05D2 завершён:** [backup/upgrade](d05-05d2-result.md), final full
**4848passed +24subtests**,45skipped;681 final hashes,666 previous unchanged,
разрешённый D1 shared-gate change. Main V8/schema/counts unchanged. Native backup,
реальный restore exact DOCX, exported snapshot, шесть crash cuts, Stop/COMMIT и
ошибки копии/диска проверены. Далее **D05-06A** explicit owned SQL bridge редактора/
supervisor, затем desktop composition. Mac wiring выполняем до Windows PG port
для сквозной native проверки на доступном хосте; Windows остаётся обязательным.
Ориентир **20–31 самостоятельный цикл**, реальные ML/UI/native release gates отдельно.
Astra подходит, продолжаем без переключения.

**4 ноября, D05-05D1 завершён:** [schema/local identity](d05-05d1-result.md),
full **4801passed +24subtests**,45skipped;667 hashes и657 previous unchanged,
main V8 unchanged. Native first/reopen/DOCX, пять crash cuts, Stop/rollback и
known-cleanup admission проверены. Далее **D05-05D2** backup/bounded upgrade,
затем desktop/Windows и незавершённые DOCX readers. Ориентир **20–31 самостоятельный
цикл**, внешние gates отдельно; Astra без переключения, продолжаем.

**4 ноября, D05-05C завершён:** [постоянная локальная PG](d05-05c-result.md),
full **4770passed +24subtests**,45skipped;657 hashes,643 старых unchanged и два
разрешённых additive profile changes; main V8 unchanged. Реальная временная PG:
first/reopen, сохранение COMMIT при Stop, семь crash cutpoints, missing/replaced
DB без пустой подмены. Далее **D05-05D1** schema bootstrap/local identity, затем
backup/upgrade, Windows и desktop composition/build. Astra без переключения.

Уточнён оставшийся PG/desktop блок: schema+backup2, Windows1–2, composition/build2–3,
то есть5–7 циклов. Вместе с DOCX13–19, adapter1–2 и финальной проверкой2–4 ориентир
**21–32 самостоятельных цикла**. Рост относительно механического счётчика B отражает
разделение schema/backup и сборки, а не новый продуктовый объём. Внешние frontend,
реальный ML pack, native Windows/Word, signing/TLS/release gates отдельно.

**4 ноября, D05-05B завершён:** [Mac PG process ownership](d05-05b-result.md),
full **4720passed +24subtests**,45skipped;645 hashes/main V8 unchanged. Проверены
COMMIT при Stop, restart и parent death с реальной временной PG18.6; unknown
outcomes остаются pending. Далее **D05-05C** durable cluster bootstrap/readiness,
затем Windows/schema/backup/composition. Ориентир **20–31 самостоятельный цикл**;
Astra без переключения, продолжаем.

**4 ноября, D05-05A завершён:** [профиль PostgreSQL18](d05-05a-result.md),
full **4680passed +24subtests**,45skipped;633 hashes/main V8 unchanged. Real temporary
Mac PG: initdb/peer/SQL/write/smart shutdown green. Далее **D05-05B** native Mac
process ownership, затем Windows/cluster preparation/schema/composition. Ориентир
**21–32 самостоятельных цикла** после пересчёта блоков ниже; Astra, продолжаем.

**4 ноября, D05-04 завершён:** [папка данных/identity](d05-04-result.md),
full **4598passed +24subtests**,45skipped;625 hashes/main V8 unchanged. Native macOS
restart/crash/ownership проверены; Windows native gate остаётся. Далее **D05-05A**
профиль PG18, затем native ownership/bootstrap, схема/backup и desktop composition.
Продолжаем на выбранной Astra без переключения.

**Уточнение остатка по фактическим незавершённым блокам,4 ноября.** Прежние11–26
механически уменьшались при дроблении runtime и больше не отражают очередь:
DOCX readers из A2b сами по себе ещё занимают13–19 циклов. Их blockers не сняты
позднейшими ML/API/licensing проверками. Новый рабочий ориентир **22–33 самостоятельных
цикла**: DOCX13–19; PG/запуск/сборка6–8; оставшийся adapter1–2; финальная независимая
проверка/передача2–4. Это исправление оценки прежнего объёма, не добавление функций.
Фронтенд Ани, настоящий ML pack, native Windows/Word, production signing/TLS/release
по-прежнему отдельные внешние gates. Пересчитывать по оставшимся задачам, а не
вычитать каждый новый подцикл из устаревшего общего числа.

**4 ноября, D05-03 завершён:** [проверка состава установки](d05-03-result.md),
full **4548passed +24subtests**,44skipped;614 hashes/main V8 unchanged. Pinned
manifest, exact inventory/streaming hashes, explicit fixture и observed mutation
проверены. Далее **D05-04** папка данных/stable identity/single-instance ownership,
после неё отдельный PostgreSQL bootstrap. Ориентир **11–26 самостоятельных циклов**;
на выбранной Astra продолжаем, без смены режима.

**4 ноября, D05-02 завершён:** [владение локальным сервером](d05-02-result.md),
full **4462passed +24subtests**,43skipped;606 hashes/main V8 unchanged. Реальный
HTTP/SQL save при shutdown завершился без потери DOCX; lifecycle/body/ownership
проверены. Далее **D05-03** проверяемый состав установки, затем отдельные runtime/
PG bootstrap и сборка. Ориентир **12–27 самостоятельных циклов**, Astra, продолжаем.

**4 ноября, D05-01 завершён:** [защищённый локальный API](d05-01-result.md),
full **4411passed +24subtests**,43skipped;594 hashes/main V8 unchanged. Реальный
loopback HTTP, exact DOCX save/export после expiry и pending fixture analysis
(success/Stop) проверены. Далее **D05-02** владение локальным сервером: lifecycle,
bounded input и graceful drain. UI/упаковка/публичный license server ещё отдельно.
Ориентир **13–28 самостоятельных циклов**, Astra, продолжаем.

**4 ноября, D04-03 завершён:** [клиент лицензии](d04-03-result.md), full
**4289passed +24subtests**,43skipped;582 hashes/main V8 checked. Native Mac
identity и server/client restart проверены; Windows/TLS deployment отдельно.
Далее **D05-01** защищённая локальная HTTP-граница: license guard, доступ только
из приложения и сохранение уже принятого текста после expiry. Frontend/установщик
ещё не готовы. Ориентир **14–29 самостоятельных циклов**, Astra, продолжаем.

**4 ноября, D04-02 завершён:** [сервер лицензий](d04-02-result.md), full
**4195passed +24subtests**,41skipped;570 hashes/main V8 unchanged. Проверены
атомарная one-device activation, повтор без renewal, check, отдельная БД/API/CLI.
Публичной deployment/TLS приёмки нет. Далее D04-03 клиент: HTTPS/current nonce,
native identity, постоянная идентичность активации и локальный срок.
Ориентир **15–30 самостоятельных циклов**; Astra без переключения, продолжаем.

**4 ноября, D04-01 завершён:** [license policy/protocol](d04-01-result.md), full
**4156passed +24subtests**,41skipped;561 hashes/main V8 unchanged. Нет SQL/сети в
pure core. Далее D04-02 отдельный сервер лицензий, затем D04-03 клиент и позже
desktop wiring. Ориентир **16–31 самостоятельный цикл**; текущая Astra, продолжаем.

**4 ноября, работа возобновлена по команде Никиты:** после E4C2 следующий
**D04-01** — [pure лицензирование](d04-01-contract.md), затем D04-02 сервер и
D04-03 клиент по [проекту](licensing-design.md). Три цикла внутри прежней оценки3–5,
новых продуктовых функций нет. Ориентир17–32 прежний до проверки первого цикла.
Историческая просьба остановиться ниже отменена. Main V8/чужие изменения сохраняем;
на выбранной Astra продолжаем без переключения.

**3 ноября, остановка по просьбе Никиты после завершения E4C2:**
[effective review HTTP](d03-17e4c2-result.md), full **4102passed +24subtests**,
41skipped;555 hashes/main V8 unchanged. Native Mac fixture edit/recheck/clear/reopen
прошёл. Новую задачу сейчас не начинать: пользователь закрывает ноутбук.
При возобновлении — контракт лицензирования с онлайн-проверкой при каждом запуске
(решение3ноября, F03); его реализация ещё не начата. Пакета ML нет.
Ориентир **17–32 самостоятельных цикла**, внешние frontend/ML/native release gates
отдельно. Astra можно оставить. Более ранние команды о непрерывной работе ниже
не отменяют эту последнюю просьбу остановиться.

**3 ноября, E4C1 завершён:** [effective commands и clear](d03-17e4c1-result.md),
full **4085passed +24subtests**,41skipped;553 hashes/main V8 unchanged. CAS/replay,
all-alias unhide и explicit recovery проверены. Далее E4C2 HTTP/native fixture.
Ориентир **18–33 самостоятельных цикла**; Astra без переключения, пакета ML нет.

**3 ноября, E4B завершён:** [scoped effective visibility](d03-17e4b-result.md),
full **4052passed +24subtests**,41skipped;549 hashes/main V8 unchanged. Чтение
возвращает все aliases и не меняет решения. Далее E4C1 команды/clear recovery,
E4C2 HTTP/view; нужны отдельные gates. Ориентир **19–34** сохранён: -1 завершённый
E4B, +1 за разбиение прежней интеграции на два шага. Astra, без переключения.

**3 ноября, E4A завершён:** [pure correspondence](d03-17e4a-result.md),
full **4019passed +24subtests**,41skipped;544 hashes/main V8 unchanged. Однозначное
сопоставление после edit проверено; persistent application ещё не подключено.
Далее E4B scoped resolver, E4C CAS/unhide/API. Ориентир **19–34 самостоятельных
цикла**, без зависимости от отсутствующего ML pack; продолжаем на Astra.

**3 ноября, E3 завершён:** [API фильтров/скрытия](d03-17e3-result.md),
[handoff фронтенду](docx-review-api.md); full **3974passed +24subtests**,41skipped,
539 hashes/main V8 unchanged. Native Mac fixture scenario прошёл. Далее E4A pure
conservative mapping, затем его persistence/integration отдельными циклами.
Ориентир **20–35 самостоятельных циклов**; Astra, без остановки на переключение.

**3 ноября, E2B завершён:** [постоянные фильтры/скрытие](d03-17e2b-result.md),
full **3948passed +24subtests**,41skipped,533 hashes/main V8 unchanged.
Атомарные CAS/receipts и безопасный replay проверены. Далее E3 HTTP, затем
E4 перенос между изменёнными source. Пакета модели нет — продолжаем без него.
Ориентир **21–36 самостоятельных циклов**, выбранная Astra без переключений.

**3 ноября, E2A завершён:** [schema памяти скрытия](d03-17e2a-result.md),
V13 только в disposable tests, full **3908 passed +24 subtests**,41skipped,
main V8 unchanged. Supervisor совместим с12/13. Дальше E2B scoped CAS/receipts,
затем E3 HTTP и E4 перенос. Ориентир **22–37 самостоятельных циклов**;
на выбранной Astra продолжаем без переключения.


**3 ноября, E1 завершён:** [фильтры и точные ключи скрытия](d03-17e1-result.md),
full **3874 passed +24 subtests**,41skipped, main V8 unchanged. Только pure
presentation; persistent state/UI ещё не объявляются готовыми. Дальше E2A schema,
E2B CAS/storage, E3 API, E4 conservative transfer. Ориентир **23–38 циклов**;
продолжаем на выбранной Astra без паузы.


**3 ноября, D03-17D завершён:** [результат](d03-17d-result.md),
[API для фронтенда](docx-analysis-api.md). Opt-in saved editor→supervisor→verified
results/Stop/retry; полный gate **3841 passed +24 subtests**,41skipped, main V8
unchanged. Учебный native macOS сценарий прошёл; настоящий ML не заявляется.
Никита подтвердил отсутствие models-0.2m: продолжаем независимые циклы.
Следующий E1 — pure filters/exact hide identity, затем отдельные persistence/API/
remapping. Ориентир **24–39 самостоятельных циклов**. На выбранной Astra
продолжаем без запроса смены режима.


**Текущий этап,3 ноября:** C2 [input guards](d03-17c2-input-result.md) и [сквозной native review fixture](d03-17c2-fixture-result.md) проверены; full3804passed/41skipped/+24subtests,exit0,main V8 unchanged. Реальные веса/adapter353cfee pending; по поручению Никиты продолжаем независимый **D03-17D** на Astra: [точный контракт API](d03-17d-contract.md). Остаток25–40, целый C2 пока не вычтен. Ниже история завершённого F3.

**Актуальный итог, 3 ноября: D03-17C1F3 завершён в fixture-границах.** [Результат](d03-17c1f3-result.md):90 targeted; полный gate3706passed/41skipped/+24subtests,exit0; main V8 неизменна. Конфликт early timeout устранён additive V12 с сохранением истории и безопасным downgrade. По последней команде Никиты продолжаем на Astra без смены режима: далее C2. Самостоятельный остаток **25–40**; нижние pending-статусы исторические.

**Текущий checkpoint,3 ноября:** **D03-17C1F3 не завершён**. Sol6.1 High реализовал доступную композицию:64passed/4deselected; отдельный probe подтвердил, что V11 `ck_dar_terminal_reason` запрещает обязательный ранний local timed_out. [Точный schema preflight](d03-17c1f3-schema-preflight.md), [проверки/частичный результат](d03-17c1f3-checkpoint-result.md). Следующий режим **Astra6 High — schema/compatibility design**, затем Sol заканчивает F3 без исключения четырёх cases. Старые source/tests/schema/main V8 сохранены, F3 не вычтен; остаток26–41, новых ID нет. Предыдущая передача на Sol ниже историческая.

**Текущий этап, 3 ноября:** проектирование **D03-17C1F3** на Astra6 High завершено: конфликт local deadline→SQL и композиция jobs/port/native cleanup определены. [Точный контракт](d03-17c1f3-contract.md), [матрица приёмки](d03-17c1f3-acceptance.md), [результат и регрессия](d03-17c1f3-design-result.md). Full3616passed+24subtests/41skipped,exit0; main V8 и483 hashes unchanged. **Далее Sol6.1 High → F3:** новая independent acceptance/freeze/red, затем три последовательных checkpoint внутри одного цикла, полный gate и локальный commit. Source/tests/schema старых циклов неизменны, production/Windows/boot/model gates открыты. Самостоятельный остаток **26–41**, новых ID нет; предыдущие передачи ниже — история.

**Передача после F2, 3 ноября:** F2 завершён commit3fc77f2. При подготовке F3 выявлен недостающий контракт continuous-deadline→SQL terminal, включая конкуренцию с committing/unknown permit; [точный preflight](d03-17c1f3-preflight.md). Нужен **Astra6 High focused design**, затем Sol6.1 High для реализации F3. Source/acceptance F3 не создавались, новых product cycles нет, остаток26–41. Предыдущая рекомендация механически продолжить F3 на Sol уточнена по фактическому конфликту на зелёной границе.

**Текущий итог, 3 ноября:** [F2 завершён](d03-17c1f2-result.md) на Sol6.1 High: SQL ledger/scoped lifecycle/bounded pools. Два согласованных preparation fixes,52/29 assertions preserved; targeted204passed, итоговый full3616passed+24subtests/41skipped,76warnings,402,69s,exit0. Main V8 и483 final hashes unchanged. Далее **D03-17C1F3 preparation на том же Sol6.1 High**. Самостоятельный остаток **26–41**, F2 вычтен один раз. Предыдущие pending статусы ниже — история.

**Согласования F2 получены, 3 ноября:** обе узкие поправки подготовки tests применены с явного разрешения Никиты;52/29 assertions unchanged, targeted204passed,32,83s. Идёт финальный full по [F2](d03-17c1f2-result.md). Далее тот же Sol6.1 High, F3 preparation. Пока final gate не завершён, F2 не вычитается из27–42.

**F2 открыт, 3 ноября:** source/V11/SQL services подготовлены на Sol6.1 High; [результат и pending approval](d03-17c1f2-result.md). Full3614passed+24subtests/2failed/41skipped,exit1: oracle SQL comment split и ещё один V10-only direct fixture требуют узких preparation поправок; ответы Никиты ожидаются. Сам код/F1/main V8 unchanged после gate,483 hashes совпали. Implementation F2 не закрыт/не закоммичен; F3 не начат. Режим Sol6.1 High достаточен, остаток27–42 прежний.

**Текущий цикл, 3 ноября:** [D03-17C1F1 реализован](d03-17c1f1-result.md) на Sol6.1 High: serialized dispatcher/Stop/lease и bounded publication port, без SQL/process startup. Freeze4f8c79d, targeted58passed, финальный full3566passed+24subtests/41skipped,75warnings,408,06s,exit0. Main V8 и468 прежних hashes unchanged, все475 final gate hashes совпали. Далее **F2 preparation на Sol6.1 High**, затем F3 по отдельным циклам. Самостоятельный остаток **27–42**; F1 вычтен один раз. Исторические записи ниже сохранены.

**Текущая передача, 3 ноября:** на Astra6 High подготовлен [C1F design](d03-17c1f-design.md) и [контракт F1](d03-17c1f1-contract.md). Следующая реализация **Sol6.1 High → D03-17C1F1**, затем F2 scoped SQL/ledger и F3 supervisor composition с отдельной приёмкой/проверкой/commit каждого. C1F source ещё отсутствует; automatic boot recovery и native production gates открыты. Одна прежняя строка F разбита на три, поэтому самостоятельный остаток **28–43** (+2 к26–41; новых продуктовых функций нет). Результаты design regression — в [отчёте](d03-17c1f-result.md). Нижние статусы исторические.

**Актуальный итог, 3 ноября:** [E4 завершён в available границах](d03-17c1e4-result.md) на Sol6.1 High. Добавлено ожидание освобождения канала в frozen тесте,44 assertions/source неизменны; imports отформатированы для Ruff. Targeted66passed/15skipped;10/10изолированных повторов проблемного теста; итоговый full3508passed+24subtests/41native skipped,74warnings,401,07s,exit0. Main V8 и468code/test hashes unchanged. **Теперь Astra6 High → C1F exact design**, [handoff](d03-17c1f-preflight.md); native Windows/durable recovery/real ML не подтверждены. Самостоятельный остаток **26–41**, E4 вычтен один раз, новых ID/циклов нет. Исторические состояния ниже сохранены.

**Текущая работа, 2 ноября:** [E4 source/результат](d03-17c1e4-result.md) подготовлены на Sol6.1 High. Полный gate3508passed+24subtests/39skipped,exit0; main V8 и E1–E3 unchanged. Но цикл ещё открыт: frozen тест повторного renew допускает гонку подготовки; одна строка ожидания owner release запрошена, ответа пока нет. Не скрывать первый targeted failure успешным full scheduling, не изменять frozen test без ответа. Сейчас тот же Sol6.1 High, после исправления/проверки — Astra6 High для C1F design. Остаток27–42, E4 пока не вычтен, новых циклов нет. Исторический design handoff ниже уже реализован в source.

**Текущая передача, 2 ноября 2026:** E3 available implementation `66f3bc6` проверен; **E4 спроектирован на Astra6 High**, [контракт](d03-17c1e4-contract.md), [результат](d03-17c1e4-design-result.md). Следующий шаг — **Sol6.1 High, D03-17C1E4 implementation** с собственной acceptance/freeze/red. Source/tests E4 ещё отсутствуют. Design regression3442passed+24subtests/26native skipped,exit0;460 code/test hashes и main V8 unchanged. Остаток **27–42** без новых циклов. После implementation E4 — отдельный C1F design на Astra6 High, production Windows wiring до recovery gate запрещён. Исторические записи ниже сохраняются как журнал решений.

31 октября 2026. Рабочая очередь, не новая продуктовая спецификация. Продуктовые границы — только current-product-scope.md. Прямое разрешение Никиты в этом чате: самостоятельно переходить к следующей функции после законченного и проверенного цикла; вопросы задавать здесь, независимую работу продолжать. Это исключение из прежнего запрета автоматического перехода, остальные AGENTS.md остаются в силе. Один цикл — один ID/контракт/приёмка/результат/локальный коммит. Runner/tasks/progress не переписывать. Перед повышением режима завершить цикл и остановиться с рекомендацией. После проектирования D03-14 на Astra 6 реализация продолжена на выбранном Никитой Sol 6.1 High.

Последний законченный цикл на старте: D03-10, ca4f797, 1576 tests + 24 subtests. Далее завершены D03-11 (0f7d1bd), D03-12 (ea98f84), D03-13 (1b11943), D03-14 (e995893), D03-15A (89bad1c), D03-15B1 (c95e796), D03-15B2 (dc53fe7), D03-15B3 (f88407f), D03-15C (ef33ffa) и D03-15D ([результат](d03-15d-result.md)). Gate завершения D03-15: **1897 tests + 24 subtests**, exit 0, 171,13 секунды. Основной frontend ожидается от Ани; текущий workspace — проверочный интерфейс, не замена её работы.

## Ближайшие независимые backend-циклы

1. D03-11 — безопасная вставка и удаление абзацев DOCX с сохранением остальных bytes/частей.
2. D03-12 — стили заголовков и native списки, через отдельный ограниченный контракт.
3. D03-13 — атомарное сохранение этих команд через API, CAS/idempotency и handoff для frontend.
4. Далее отдельные циклы: разбиение/объединение и вставка многострочного текста; адаптер проверок и снимок DOCX для модели; состояние/остановка/тайм-аут анализа; сохранение/фильтры/скрытие замечаний; лицензирование; desktop-поставка и проверка целевых платформ. Каждый ID/границы фиксировать перед реализацией, а не объявлять весь список одной задачей.

D03-11…D03-14 и D03-15A/B1/B2/B3/C/D завершены отдельными контрактами/приёмкой/коммитами; [handoff API](docx-editor-api.md), [архитектура split/join/undo/recovery](d03-14-design.md). Реализованы pure boundaries, общая exact history для range/structure/formatting и controller с selection, Enter/join, форматированным вводом в пустой p и многострочным plain-text paste. D03-15D добавляет native soft-break intent отдельно от paragraph boundaries. Это backend-controller без DOM/IME bindings, новых HTTP routes или durable restart recovery. Несовместимые paragraph styles требуют отдельного resolver, а не потери оформления ради склейки. Приёмка последующих циклов фиксируется перед каждым из них; runner/tasks/progress не меняются.

## D03-16 — проект сохранения и восстановления готов

31 октября на Astra 6 High подготовлен [точный проект](d03-16-design.md). Завершены A [restore](d03-16a-result.md), B1 [schema](d03-16b1-result.md), B2A [codec](d03-16b2a-result.md), B2B [checkpoint CAS](d03-16b2b-result.md), C1 [prepare](d03-16c1-result.md), C2 [commit](d03-16c2-result.md), C3A [finalize/status](d03-16c3a-result.md), C3B [discard/reconcile](d03-16c3b-result.md). Gate завершения C3B **2086 tests + 24 subtests**, exit 0. Durable storage protocol затем подключён к живому controller циклами D/E ниже.

Архитектурный проход **D03-16D завершён на Astra 6 High**: [решения](d03-16d-design.md), [контракт D1](d03-16d1-contract.md), [результат](d03-16d-result.md). Реализованы **D1** ([результат](d03-16d1-result.md)), **D2** ([результат](d03-16d2-result.md)), **D3A** ([результат](d03-16d3a-result.md)), **D3B** ([результат](d03-16d3b-result.md)), **E1** ([результат](d03-16e1-result.md)), **E2** ([результат](d03-16e2-result.md)), **E3A** ([результат](d03-16e3a-result.md)), **E3B** ([результат](d03-16e3b-result.md)), **E3C** ([результат](d03-16e3c-result.md)): scoped registry/native commands, checkpoint/save/recovery, exact snapshots и pure strict wire codec. Последний полный gate **2301 tests + 24 subtests**, exit 0. D03-16 backend implementation pass завершён; каждый цикл имеет freeze/red/implementation/gate/result/local commit. Далее отдельный архитектурный D03-17 на **Astra 6 High**, после проекта реализация на **Sol 6.1 High**. Runner/tasks/progress не менять.

Проверенные основания и предмет проектирования:

- EditorSession/DocxSession держат историю и position/revision в RAM. Новый процесс начинает историю заново; transport должен различать эпохи сессий, чтобы старая команда с тем же числом revision не прошла после restart. Полный undo stack между запусками пока не обещан.
- recovery_schemas.RecoveryPayload и recover() строго читают только TextEditRequest с pending operation_id. Запись нового DOCX checkpoint в тот же JSONB без versioning/совместимости сломает старых readers. Нужны точная схема, миграция или отдельное хранилище с явной арбитрацией одного draft, строгие scope/CAS и совместимость прежнего /draft.
- Saved current, working DOCX, selection и неизменяемый pending save должны иметь отдельный жизненный цикл. Выбрать частоту/стоимость checkpoint и границу возможной потери ещё не записанного хвоста; продуктовый autosave остаётся две минуты. Не обещать zero-loss RAM или переписывать большой DOCX в PostgreSQL на каждый символ без оценки.
- Старые /paragraph-commands, /text-edits и PUT content остаются внешними writers: их storage revisions нельзя незаметно затереть новым controller. Нужны project/document lock order, конфликт без автоматического merge и сохранение рабочей копии.
- Candidate готовится до изменения живой RAM; durable update + receipt атомарны. ACK-loss требует повторять тот же immutable operation ID/candidate, а не split/join заново. Старый replay не заменяет новый current. Ошибка очистки pending должна оставлять восстановимое состояние, не удаляя draft другого окна.
- Приёмка следующего проекта: crash до/после transaction commit, потерянный ответ, повтор/подмена ключа, несколько окон/процессов, чужой writer, удаление/переключение документа, legacy checkpoint, budgets/невалидный package, restart с сохранением bytes/selection/receipt и без ложного mark_saved. Выбрать bounded подциклы до кода, не менять все слои одним проходом.

D03-16E3C завершает scoped HTTP deadlines/handoff. Рабочая БД остаётся V8; V9/editor API проверены на disposable БД, автоматической миграции нет. Следующий архитектурный цикл сначала читает current-product-scope.md, docx-editor-api.md, актуальные backend/ML contracts и локальный снимок engine Артёма. Нужен собственный дизайн/подциклы до нового кода; ожидание фронта Ани не блокирует проектирование. На этой границе рекомендована смена на Astra 6 High, поэтому автономная реализация остановлена после законченного E3C.

Дизайн недостающего поведения решать в узком контракте, сохраняя пользовательские данные и старые проверки. Не выдавать fixture за анализ, проверочный UI за готовый frontend или сборку без проверки Windows/macOS за готовый релиз. При внешнем блокере пропускать только зависимую часть; не менять критерии, чтобы получить готовность.

## Проверка работы Артёма

31 октября прочитан private репозиторий gorokhovartempsystech-wq/aira через открытый пользователем GitHub (коннектор вернул 404, браузер авторизован). Скачан main snapshot 036a4e89027276144c51de14f0cc91412c59f437 в ignored .runtime/aira-team-036a4e8; удалённый репозиторий не менялся, код не запускался.

Есть engine/aira_ml/engine.py — ONNX CPU runtime, локальные parse/review/impact, контракт contracts/engine-api.md и JSON Schema. Веса по README должны быть в models-0.1.zip из Releases, но страница Releases показывает отсутствие опубликованных релизов. Снимок исходников весов не содержит. Это не отсутствие ML-кода; реальный запуск без пакета не подтверждён. Адаптер можно подготовить на реальных схемах, сам запуск ML пропустить до появления пакета, как разрешил Никита. Старый app/README.md включает автоисправления/impact/MD/ISO; эти возможности не возвращать поверх текущего объёма автоматически.

Источники: [engine](https://github.com/gorokhovartempsystech-wq/aira/tree/036a4e89027276144c51de14f0cc91412c59f437/engine), [контракт](https://github.com/gorokhovartempsystech-wq/aira/blob/036a4e89027276144c51de14f0cc91412c59f437/contracts/engine-api.md), [Releases](https://github.com/gorokhovartempsystech-wq/aira/releases).

## Лицензирование

Прямые сообщения 31 октября: настраиваемое время действия в нашей серверной таблице, онлайн-проверка введённого ключа и выдача доступа на n времени. Бессрочность отменена. Срок/первая активация/привязка устройства и безопасный повтор нужны; конкретную длительность не выдумывать. Секреты только ~/secrets.env, ключи не хранить/не логировать открыто. Деплой сервера и домен не предполагаются готовыми.


## D03-17 — архитектура готова, следующий цикл A1

Предмет — F06–F10 поверх exact saved DOCX snapshot: подготовка текста/фрагментов и обратное отображение ML offsets в Word anchors, привязка к storage revision/SHA, вопросы/замечания/coverage, lifecycle запуска/stop/timeout5min/retry, stale results и решения о скрытии по документу. Текущий source для ML — снимок Артёма 036a4e8, contracts/engine-api.md и engine.schema.json; он использует fragments/offset/span и formulation/duplicate/contradiction, прежний backend0.1 — другие request/result/coverage/change_groups. Не внедрять старый Merge/автофикс/ISO из этих источников поверх актуального scope.

До реализации согласовать bounded bridge, несовместимости и миграции/новый API/бюджеты/acceptance, сохраняющие старые tests/contracts. Нельзя объявлять full DOCX analysis по одной main-body projection или молча обрезать/терять unsupported части. Устойчивость fragment IDs/anchors после split/join/repeat text и точные Unicode offsets влияют на подсветку и скрытие новых замечаний; это требует отдельного решения. Реальный engine run без весов пропускается, как разрешил Никита; fixtures явно помечать. Не менять текущие contracts/schema/runner/tasks/progress этим handoff.

31 октября после переключения на Astra 6 High выполнено проектирование: [D03-17](d03-17-design.md), [контракт A1](d03-17a1-contract.md), [результат](d03-17-result.md). Выбраны pinned saved source, exact Word anchors/code-point spans и coverage ledger; отдельный namespace/новые таблицы без изменения старого backend0.1; child-process bridge без upstream HTTP; общий deadline300s, cancel/lease/fencing; строгие result/quote/token guards; stale results и консервативное сохранение решений о скрытии. Обычный parse_text Артёма пропускает headings/короткие строки, tokenizer обрезает ввод — эти пути не использовать без адаптера. Реальные weights не запускались, pinned snapshot не выдаётся за актуальность удалённого main.

Следующий bounded цикл **D03-17A1 на Sol 6.1 High**: pure DOCX snapshot + coverage + обратные адреса подсветки, без SQL/HTTP/модели. После него отдельные A2 readers/inventory, B1 validation, B2/B3 storage/lifecycle, C1/C2 supervisor/engine bridge, D end-to-end API, E preferences/hide, F реальные модели/платформы. Сейчас точный implementation contract есть только у A1; остальные предварительно получают собственные allowed paths/приёмку. Отсутствие weights не блокирует независимые циклы; comments/revisions policy уточняется перед зависимым reader. Main остаётся V8, frontend Ани/лицензия/установщики не объявляются готовыми.

На этой границе завершён дизайн и рекомендован возврат с **Astra 6 High на Sol 6.1 High**. Это оценка конкретной задачи, не обещание стоимости или невозможности выполнить её на другой модели. До смены режима приложение в D03-17 не реализовывалось; runner/tasks/progress не меняются.

1 ноября на выбранном Sol 6.1 High завершён **D03-17A1**: [результат](d03-17a1-result.md). Pure snapshot/coverage/exact span mapping, freeze9239f0a, red52 failures, targeted163 passed, full gate **2370 tests + 24 subtests**, exit0. Rich fixture:26 exact mapped fragments, complete=false при неподдержанных частях, bytes unchanged. Следующий отдельный цикл **D03-17A2a** — inventory package parts/relationships и согласованная DOCX policy. Продолжать на Sol 6.1 High по прямому разрешению Никиты, сначала собственный контракт/приёмка.

Затем автономно завершён **D03-17A2a**: [результат](d03-17a2a-result.md), freezefd76d9a, red35 failures, targeted109 passed, full gate **2410 tests + 24 subtests**, exit0. Учтены все package parts/links, без external fetching или ослабления A1 coverage. Main остаётся V8. Сегодня Никита согласовал итоговый текст revisions и сохранение comments без анализа; источник записан в current-product-scope.md.

Следующий **D03-17A2b — архитектура final-view reader/story coverage/source mapping**. Рекомендован **Astra 6 High для проектирования**, затем Sol 6.1 High для маленьких implementation cycles. Удаление paragraph mark в Word может объединять текст физических paragraphs; A1 single paragraph anchor нельзя подменить без нового профиля/DTO. Нужно заранее решить multi-source ranges, insert/delete/move на разных уровнях, story/field/SDT/textbox coverage и acceptance. Подробные основания/ссылки Microsoft и handoff — в результате A2a. На границе законченного и проверенного A2a реализация остановлена для смены режима по прежней команде Никиты; runner/tasks/progress не меняются.

1 ноября **D03-17A2b спроектирован на Astra 6 High**: [дизайн](d03-17a2b-design.md), [контракт b1](d03-17a2b1-contract.md), [результат](d03-17a2b-result.md). Выбраны новый final-view profile/DTO, logical paragraph с несколькими source p, exact pieces и joins, source slices вместо одного общего range; контекстные правила Final и coverage admission. Inserted paragraph mark сохраняется по уточнению Microsoft MS-OI29500, deleted mark объединяет text; old A1 остаётся совместимым. Первый reader ограничен supported main grammar, остальные structures имеют явные blockers до своих readers.

Полный gate дизайна **2410 tests + 24 subtests**, exit0, main V8/baseline unchanged. Следующая реализация **D03-17A2b1 на Sol 6.1 High**: freeze новых acceptance→red→source→targeted/full→baseline/result/local commit. Затем отдельные b2a properties/visibility, b2b moves, b3 tables, b4 stories, b5 fields/containers/media, b6 assembly/Word corpus по точным contracts. Не начинать все слои одним циклом и не переписывать tests/runner. На границе завершённого дизайна рекомендован возврат на Sol; реальная модель/UI/desktop этим не объявляются готовыми.

1 ноября **D03-17A2b1 реализован на Sol 6.1 High**: [результат](d03-17a2b1-result.md). Freeze d117eba, red47 failures, targeted150 passed, full **2473 tests + 24 subtests**, exit0. Source-exact logical paragraphs/pieces/joins, multi-range mapping, contextual grammar/coverage/budgets; old A1/A2a неизменны, main V8. Следующий bounded цикл b2a1 — current-vs-historical direct properties по новому opt-in profile. Сначала собственный exact contract/приёмка, продолжать на Sol 6.1 High по разрешению Никиты.

Затем автономно реализован **D03-17A2b2a1**: [контракт](d03-17a2b2a1-contract.md), [результат](d03-17a2b2a1-result.md). Freeze5ce8b7f, red15 failures, targeted171 passed, полный gate **2494 tests + 24 subtests**, exit0. Opt-in final-properties-v1, explicit historical coverage, неизменный b1 default; source bytes/main V8 unchanged. Никита отдельно согласовал проверять только видимый текст; решение записано в current-product-scope.md, resolver пока не реализован.

Следующий **D03-17A2b2a2 — проектирование effective visibility/style context на Astra 6 High**, затем реализация на Sol. Новая policy требует учесть docDefaults/basedOn/paragraph/character/direct formatting, toggle semantics, hidden paragraph mark и source boundaries; простого удаления прямых vanish недостаточно. Ссылки Microsoft и конкретный handoff — в результате b2a1. До этого source profiles с unresolved visibility сохраняют blocker. На границе законченного и проверенного b2a1 остановиться для согласованной смены режима, а не начинать неподготовленную реализацию нового правила. Runner/tasks/progress не менять.

1 ноября **D03-17A2b2a2 спроектирован**: [дизайн](d03-17a2b2a2-design.md), [первый контракт](d03-17a2b2a2a-contract.md), [результат и проверка](d03-17a2b2a2-result.md). Определены отдельный styles context, policy final-visible-no-comments-v2, контекстное вычисление visibility и новый boundary/mapping слой. BasedOn-цепочка и toggle между уровнями стилей разделены; скрытый run не удаляется из source, скрытая граница не подменяется revision marker. Реализация обычного visible flow не будет угадывать видимость через неподдержанные settings или сложные joins. Native Word comparison остаётся отдельным gate; code/tests/БД/runner не менялись.

Полный gate дизайна: **2494 tests + 24 subtests**, exit0; main V8/schema/counts unchanged. **Следующий режим — Sol 6.1 High, D03-17A2b2a2a**: pure styles catalog/current properties/basedOn/provenance, точные allowed paths/API/grammar/limits/acceptance подготовлены. Сначала freeze/red, затем implementation/targeted/full/baseline/result/local commit. После — отдельные b2a2b visible-main snapshot/mapper и b2a2c boundaries/Word corpus, каждый со своим контрактом до кода. Продолжать на Sol без повторного подтверждения по прежнему разрешению Никиты; на текущей границе завершён дизайн и рекомендован возврат с Astra на Sol. Новых продуктовых вопросов нет, push не разрешён.

Затем **D03-17A2b2a2a реализован на Sol 6.1 High**: [результат](d03-17a2b2a2a-result.md). Freeze a214b7b, red52 failures, targeted236 passed; полный gate **2559 tests + 24 subtests**, exit0. Current properties/nearest basedOn/provenance, cycle/type/structure guards и bounded parsing; source bytes/main V8 unchanged. Это styles catalog без объявления готовности полной проверки hidden text. Продолжать на Sol: следующий отдельный b2a2b contract/acceptance для ordinary visible flow, без автоматического переноса старых joins.

Автономно завершён **D03-17A2b2a2b1**: [контракт](d03-17a2b2a2b1-contract.md), [результат](d03-17a2b2a2b1-result.md). Из b2a2b выделена bounded algebra/selection перед snapshot: batch ordinary-run queries, pinned catalog один раз, D/P/C/direct rules, отдельные specVanish/webHidden metadata, static blockers. Freeze89f1ae8, red33 failures, targeted276 passed, полный gate **2599 tests + 24 subtests**, exit0. Main V8/source bytes unchanged. Batch ещё не является чтением XML runs или допуском к ML.

Следующий **D03-17A2b2a2b2 — exact visible-main snapshot/source binding/mapper contract**. На завершённой и проверенной границе рекомендован **Astra 6 High для короткого проектирования**, затем Sol 6.1 High для реализации. Нужны точные DTO/manifest/visibility evidence/coverage validators, запрет highlights через hidden gaps и защита от rehashed forged mappings. Отдельно уточнить admission case implicit default character=false при docDefaults=true; b1 convention не доказывает Word parity. Не переписывать frozen b1 и не выдавать batch за готовый full reader. Продуктовых вопросов нет; runner/tasks/progress и push не трогать.

1 ноября этот архитектурный проход выполнен: [контракт b2](d03-17a2b2a2b2-contract.md), [результат дизайна](d03-17a2b2a2b2-design-result.md). Следующий шаг — **реализация D03-17A2b2a2b2 на Sol 6.1 High**, без нового проектного дробления перед первым кодом. Whole-main reader получает selectors из оригинала, сохраняет provenance в versioned snapshot и исключает hidden text с exact source gaps. Новый mapper обязательно принимает оригинальные bytes и проверяет весь снимок повторной сборкой один раз на batch; rehashed forged ranges не проходят. Старые snapshots/API неизменны. Implicit default character с любым explicit visibility value и потенциальные hidden/deleted paragraph boundaries остаются explicit blockers до собственных readers/native evidence. Acceptance freeze/red относится к реализации, не имитируется в документационном цикле.

Gate проектирования: **2599 tests + 24 subtests**, 77 warnings, exit0; main V8/schema/counts unchanged. Поведение приложения не менялось. Следующий implementation cycle не требует продуктового ответа; новый контракт/приёмка фиксируются перед source. Переход на Sol — согласованная граница режима после завершённого дизайна, не ожидание фронта/модели.

Затем **D03-17A2b2a2b2 реализован на Sol 6.1 High**: [результат](d03-17a2b2a2b2-result.md). Freeze d0f8c13, red43 failures, targeted428 passed; финальный gate **2656 tests +24 subtests**, 75 warnings, exit0. Main V8/schema/counts/source unchanged. Новый visible-main reader извлекает XML-derived selectors/direct provenance и hidden gaps; mapper сверяет snapshot по original bytes одним rebuild на batch. Frozen tests/старые source не менялись. Следующий цикл b2a2c сначала проверяет native Word evidence и фиксирует отдельные границы; при недоступности зависимой проверки продолжать независимый B1, не объявлять hidden joins готовыми.

После этого implementation cycle прежняя планировочная оценка самостоятельного остатка уменьшается до **29–44 циклов** (DOCX13–19, остальные блоки ниже прежние). Это тот же ориентир, а не новый гарантированный срок/потолок; native Word/сложная матрица могут потребовать уточнения.

Native preflight **D03-17A2b2a2c0**: [контракт](d03-17a2b2a2c0-contract.md), [наблюдения/блокер](d03-17a2b2a2c0-result.md). Word16.114.3/version query доступны, но open/retrieval control не завершён (AppleEvent-1712/timeout); native evidence не получено. b2 guards не снимать, c не считать готовым, остаток29–44 пока прежний. Следующий независимый **D03-17B1 на Sol 6.1 High**: по D03-17 exact wire/request/result validation, без ожидания весов/frontend и без снятия DOCX coverage blockers. Перед реализацией отдельный контракт/приёмка/freeze/red; dependencies и legacy API не менять.

По просьбе Никиты native probe повторён: direct hidden gap успешно прочитан как abcd с ожидаемыми font.hidden flags; setter retrieval mode дал-10006, а новый plain fixture опять-1712, batch остановлен. Общий native gate по-прежнему blocked; подробности/границы доказательства в результате c0. Отсутствие лицензии Microsoft может ограничивать setters, но причина ошибок не установлена; штатная AIRA не использует Word как обязательную runtime dependency. Продолжать независимый B1 на Sol.

Затем независимо реализован **D03-17B1**: [контракт](d03-17b1-contract.md), [результат](d03-17b1-result.md), новая JSON Schema docx-review/1. Freeze ed69b2d, red35 failures, targeted476 passed; финальный full gate **2704 tests +24 subtests**, 75 warnings, exit0. Source-backed request admission и atomic strict result validation, one mapping batch, exact related evidence, semantic IDs и вопросы/all origins, private provenance и честный fixture flag. Реальная модель/новые HTTP/БД этим не запускаются; main V8/schema/counts unchanged, frozen/legacy source/tests сохранены.

Самостоятельный остаток после b2+B1 ориентировочно **28–43 циклов**: DOCX13–19, проверка/результаты6–9, лицензирование3–5, поставка4–6, финальная проверка2–4. Native c0 не вычитается как реализованный reader; диапазон не гарантированный потолок. Следующий **D03-17B2 — архитектурный проход на Astra 6 High**, затем реализация на Sol6.1 High по exact DDL/контракту/новой frozen acceptance. Нужны immutable source/run/attempt/result связи с готовым B1 wire, constraints/lease/fence/deadline/active uniqueness и безопасная migration compatibility/downgrade. Подробный handoff в результате B1. На этой законченной и проверенной границе остановиться для согласованной смены режима, main автоматически не мигрировать, runner/tasks/progress не менять.

Затем по команде Никиты на Astra завершён **design-cycle D03-17B2**: [решения](d03-17b2-design.md), [точный DDL](d03-17b2-schema.sql), [контракт следующего B2A](d03-17b2a-contract.md), [результат](d03-17b2-result.md). Четыре отдельные таблицы, exact BYTEA wire/source/provenance, scoped deferred FK для атомарных attempt/result, один inference/run, deadline/lease/fences, replay и безопасный downgrade. SQL проверен только на одноразовой V9 БД; это не установленная миграция. Приложение/рабочая БД/source/tests/runner не меняются. Следующий **D03-17B2A на Sol 6.1 High**, затем B2B, B3A/B3B по отдельным контрактам и gate без новых подтверждений, если не возникает архитектурного конфликта.

B2A затем реализован на Sol6.1 High: [результат](d03-17b2a-result.md), freeze d55e0c7, новый exact DDL/ORM и V10, safe downgrade без потери analysis history. Full gate **2838 tests +24 subtests**,77 warnings,exit0; main V8/counts unchanged. Следующий B2B — codec/source-backed reconstruction, на том же Sol6.1 High. После B2A текущий остаток **29–44** (проверка/результаты7–10 вместо8–11); таблица ниже сохраняет оценку на границе завершённого дизайна.

B2B выполнен независимо: [результат](d03-17b2b-result.md), freeze054e958, pure canonical storage codec и source/request/reply-backed восстановление без inference. Full gate **2896 tests +24 subtests**,75 warnings,exit0; main V8 unchanged. Следующий **B3A start/read/replay/retry на Sol6.1 High**, затем B3B lifecycle. Текущий самостоятельный остаток **28–43** (проверка/результаты6–9); нижняя таблица — историческая оценка на границе B2 design.

B3A завершён: [результат](d03-17b3a-result.md), freeze f7f4e4c, scoped start/replay/retry и metadata/source reads. Gate **2927 tests +24 subtests**,77 warnings,exit0; main V8 unchanged. Следующий **B3B lifecycle на Sol6.1 High**, затем C1 process supervision. После B3A текущий самостоятельный остаток **27–42**; завершённая очередь пока не означает работающий worker/модель.

B3B завершён: [результат/handoff C1](d03-17b3b-result.md), freeze f64bcab, fenced claim/lease/cancel/reaper и atomic result/reconciliation. Full gate **2957 tests +24 subtests**,75 warnings,exit0; main V8 unchanged. После B3B остаток **26–41 самостоятельный цикл**. Следующий **C1 design на Astra6 High**, затем implementation Sol: выбрать Windows/macOS ownership/lifetime, closed IPC, monotonic deadline/heartbeat и local Stop latch с явной координацией in-flight publication при DB outage. SQL lifecycle не объявлять end-to-end supervisor. Законченный цикл/локальный commit перед остановкой для смены режима; runner/tasks/progress не менять.

## D03-17C1 — проект управления процессом готов

1 ноября на Astra6 High по команде Никиты подготовлен [C1 design](d03-17c1-design.md) и [контракт C1A](d03-17c1a-contract.md). Уточнена гонка Stop/COMMIT: compute прекращается независимо от DB, право начать новую публикацию отзывается локальным арбитром, уже допущенный unknown commit разрешается ordered-lock чтением; ранний cancelled ACK запрещён. Continuous clock включает сон компьютера. Выбраны отдельный guardian, два lifetime locks, private bounded pipes, macOS ownership и Windows Job; native Windows gate остаётся отдельным. Подробности/границы в [результате](d03-17c1-result.md). Runtime code не менялся. Полный gate **2957 tests +24 subtests**,76 warnings,exit0; main V8/schema/counts unchanged.

**Далее переключить на Sol6.1 High и реализовать D03-17C1A**, затем C1B guarded SQL, C1C codec, C1D macOS, C1E Windows, C1F scheduler по отдельным freeze/red/gate/result/commit. Веса/новый engine payload — C2, не часть C1. Следующий Astra pass нужен только при новом архитектурном противоречии. Независимый остаток **31–46 циклов**: прежняя крупная строка C1 разбита на шесть (+5 к26–41), новых продуктовых функций нет. Эта оценка заменяет прежний текущий счётчик, таблица ниже остаётся историей B2 design. Полноценный DOCX/лицензия/desktop/финальная интеграция по-прежнему впереди.

## Оценка самостоятельных циклов на границе B2 design, 1 ноября

По просьбе Никиты оцениваем **нашу часть без ожидания кода Ани и весов/доработок Артёма**. Финал этой части: проверенные backend/document APIs и сохранение результатов, готовый адаптер модели с честными fixture tests, реализация лицензирования, независимая инфраструктура запуска/сборки и документация подключения. Это ещё не готовый пользовательский релиз с настоящей моделью и интерфейсом. Считается цикл «ограниченный контракт + приёмка + реализация + проверка + результат/коммит»; отдельный необходимый архитектурный проход входит в резерв диапазона, а не считается бесплатным. Текущий design-cycle уже завершён и в остаток не включён.

| Самостоятельный блок | Оценка циклов | Что остаётся |
|---|---:|---|
| DOCX: чтение, координаты, полноценная матрица обработки | 13–19 | Hidden/revision boundaries; moves; tables/grid; sections/stories/notes; fields/containers/media; settings/numbering/font/theme/MC admission; assembler и закрытие подтверждённых пробелов редактора/экспорта. Visible-main b2 завершён; пустой blocker вместо обязательной возможности не считается её завершением |
| Проверка и результаты | 8–11 | B2A schema, B2B codecs, B3A start/replay/read, B3B worker lifecycle, C1 subprocess, C2 adapter с token guards, D API/freshness/questions, E filters/hide/unhide; crash/cancel/retry и независимые cut-point tests. B1 и B2 design завершены |
| Лицензирование | 3–5 | Device binding/серверная таблица с настраиваемым сроком, активация/idempotency, локальное подписанное подтверждение/проверка срока и ошибки. Сначала согласовать открытые бизнес-правила; пока этой реализации в src/ara нет |
| Независимая поставка и запуск | 4–6 | Local runtime/порты/процессы/миграции без пользовательской настройки БД, сборочные рецепты Windows/macOS, asset/model manifest с fixtures, шаблон скачивания/релизных метаданных. Не заменять frontend Ани и не публиковать фальшивые загрузки |
| Финальная независимая проверка и передача | 2–4 | Сценарий import/edit/save/check-fixture/export/reopen, восстановление/ошибки/ресурсные бюджеты, synthetic DOCX round-trip и передача API/сборки; найденные интеграционные дефекты |
| **Всего ориентировочно** | **30–45** | Рабочий диапазон, не обещанный фиксированный счётчик |

Основания: D03-16 backend pass завершён; D03-17A1/A2a/property history/catalog/rules/ordinary visible-main/B1 завершены. Последний промежуточный ориентир28–43 выше уточнён до **30–45**: две крупные строки B2/B3 разделены каждая на два проверяемых implementation цикла, новые продуктовые функции не добавлены. Design B2 завершён и повторно в остатке не считается. Таблица D03-17B…F и readers из d03-17a2b-design остаётся действующей. docs/docx-editor-api.md явно ограничивает сложное редактирование; неизвестную матрицу нельзя объявить готовой по числу тестов. Licensing/desktop production modules в текущем src/ara не обнаружены. Старые рабочие материалы/Confluence/Merge/auth scope в оценку не входят.

Нижняя граница предполагает повторное использование уже проверенных компонентов без пересмотра архитектуры; верхняя включает обычные уточнения DOCX и дополнительную приёмку. Самый большой риск роста — требование полноценного Word, пока точная матрица сложного редактирования/отображения не закрыта; диапазон не является потолком. Пересматривать после завершения DOCX reader/admission и после первого E2E, объясняя добавленный объём, а не молча увеличивая номера подциклов.

Отдельные внешние gates, **не включённые как выполненные самостоятельные циклы**: настоящий frontend и его UX от Ани, актуальный ML pack/weights и качество модели от Артёма, совместная сборка с ними, замеры на целевом железе и native Word/Windows/macOS приёмка там, где нет доступной среды, production подпись/хостинг/публикация. Их отсутствие не блокирует независимый код, но блокирует утверждение «готовый релиз». Лицензионные правила могут потребовать ответа Никиты; согласование не равно ожиданию команды. Без новых обстоятельств не просить повторного разрешения на каждый обычный цикл.

C1A реализован на Sol6.1 High: [результат](d03-17c1a-result.md), freeze36a4eb5; pure budget/Stop/publication arbiter без SQL/process/clock I/O. Full gate **3025 tests +24 subtests**,74 warnings,exit0, main V8 unchanged. Далее отдельный **C1B guarded SQL на Sol6.1 High** без паузы; остаток **30–45 самостоятельных циклов**.

C1B завершён: [результат](d03-17c1b-result.md), freeze985683d, implementation10ae0ad; guarded SQL publication/locked reconciliation, no inference/old unguarded calls. Gate **3057+24**,75 warnings,exit0; main V8 unchanged. Далее **C1C wire на Sol6.1 High**; самостоятельный остаток **29–44 цикла**.

C1C завершён: [результат/handoff C1D](d03-17c1c-result.md), freezedc07ac0, implementationd9fedb8; strict bounded private wire encoder/parser, без модели/SQL/OS launch. Gate **3121+24**,75 warnings,exit0, main V8 unchanged. Остаток **28–43 цикла**. Native preflight подтвердил NOTE_EXIT/slot inheritance/setsid, но killpg после завершения дал EPERM; Apple source допускает zombie-only ветку с таким errno. Это не подтверждённый sandbox blocker и не proof live teardown. **Далее Astra6 High для точного C1D native lifecycle/startup контракта**, затем Sol implementation. Не смешивать unknown/live/confirmed-exit, не добавлять bootstrap ACK в frozen C1C молча. Остановиться после законченных C1A/B/C только для согласованной смены режима.

## D03-17C1D — уточнённый macOS проект готов

1 ноября на Astra6 High завершён [C1D design](d03-17c1d-design.md), [результат/handoff](d03-17c1d-result.md), [контракт первого D1](d03-17c1d1-contract.md). Frozen C1A/B/C не менялись. Зафиксированы separate bootstrap prepared/gate/armed без расширения wire, единственный signal/wait owner, NOTE_EXIT до reap, fail-closed EPERM/ESRCH, independent slot release probe, отдельный control writer и bounded data pump. Native synthetic probe подтвердил natural exit, live TERM, ignored TERM→KILL и integer timebase; это не приёмка ещё не написанного guardian/реальной модели.

Регрессионный gate **3121 tests +24 subtests**,76 warnings,exit0,646,18s; main V8/schema/counts unchanged. **Сейчас Sol6.1 High: D03-17C1D1 (clock/locks), затем D2 (guardian/bootstrap), D3 (parent transport/native fault matrix)**, каждый с собственным contract/freeze/red/gate/result/local commit. Source/tests D ещё не реализованы. Один прежний C1D разделён на три (+2), актуальный независимый остаток **30–45 циклов**, без новых продуктовых функций и без работы Ани/Артёма. Windows/физический suspend/real engine/Word остаются честными отдельными gates. Пауза только для согласованного возврата на Sol; никакой push/main migration/runner rewrite.

D1 выполнен на Sol6.1 High: [результат](d03-17c1d1-result.md), acceptance c3b049a и согласованное исправление подготовки f94d897. Checked continuous clock и private owner/inherited slot, без guardian/SQL. Native targeted47 passed; full **3168+24**,74 warnings,649,80s,exit0. Main V8/schema/counts unchanged. Далее **D03-17C1D2 на Sol6.1 High** по отдельному contract/freeze/red; самостоятельный остаток **29–44 цикла**.

D2 начат, но **не завершён**: [точный конфликт/handoff](d03-17c1d2-result.md), contract/acceptance freeze9afce73. Targeted24passed/1failed; full3192passed/1failed+24subtests,74warnings,655,71s,exit1. Native Stop закрывает gate, M выходит74, SIGTERM может вернутьEPERM; actual wait подтверждает cleanup, но signal-error fault latch требует crashed, а frozen обычный Stop ожидает stopped. Не ослаблять test/blanket-ignoreerrno и не возвращать clean result. **Далее Astra6 High: уточнить D2 классификацию signal fault/Stop/exit evidence**, затем Sol завершает тот же цикл. D1 verified code commit2d93304; D2 source WIP остаётся в workspace и не включён в verified code commit. Main V8/counts unchanged, все synthetic processes reaped. Остаток **29–44**, D2 не вычитается.

На Astra6 High конфликт D2 **разобран**: [нормативное дополнение](d03-17c1d2-stop-addendum.md), [результат](d03-17c1d2-stop-design-result.md). Aggregate fault sticky, отдельные signal_error/hard_fault; ordinary Stop+exact wait без hard fault→stopped, без wait нет proof, hard fault не маскируется, clean после Stop/ошибки сигнала запрещён. Уточнена отмена bootstrap; wire/SQL unchanged. Source и frozen contract/tests не редактировались. Регрессия неизменённого WIP: **1failed/3192passed+24**,75warnings,361,74s,exit1 (тот же native Stop); main V8/schema/counts unchanged. **Сейчас Sol6.1 High: завершить D03-17C1D2 по дополнению**, сначала новая additive acceptance/freeze/red, затем source/targeted/native/full gate/result/commit; потом D3. Остаток **29–44**, нового цикла в счётчик не добавлено.

2ноября **D2 завершён** на Sol6.1 High: [итог](d03-17c1d2-finish-result.md), additive freeze67a2656. Guardian/bootstrap/owned wait и Stop supplement, старые tests unchanged. Targeted/native58passed (включая20 повторов Stop); full **3226+24**,75warnings,375,72s,exit0; main V8/schema/counts unchanged. Теперь **D03-17C1D3 на Sol6.1 High**: parent transport/candidate proof по отдельному exact contract/freeze/red. Остаток **28–43 цикла**.

2ноября **D3 завершён** на Sol6.1 High: [итог/handoff C1E](d03-17c1d3-result.md), freezec707da1. Parent transport, независимый atomic control/Stop, composite candidate proof, bounded IO и explicit cleanup без SQL/реальной модели. Targeted/own21passed, native death/backpressure/flood/slot/FD/memory checks; окончательный full **3247+24**,76warnings,401,62s,exit0, main V8/schema/counts unchanged. **Далее Astra6 High: C1E exact Windows Job/HANDLE/pipe ownership/startup design**, затем Sol implementation с честным native Windows gate. Остаток **27–42 цикла**. Mac C1D завершён только в своих synthetic границах, frontend/weights/desktop/full DOCX/лицензия ещё не завершены.

2ноября **C1E Windows design завершён** на Astra6 High: [проект](d03-17c1e-design.md), [первый контракт E1](d03-17c1e1-contract.md), [результат](d03-17c1e-result.md). Выбраны создание G/M сразу в Job, outer Job у S и inner Job у G, inherited file reservation, sleep-counting clock, отдельные Stop/abort events и bounded overlapped pipes с обязательным completion после cancel. Frozen C1A/B/C/D/source/tests unchanged, Windows native gate pending. Full documentation-cycle regression **3247 tests+24 subtests**,78warnings,425,05s,exit0; main V8/schema/counts unchanged.

**Теперь Sol6.1 High: C1E1 clock/owner/slot**, затем C1E2 pipe/event primitives, C1E3 Job/guardian/bootstrap, C1E4 parent driver/fault matrix. Для каждого свой contract/freeze/red/implementation/gates/result/local commit. Доступные portable проверки на Mac не означают native acceptance; можно продолжать независимые части при явной записи pending Windows gate. Самостоятельный остаток **30–45 циклов**: прежняя одна строка C1E раскрыта в четыре (+3), новых функций нет, завершённый design повторно не считается. На этой границе остановиться только для согласованного возврата на Sol. Push/публикация/рабочая миграция/runner edits не выполняются.

**C1E1 available implementation завершён** на Sol6.1 High: [результат](d03-17c1e1-result.md), freeze83d5f5e и user-approved test preparation fix ce47170. Lazy Windows clock/ABI, canonical private root и owner/slot capabilities; targeted93passed/7native skipped. Full **3340passed+24subtests,7skipped,77warnings,371,58s,exit0**, main V8 unchanged. Native Windows gate pending, весь C1E не принят. **Продолжать Sol6.1 High → C1E2** по [готовому контракту](d03-17c1e2-contract.md), отдельные freeze/red/source/gates/result/commit; остаток **29–44**.

**C1E2 available implementation завершён**: [результат](d03-17c1e2-result.md), freezef280f01. Private Windows pipes/events, bounded overlapped lifecycle/strong retention/cancel без false completion. Targeted38passed/3native skipped; full **3378passed+24subtests,10native skipped,75warnings,398,68s,exit0**, main V8 unchanged. **Далее Sol6.1 High → C1E3** Job/guardian/bootstrap, отдельный contract/freeze/red; затем E4. Native Windows pending gate сохраняется, самостоятельный остаток **28–43**.

**На подготовке E3 выявлен проектный вопрос**, не runtime failure: [handoff](d03-17c1e3-preflight.md). JOB_LIST before-execution guarantee не заменяет отдельный proof lifetime/cleanup при смерти caller до возврата CreateProcessW. E3 source/tests ещё не создавались; E1/E2 остаются проверенными, новых циклов в оценку не добавлено. **Сейчас Astra6 High — уточнить E3 startup proof/recovery и exact contract**, затем вернуться на Sol6.1 High. Stop после завершённого E2 только для согласованной смены режима; остаток **28–43**. Windows gate по-прежнему pending, никаких новых Windows гарантий из mocks.

**Проектирование E3 завершено, 2 ноября:** [точный контракт](d03-17c1e3-contract.md). Сохраняются два Job/JOB_LIST; failed create, retained successful create и unknown outcome разделены. Unknown не выдаёт cleanup/повторный анализ; автоматическое восстановление после потери владельца требует durable crash fence в уже запланированном C1F, а не свободного slot/terminal SQL. Holder выдаётся до I/O, strongly retained; заданы ABI, reduced-rights handle handoff, E2 thread ownership и VM-only crash gate. Source/acceptance E3 ещё отсутствуют, старые проверки неизменны. **Теперь Sol6.1 High → D03-17C1E3**, freeze/red/source/targeted/full/result, затем E4 отдельным циклом при достаточности режима. Остаток **28–43**, дизайн уже учтённого этапа повторно не вычитается; native Windows/restart gates остаются открыты.

[Результат E3 design](d03-17c1e3-design-result.md): `bash scripts/check.sh` **3378passed+24subtests,10skipped,77warnings,375,58s,exit0**.445 source/test/contracts/runner files unchanged, read-only runtime snapshots равны, main V8 unchanged. Следующий шаг — реализация E3 на Sol6.1 High, не повторное проектирование preflight.

**E3 available implementation завершён, 2 ноября:** [результат](d03-17c1e3-result.md), freeze d948ca1 и user-approved additive pipe-rights a32c39e. Win64 Job/create holders, private inherited roles, guardian/bootstrap и bounded fixture. Старые tests/SQL/runner unchanged; одна согласованная строка E2 расширяет writer на FILE_READ_ATTRIBUTES без read-data. E1–E3 targeted195passed/26skipped; final full **3442passed+24subtests,26native skipped,74warnings,402,69s,exit0**, main V8/counts unchanged,460code/test hashes equal. Native Windows/VM-crash/suspend gates остаются открыты. **Теперь Astra6 High → E4 exact contract** по [handoff](d03-17c1e4-preflight.md): три thread owners, ACK/cancel/cleanup и candidate composition. Затем Sol6.1 High для реализации E4; E4 source ещё отсутствует. Самостоятельный остаток **27–42**, без нового дробления/ID. Pause только на границе завершённого E3 для согласованной смены режима; без публикации/миграции/настоящего ML.
