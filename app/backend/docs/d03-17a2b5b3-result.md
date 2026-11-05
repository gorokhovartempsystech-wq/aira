# D03-17A2b5b3 — saved plain-text controls

5 ноября 2026. Baseline `969ca5a`, frozen contract/acceptance `bd9551c`.
Red **45 failed /0.42s**; первый targeted **45 passed /0.50s**.
Регрессия прежних readers/catalogs/proofs **1163 passed /5.65s**.
Review добавил6 проверок: rich fields/notes сохраняются, nested rich ownership,
empty plain row refuses, malformed cellDel не разрешает пропустить payload,
разные current formatting bases не нормализуются, closed field внутри plain refuses.
Review targeted **51 passed /0.53s**. Подготовка frozen tests не менялась;
AST всех зафиксированных test functions совпал.

Новый профиль читает unbound plain controls с доказуемым единым current formatting
и настоящим logical ownership. Сохранённые soft breaks остаются независимо от multiLine.
Current hidden runs участвуют в proof; historical rPrChange и proven deleted content
не подменяют текущие свойства. Atomic refusal предшествует сборке output.

Три private hooks: extended control property/code с прежним default refusal,
grammar_type с прежним default и извлечённый private C2C builder с явным reader/profile.
Старые public profiles/сигнатуры сохраняются. Ни редактор, ни схема, ни приложение,
ни ML-контракт не расширяются этим циклом. Original bytes/addresses неизменны.

Full `bash scripts/check.sh`: **5919 passed, 45 skipped, 82 warnings,
24 subtests passed /800.90s**, exit0; Ruff/format832 files. Все897 frozen hashes
совпали; все886 прежних контрольных файлов вне трёх hooks неизменны. Readonly main
V8 `0008_docx_edit_drafts`: schema/revision/counts совпали с C2C, без чтения строк.
Выборочный локальный commit, без публикации.

Далее D03-17A2b5d1: inline PNG/JPEG accounting, boundaries между соседними текстовыми
фрагментами и original-source mapping. Application admission, другие сложные структуры,
editor/export и native Word/Windows остаются отдельной работой. UI/ML/release gates
не объявляются закрытыми.
