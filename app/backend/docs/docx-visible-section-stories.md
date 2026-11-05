# Текст основного документа и колонтитулов

`ara.docx_analysis.visible_stories` предоставляет `build_story_snapshot` и
`map_story_spans/span` с fixed profile `docx-analysis/final-visible-section-stories-v1`.
Используются прежние Visible DTO и лимиты; main_part всегда обозначает настоящий
основной XML part. Fragment.story_anchor относится к body основного документа или
реальному корню hdr/ftr; flow — к этому контейнеру либо конкретной исходной ячейке.

Порядок анализа: main, затем уникальные потенциальные header/footer parts по
каноническому имени. Выбор определений и наследование выполняет fresh SectionCatalog.
Это не раскладка страниц: колонтитул читается один раз, даже когда его используют
несколько разделов или вариантов. У каждой части собственные relationships; совпадение
r:id в основном тексте не разрешает ссылку колонтитула. Все offsets — code points.

Каждая часть проходит те же правила visible runs, current table history/revisions,
neutral table styles и logical grid, что основной текст. Заголовки, списки и прочие
формы читаются только в пределах уже поддержанного закрытого grammar. Поддержанные
section properties учитываются как metadata; old section/pPr histories не активируют
исторические таблицы или references. Исходный ZIP/XML не переписывается и не оборачивается
в фиктивный document/body ради повторного использования main reader.

Сначала весь main/styles/settings/header/footer XML, включая неиспользуемые parts,
проходит общий preflight. Technical table/move caps также суммируются по story parts.
После этого строятся один SectionCatalog, один StyleContext и при необходимости один
общий proof нейтральных table styles. Original trees дают private proofs текущих
таблиц/moves; публичный вызов не принимает готовый catalog как доверенный источник.

Новый профиль возвращает пустые fragments/analysis_text/paragraphs/runs, если активная
часть не прочитана, reference/style proof не разрешён или остаются другие unread parts.
Причины сохраняются в coverage. Невостребованные header/footer parts получают excluded
только после успешного разбора всех активных ветвей; до него usage остаётся unproven.
Word comments по согласованной политике сохраняются без анализа.

Batch mapping проверяет точную форму DTO, один раз заново строит proof из исходных
bytes (также для пустого batch), сравнивает snapshot и возвращает original source
slices. Одни и те же слова в body/header/footer имеют разные fragment IDs и адреса.
Изменённый DOCX, подмена story/coverage/style или пересчитанный чужой digest не разрешают
подсветку. Synthetic два LF между fragments не получают ложных исходных адресов.

Это opt-in reader, ещё не application admission. Notes, поля, SDT/MC, media, сложные
paragraph/table/section revisions, printerSettings и прочие неподдержанные parts
остаются явными gates. Native Word/Windows и полная обработка DOCX не подтверждены
одним этим циклом. [Контракт](d03-17a2b4a2-contract.md),
[результат](d03-17a2b4a2-result.md).
