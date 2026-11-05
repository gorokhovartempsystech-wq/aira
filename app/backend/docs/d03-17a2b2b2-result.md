# D03-17A2b2b2 — итоговый inline move reader и mapping

4 ноября2026, frozen763d0a8. [Контракт](d03-17a2b2b2-contract.md),
[guide](docx-visible-moves.md). Новый pure opt-in profile читает destination,
исключает source wrapper, сохраняет обычный текст внутри ranges и original XML paths.
Наследуются effective visibility/styles, ins/del/comments/hyperlink правила.
Batch mapping строит один authoritative snapshot/catalog и проверяет полный DTO.
Old/new profiles и fragment hashes различны, взаимное смешивание отвергается.

Independent red29failed0.32s (namespace отсутствовал); initial targeted29passed0.22s.
Review добавил namespace-before-DOM случай:1failed10deselected0.08s. Исправлен порядок:
catalog preparation после aggregate preflight, до style/reader DOM. Только одно
review addition к own edge tests; frozen main acceptance/contract не изменены.
Пять разрешённых shared files выделяют fixed-profile private pipeline; старые public
API/guards/профили/ожидаемые хеши и все прежние тесты сохранены.
Combined new/old visible+move catalog regression:136passed0.91s.

Required `bash scripts/check.sh`: **4991passed,45skipped,79warnings,24subtests passed**,
790.04s,exit0. Ruff/format672files green. Final718 hashes совпадают;707 предыдущих
unchanged, ровно5 разрешённых shared source changes. Main V8/schema/counts совпадают
с b2b1; ara_test empty и temporary ara_check databases0, без чтения содержимого строк.
Evidence: `.runtime/d03-17a2b2b2-{red,targeted,review-red,regression,full}.log`,
`d03-17a2b2b2-hashes.json`, `d03-17a2b2b2-runtime.json`.

Native Word parity не подтверждён (plain synthetic control b2b1 timeout); source
не менялся и его own document закрыт. Нового API/ML storage/application admission,
правки исходных move structures, table/story readers и paragraph-join semantics
этот цикл не добавляет. Новая complete coverage относится только к pure profile,
не доказывает real model/UI/Word rendering/готовность установщика.

Следующий independent цикл **D03-17A2b3a1** — physical direct-current table catalog:
grid spans, vertical merge origins, nested cells/ordered blocks. Затем отдельный
visible table-flow reader. Native boundary work остаётся в очереди; не снимаем gate.
На выбранной Astra продолжаем автономно по текущей команде пользователя.
