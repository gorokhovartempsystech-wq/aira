# D03-17A2b4a2 — чтение колонтитулов и обратные адреса

4 ноября2026. Baseline d028fb3; freeze0521c47. Red37 failed/0.37s, initial37 passed/0.36s.
Review добавил5 случаев: oldpPr с fake tables/references; hiddenrow/nonemptycontinuation
вheader; общиеcharacterstyles; comments policy/sourcehash. Combined400 passed/1.28s,
Ruff753 files green. Ни одной setup correction; frozenmain/contract и edgeprefix unchanged.
808 finalhashes;793 previous unchanged, только3 заранее согласованных private hooks.

Новый fixedprofile final-visible-section-stories-v1 читает main, затем уникальные
потенциальныеheader/footer в canonicalpartorder; same original table/visibility rules,
своиrelationships и sourceanchors, одна SectionCatalog/StyleContext и cachedtableproof.
Globalpreflight включает inactive/orphanstoryXML до semanticDOM; ошибка любойactivepart
илинепрочитаннаядругаячасть оставляет весьновыйsnapshot безтекста/fragments. Orphan
exclusion толькопослеполного reference/content proof. Batch mapping source-backed,
одинrebuildвключаяemptybatch. Исходныеbytesнепереписываются.

`bash scripts/check.sh`: exit 0, **5429 passed, 45 skipped, 79 warnings,
24 subtests passed / 799.35s**. Ruff и форматирование: 753 файла. Все 808 финальных
хешей совпадают; из прежних 796 изменены только три разрешённых private hooks.
Readonly snapshot основной БД совпадает с a1: V8, схема, revision и счётчики
сохранены, содержимое строк не читалось. Журнал и снимки — в ignored `.runtime/`
под префиксом `d03-17a2b4a2-`.

Native Word/Windows, сложные table/section/paragraph revisions, notes/fields/MC/media,
full DOCX и application admission не объявлены готовыми. Следующий отдельный цикл —
D03-17A2b4b1, каталог исходных определений сносок и концевых примечаний.
