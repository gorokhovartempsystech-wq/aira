# D03-17A2b5d2 — floating raster anchors

5 ноября 2026. Baseline `68eeecf`, frozen contract/acceptance `8432c04`.
Red **50 failed /0.49s**; первый targeted **50 passed /0.59s**.
Регрессия visible/compatibility/table/note/section readers **1017 passed /5.57s**.
Review добавил4 проверки: hidden flag не обходит foreground-overlay gate,
optional simplePos/wrap effects, wrong namespace/non-XML whitespace и early blocked
context сохраняет новый profile. Targeted **54 passed /0.63s**.
Все frozen functions AST прежние; test preparation corrections не понадобились.

Floating raster anchor не создаёт inline glyph/разрыв. Closed metadata proof охватывает
positions/flags/wrap geometry, затем прежний picture/raster relationship proof. Inline
boundaries, hidden runs, field ordering, notes и original source slices сохраняются.
Foreground wrapNone остаётся явным gate; физическое перекрытие текста не угадывается.

Два private hooks: извлечённый fixed-reader/profile builder и общий graphic proof.
Old public APIs/defaults/profiles/capabilities неизменны. До полного прогона все906
прежних файлов вне hooks совпали; зафиксированы915 hashes.

Полный `bash scripts/check.sh`: **6036 passed, 45 skipped, 82 warnings, 24 subtests passed /802.12s**, exit0; Ruff848 files. Post-gate все915 hashes совпали,906 прежних файлов вне hooks неизменны. Readonly mainV8: схема, revision и количества записей совпали с D1. Цикл завершён; application admission и native visual gates остаются отдельными.
