# Pure чтение итоговых inline-перемещений Word

`ara.docx_analysis.visible_moves` — отдельный opt-in профиль
`docx-analysis/final-visible-main-moves-v1`. Он читает только поддержанную b2b1
main/inline структуру: source исключён, destination прочитан на новом месте,
ordinary runs внутри ranges остаются. Исходные DOCX bytes и revisions неизменны.

```python
from hashlib import sha256
from uuid import UUID
from ara.docx_analysis.visible_moves import (
    build_move_snapshot, map_move_spans, VisibleSpanRequest,
)

snapshot = build_move_snapshot(
    data, document_id=UUID(int=1), storage_revision=1,
    source_sha256=sha256(data).hexdigest(),
)
# incomplete coverage запрещает выдавать успешный полный анализ.
if snapshot.complete and snapshot.fragments:
    f = snapshot.fragments[0]
    mapped = map_move_spans(
        data, snapshot,
        requests=(VisibleSpanRequest(f.fragment_id, 0, len(f.text), f.text),),
    )
```

Caller не передаёт catalog/profile/reader. Build сам проверяет exact bytes/SHA,
aggregate XML limits, structural move catalog и styles; mapping повторяет один
source-backed build для всего batch, сравнивает полный DTO и возвращает точные
original XML slices. Между slices могут находиться excluded source/hidden/deleted
узлы; нельзя подсвечивать один непрерывный range от первого до последнего.
SourceAnchor — исходный ZIP part, SHA, element-only child path; offsets codepoints.
Никакого исполнения полей, внешних ссылок, сети, Word, SQL или чтения окружения.

Все Visible* DTO/limits/errors совместно используются с visible_main, но profile
и fragment hashes различны. Старый mapper отвергает новый profile, новый отвергает
старый, включая empty batches и пересчитанный digest. Public v1 поведение неизменно.
Это не новый HTTP/ML формат; приложение продолжает использовать прежний admission.

Catalog blocked → main fragments/contexts пусты, fixed move_catalog_blocked.
Другие unknown parts продолжают блокировать complete. Source wrapper содержимое
исключено как revision branch, но вложенные move tags проверяются глобально.
Styles/hidden destination, ins/del/comments/hyperlinks наследуют прежние правила.
Таблицы, cross-paragraph ranges, moved/deleted/hidden paragraph boundaries, fields,
SDT и другие stories пока отдельные readers. Не редактировать moves через mapping.

Resource bounds включают excluded XML; move namespace/range/member preflight
выполняется до любого reader semantic DOM. Native Word final-view parity остаётся
незакрытым gate: простой synthetic control4ноября снова timed out. Complete этого
pure profile не доказывает native rendering, интерфейс, реальный ML или готовность
установщика. Подключение reader к общему assembler/API — отдельный контракт.
