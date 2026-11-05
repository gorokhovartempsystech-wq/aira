# D03-17A2b4a1 — завершён

4 ноября2026. Baseline bafad48; freeze2257cab, только переносы двух строк fixture
в60ced14 (Python AST доказанно тот же). Red49 failed/0.41s; initial49 passed/0.18s.
Review добавил6 случаев: inherited inactivefirst, aggregateXMLcap, чужой relationship
owner, foreign/external/ambiguous settings. В новой unfrozen review fixture исправлена
подготовка secondsettings: XML namespace prefix мешал строковому replace; теперь
добавляется реальный Override через ET, все assertions сохранены. Main frozen tests
и contract unchanged после60ced14, frozenedgeprefix2257cab untouched.
Combined sections/table readers **294 passed/0.97s**, Ruff742 files green.
`bash scripts/check.sh`: **exit0**, **5387 passed,45 skipped,80 warnings,
24 subtests passed /800.26s**, Ruff742 files green.796 finalhashes и все787 previous
совпадают. Readonly schema/counts/revision mainV8 **0008_docx_edit_drafts** unchanged;
ara_test empty, временных ara_check_* БД нет. Секреты/содержимое документов не читались.
Evidence `.runtime/d03-17a2b4a1-{red,targeted,review,regression,full}.log`, `-hashes.json`,
`-runtime.json`. Review log сохраняет исходную ошибку новой fixture; финальная
проверка исправленной подготовки входит в regression и полный прогон.

Новый pure catalog сохраняет current sections/references/history/originanchors и
потенциальные уникальные stories. Не читает текст колонтитулов, не утверждает page
layout/visibility/admission. Native Word/Windows/fullDOCX остаются открыты.

Далее **D03-17A2b4a2**: main/header/footer text + source-backed mapping, одинаковые
правила таблиц/styles/hidden text в каждой части. Astra, автономное продолжение.
[Контракт](d03-17a2b4a1-contract.md), [использование](docx-section-references.md).
