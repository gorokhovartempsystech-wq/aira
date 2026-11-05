# Проверка нейтральности стиля таблицы

`ara.docx_analysis.table_styles.read_table_style_catalog(bytes,
source_sha256=...)` возвращает immutable evidence из исходного DOCX. Файл/сеть/БД
не читаются. Это отдельный pure API, не разрешение application передать документ ML.

Каталог `docx-table-styles/neutral-current-v1` сохраняет source SHA и SHA прежнего
StyleContext. Статус ready означает наличие table definitions; каждый стиль имеет
свой neutral/blocked статус. absent означает отсутствие table definitions; blocked —
неразрешённую общую идентичность/styles part/defaults. Неподдержанный unused style
не делает unrelated neutral style неразрешённым. default_table_style сохраняет
выбор по исходному XML даже для blocked default: consumer обязан проверить record.

Neutral означает только отсутствие свойств, влияющих на анализируемый текст, в
закрытой grammar: оформление шрифта/абзаца/таблицы/строки/ячейки. Проверяются все13
conditional regions и вся same-kind basedOn chain. Ни ложное значение vanish, ни
дочерний override не отменяют неопределённость родителя. UI hidden не является
скрытием содержимого; direct/style-row hidden пока не получает такой трактовки.

У neutral record chain содержит исходные style anchors self→parent→root; regions и
metadata сохраняют исходные XML addresses без копирования/перенумерации. Значения
авторских name/aliases/formatting не копируются в proof. Коллекции/IDs/anchors скрыты
в repr. Source-specific canonical SHA позволяет сравнивать detached evidence;
будущий reader должен перестроить его из исходных bytes, а не доверять caller DTO.

До semantic DOM preflight считает весь styles part, включая непрочитанные ветви,
namespace URI, attributes/text/tails. Graph traversal итеративный; отдельные caps
ограничивают chain depth, общее число chain links, issues и manifest bytes. Exact
limits можно только уменьшать. Никакого unbounded asdict при вычислении digest.

Существующие visibility defaults, paragraph/character rules и profile guards не
изменены. Нейтральность table style не означает видимость каждого run: document
и paragraph/character/direct hidden по-прежнему определяются прежним механизмом.
Интеграция в новый table snapshot/map profile, native Word parity, изменения
видимости/границ/сетки, numbering/прочие DOCX parts — следующие отдельные этапы.
Контракт: [D03-17A2b3a3](d03-17a2b3a3-contract.md).
