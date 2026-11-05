# D03-17A2b3a1 — физическая сетка таблиц

4 ноября2026, frozen145f865. [Контракт](d03-17a2b3a1-contract.md),
[guide](docx-table-catalog.md). Pure direct-current catalog готов: source-pinned
таблицы/строки/ячейки, интервалы колонок, vertical merge origins и ordered cell
blocks. Continuation сохраняет собственные blocks; никакого копирования/удаления
текста. Nested tables имеют свои grid scopes/parent cell anchors.

Red48failed0.40s (namespace отсутствовал), initial48passed0.15s. Review добавил три
проверки: late-table failure не выдаёт valid prefix; fake nested body не разрешает
context; missing limit field/exact canonical size. Setup corrections не требовались,
frozen acceptance/contract и все old tests неизменны. Combined projection/visible/
new catalog regression **152passed1.03s**.

Required `bash scripts/check.sh`: **5042passed,45skipped,78warnings,24subtests passed**,
798.60s,exit0. Ruff/format680files green. Final727 hashes совпадают; все718 предыдущих
unchanged. Readonly main snapshot: V8/schema/counts совпадают с b2b2, ara_test empty,
временных ara_check databases0; содержимое строк не читалось.
Evidence: `.runtime/d03-17a2b3a1-{red,targeted,regression,full}.log`,
`d03-17a2b3a1-hashes.json`, `d03-17a2b3a1-runtime.json`.

Catalog main-only indexed/absent/blocked, без complete/visible claims. Styles/hidden
properties/paragraph text не интерпретируются; старые readers всё ещё блокируют
таблицы. Missing/implicit/conflicting grids остаются unresolved, unknown contexts,
legacy hMerge/revisions blocked; DOCX не меняется. Native Word parity/application
admission, редактирование сложных таблиц и полноценная DOCX матрица ещё отдельно.

Следующий **D03-17A2b3a2** — итоговый table-flow reader с cell source mapping,
continuation checks и guard на unresolved table styles/visibility. Новые границы
готовятся отдельно, старые guards не снимаются. Продолжаем на выбранной Astra.
