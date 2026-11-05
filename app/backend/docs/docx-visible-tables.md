# Итоговый текст таблиц с адресами ячеек

`ara.docx_analysis.visible_tables` предоставляет `build_table_snapshot`,
`map_table_spans`, `map_table_span` и прежние exact Visible* DTO/limits/errors.
Profile `docx-analysis/final-visible-tables-v1` отдельный от visible_main/moves;
old/new mapper взаимно отвергают snapshots, даже для одинакового plain текста.

Body, строки, ячейки и nested blocks читаются в исходном logical order. Story anchor
остаётся main body, flow anchor у cell paragraph — его физическая ячейка. Fragment
ID содержит этот flow. Identical quotes в разных cells имеют разные адреса;
mapping проверяет exact source/snapshot/quote, не ищет похожую фразу в документе.
Paragraph fragments разделены двумя synthetic LF; эти разделители не source atoms.
Не склеивать source slices через hidden/deleted content или между ячейками.

Horizontal span не повторяет содержимое. Vertical origin читается один раз, а
continuation пока разрешён только с canonicalempty p blocks: иначе явный отказ,
содержимое не отбрасывается. Nested tables имеют независимые flows. Прежние ins/del,
hidden runs, comments и hyperlinks работают внутри cell paragraphs. Main inline
moves вне tables поддержаны; moves в cells требуют расширения structural profile.

Direct formatting учитывается по closed whitelist. BiDiVisual сохраняет logical
XML order, hideMark не удаляет cell text. Direct hidden row true, default/explicit
table styles, floating/conditional/unknown properties остаются blocked до своих
readers. Incomplete coverage запрещает выдавать успешную полную проверку. Catalog
ready/indexed и наличия текста недостаточно для полного анализа всего DOCX.

Build и batch mapping заново читают один table catalog, один move catalog и один
style context из exact bytes. Caller не передаёт доверенный catalog/profile.
XML/batch/manifest limits действуют на весь вход, включая excluded branches.
Никаких FS/env/network/SQL/Word вызовов. Исходный файл/revisions не меняются;
source-bound spans — адреса для отображения, не разрешение редактировать opaque parts.

Пример (data — исходные DOCX bytes):
```python
from hashlib import sha256
from uuid import UUID
from ara.docx_analysis.visible_tables import build_table_snapshot, map_table_spans, VisibleSpanRequest

s = build_table_snapshot(data, document_id=UUID(int=1), storage_revision=1,
                         source_sha256=sha256(data).hexdigest())
if s.complete and s.fragments:
    f = s.fragments[0]
    mapped = map_table_spans(data, s,
        requests=(VisibleSpanRequest(f.fragment_id, 0, len(f.text), f.text),))
```

Это pure промежуточный профиль. Application/ML admission ещё прежний; assembler
должен дополнительно передавать table row/column context из того же pinned catalog.
Native Word/layout parity, сложные table styles/revisions, numbering/settings/stories
и editing сложных структур остаются отдельными задачами, не отменены.
