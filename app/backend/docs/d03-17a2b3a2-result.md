# D03-17A2b3a2 — итоговые потоки таблиц: результат

4 ноября 2026. Frozen acceptance **7742466**. Реализован отдельный pure profile
`docx-analysis/final-visible-tables-v1`: текст простых таблиц в порядке исходных
строк/ячеек, вложенные таблицы, точные cell flow anchors и обратная привязка диапазонов.
Горизонтальное объединение и вертикальный origin не дублируют текст. Непустые
continuations, неоднозначные стили/правки/границы остаются явно blocked. Исходник
не изменяется. Это библиотечный opt-in reader, не application/ML admission.

Проверки:
- Independent red: **37 failed, 0.37s**, новый namespace отсутствовал.
- Initial targeted: **37 passed, 0.24s**.
- Review добавил две проверки: hidden paragraph boundary/unknown continuation и
  default table style в документе без таблиц. Frozen main acceptance/contract и
  все старые тесты неизменны; исправлений подготовки тестов не потребовалось.
- Combined new/old catalogs/readers: **177 passed, 1.15s** после окончательного
  review; устранён reader↔properties reference cycle, временный DOM не удерживается.
- Required `bash scripts/check.sh`: **5081 passed, 45 skipped, 77 warnings,
  24 subtests passed, 796.65s, exit 0**. Ruff/format: **686 files**, green.
- Все **734** финальных hash совпали; **724** прежних файла неизменны, ровно три
  разрешённых private shared changes: `_build.py`, `_canonical.py`, `_reader.py`
  в visible_main. Старые public profiles/API/default IDs и guards сохранены.
- Readonly main DB snapshot совпадает с b3a1: схема/ревизия/числа записей прежние,
  **V8**, ara_test пустая, временных check DB не осталось. Содержимое строк не читалось.

Локальные evidence: `.runtime/d03-17a2b3a2-{red,targeted,regression-final,full}.log`,
`-hashes.json`, `-runtime.json`. Справочник: [reader/mapping](docx-visible-tables.md).
Native Word parity, остальные DOCX структуры, frontend Ани и настоящий ML остаются
отдельными gates. Никакой публикации, рабочей миграции или обращения к архиву.
Следующий самостоятельный цикл **D03-17A2b3a3** — доказательство нейтральности
табличных стилей; интеграция отдельным versioned reader после его проверки.
