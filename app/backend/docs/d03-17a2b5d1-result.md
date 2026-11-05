# D03-17A2b5d1 — inline raster accounting and text boundaries

5 ноября 2026. Baseline `d7c1eaf`, frozen contract/acceptance `4bdde88`.
Red **54 failed /0.55s**. Первый targeted **52 passed, 2 failed /0.57s**.
Две ошибки подготовки новых тестов исправлены в `691afee` по разрешению контракта:
SVG MIME получил valid synthetic SVG вместо PNG bytes; отрицательная header fixture
больше не содержит dangling Foot relationship. Все frozen assertions AST неизменны.
Corrected targeted **54 passed /0.55s**; изменений source для этих отказов не требовалось.

Регрессия visible/compatibility/table/note/section readers **958 passed /5.02s**.
Review добавил9 случаев: field-code/cached pictures, discarded/unknown active content,
aggregate binary budget, JPEG metadata, four malformed/unsupported JPEG frames/scans,
Strict/Transitional crop/transform/locks. Targeted **63 passed /0.62s**.

Closed inline DrawingML grammar проверяет ownership и embedded PNG/JPEG target;
bounded raster framing не является полным pixel decoder или native render proof.
Видимая картинка разделяет literal fragments, hidden object/run не создаёт boundary.
Original source addresses, note links, field behavior и atomic failure сохраняются.
Unused raster exclusions возможны только после успешного active reference closure.

Три private hooks в notes builder/output/coverage сохраняют runtime defaults.
Новый профиль не меняет C1 capability set, старые public profiles, schema или API.
До полного прогона все894 старых файла вне hooks совпали; зафиксированы908 hashes.

Full `bash scripts/check.sh`: **5982 passed, 45 skipped, 82 warnings,
24 subtests passed /800.34s**, exit0; Ruff/format842 files. Все908 frozen hashes
совпали после прогона, 894 прежних вне трёх hooks неизменны. Readonly mainV8
`0008_docx_edit_drafts`: schema/revision/counts совпали с B3, без чтения строк.
Выборочный локальный commit, без публикации.

Далее D03-17A2b5d2: floating raster anchors, metadata и logical text continuity.
После него — source reading для defaults/numbering собственного шаблона AIRA.
Read-only synthetic probe показал unsupported_defaults для body/heading/bullet/numbered:
создание DOCX само по себе не доказывает допуск его к новой проверке. App/codec/worker
по-прежнему явно требуют отдельной интеграции новых profiles. Textboxes, другие
сложные структуры, editor/export, native Word/Windows и внешние UI/ML/release gates
не объявляются завершёнными.
