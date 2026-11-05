# D03-17A2b5c2c — visible selected stories with original-source mapping

5 ноября 2026. Baseline `c9c71ae`, frozen contract/acceptance `7babcc2`.
Red **35 failed /0.44s**; первый targeted **35 passed /0.54s**.
Регрессия прежних readers/catalogs/proofs **1112 passed /5.31s**.
Review добавил6 проверок: gridless vertical merge, repeated/hidden/deleted note refs,
part-wide moves в selected/discarded definitions, hidden unsupported content и
projection text-ownership refusal. При добавлении parametrized review-теста добавлен
недостающий import pytest; проверки/подготовка прежних frozen функций не менялись.
Review targeted **41 passed /0.54s**; AST всех frozen test functions прежний.

Новый профиль строит C2B contexts один раз и использует тот же view во всех story
readers, table/history/revision/move proofs и lookup сносок. Logical ancestry определяет
владение, original ViewNode anchors — фактические адреса. Early table history/deletion
proofs больше не выводят адрес выбранного ребёнка из индекса логического дерева.
MC прозрачен для полей; прежние control/table/story barriers сохраняются.

Shared notes builder получает private provider, его default path сохраняется.
Shape получает отдельный fixed style-profile parameter без изменения глобальных enum.
Новый public API не принимает prebuilt capability; mapping заново строит результат один
раз на batch, включая пустой. Early failure не подменяется absent/ready контекстом;
любая неподтверждённая полнота атомарно очищает текст и references. Decision coverage
связана с исходными anchors и включена в общий budget.

Все 870 прежних контрольных файлов вне11 разрешённых private hooks совпали.
Full `bash scripts/check.sh`: **5868 passed, 45 skipped, 81 warnings,
24 subtests passed /801.56s**, exit0; Ruff/format825 files. Все889 frozen hashes
совпали после полного прогона. Readonly основная V8 `0008_docx_edit_drafts`:
schema/revision/counts совпали с C2B; содержимое строк не читалось.
Выборочный локальный commit, без публикации.

Далее D03-17A2b5b3: сохранённые unbound plain-text controls с доказуемым единым
текущим форматированием и сохранением уже существующих soft breaks. Product admission,
сложный editor/export, native Word/Windows и внешние UI/ML/release gates остаются.
