# D03-17A2b3c1 — завершён

4 ноября2026. Freeze **0cf23ab**, baseline **7f3b97b**. Регулярные retained rows
дают logical grid при отсутствующем/пустом/коротком current tblGrid; original
columns/anchors хранятся отдельно от column_count, никаких выдуманных XML узлов.
Новый fixed visible profile читает и адресует тот же исходник с учётом нейтральных
styles, current histories и retained revisions. Ровно один согласованный private
hook grid_event в прежнем reader; поведение старых profiles сохранено.

Red **38 failed /0.32s**, initial targeted **38 passed /0.29s**. Review добавил две
проверки: grid+history/revisions/neutral style вместе; независимые nested grids/flows.
Combined old/new catalogs/readers **456 passed /2.50s**. Setup corrections не нужны.

`bash scripts/check.sh`: **exit0**, Ruff/format734 files green;
**5332 passed,45 skipped,79 warnings,24 subtests passed /801.25s**.
Frozen contract и две main acceptance не менялись;787 final hashes совпадают,
775 previous files unchanged, единственное old изменение — разрешённый hook.
Read-only main PostgreSQL: schema/counts/revision **V8 0008_docx_edit_drafts**
совпадают с baseline, ara_test пустая, временных ara_check_* БД нет.
Evidence `.runtime/d03-17a2b3c1-{red,targeted,regression,full}.log`,
`-hashes.json`, `-runtime.json`; содержимое документов/секреты не читалось.

Это opt-in source reader, не расширение application admission. Неравные row totals,
nonzero fallback gaps, сложные row/merge/boundaries остаются blocked. Native Word,
весь DOCX и production release не объявлены готовыми;45 skips — прежние native gates.
Состояние Word не изменилось, тайм-аут native QA без новых оснований не повторялся.
Далее независимый **D03-17A2b4a1**: current sections/header/footer reference catalog.
Astra, автономное продолжение без смены режима. [Контракт](d03-17a2b3c1-contract.md),
[использование](docx-table-grid-derivation.md).
