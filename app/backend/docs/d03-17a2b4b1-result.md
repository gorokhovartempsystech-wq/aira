# D03-17A2b4b1 — каталог исходных определений сносок

4 ноября 2026. Baseline `3e39d61`, freeze `49fe538`. Red: 32 failed / 0.29s.
Initial targeted: 32 passed / 0.14s. Review: ещё 6 случаев — смешанные strict/transitional
ссылки одного вида, malformed unlinked part, три неоднозначных ID и совпадение ID
между обычной и служебной сноской. Regression: 149 passed / 0.64s. Ruff/format:
760 файлов. Setup corrections не потребовались, frozen tests/contract unchanged;
edge содержит только добавленные review cases. 816 final hashes, все 808 прежних
совпадают. Ни один прежний source или test не изменён.

Каталог связывает точные main relationships с оригинальными note parts, различает
четыре типа по w:type, нормализует ID и проверяет уникальность в каждой части.
Все candidate XML проходят общие лимиты до DOM, включая unbound/special/opaque
ветви. Неподдержанная структура определения блокирует весь каталог. DTO/digest
содержат только bounded metadata и оригинальные SourceAnchor, без текста примечаний.

`bash scripts/check.sh`: exit 0, **5467 passed, 45 skipped, 80 warnings,
24 subtests passed / 801.58s**. Ruff/format — 760 файлов. Все 816 финальных хешей
и 808 прежних совпадают. Readonly main V8 snapshot совпадает с a2: схема, revision
и счётчики не изменились, содержимое строк не читалось. Логи и снимки в ignored
`.runtime/` под префиксом `d03-17a2b4b1-`.

Этот цикл не читает видимый текст, не разрешает исключать orphan notes и не подключает
application analysis/export.
Следующий цикл — retained references, текст и mapping сносок; native Word/Windows
и прочие DOCX структуры остаются отдельными gates.
