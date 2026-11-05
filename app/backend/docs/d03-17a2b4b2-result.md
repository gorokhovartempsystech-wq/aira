# D03-17A2b4b2 — видимые ссылки, текст сносок и mapping

4 ноября 2026. Baseline b1 `11b79da`, freeze `c22ffbe`. Red 56 failed / 0.60s.
Первый прогон: 55 passed, 1 failed / 0.47s. Причина — новый тест объявил часть
footer, но helper по умолчанию создал hdr. Исправлена только подготовка этой части:
добавлен аргумент "footer", все assertions сохранены (`1778e3a`). Это документированная
setup correction, прямо разрешённая контрактом b2; старые тесты не менялись.
После исправления 56 passed / 0.46s.

Review добавил 5 случаев: ссылка в удалённой ячейке, скрытый generated self label,
две неоднозначности move starts между примечаниями одного part и отклонение неверной
формы NoteReference до rebuild. Регрессия readers/catalogs: **438 passed / 2.55s**.
Ruff/format: 774 файла. 831 final hashes; из 816 прежних 813 unchanged, изменены только
три разрешённых файла private hooks (root paths/extended run). Frozen contract и mapping
тесты неизменны, reading test совпадает с 1778e3a, edge содержит только review additions.

Новый NoteSnapshot читает main/section stories и востребованные footnotes/endnotes,
сохраняя оригинальные адреса note subtrees и связи с местом ссылки. Generated markers
не подменяются цифрами и не склеивают соседний текст: source-backed segments и nullable
ссылки на ближайшие fragments сохраняются в manifest. Скрытые/удалённые ссылки не
активируют примечания. Таблицы/стили/история/правки используют прежние правила. Reader
tree каждой используемой note part строится один раз, свежие catalogs и StyleContext
проверяются один раз на batch; table style proof общий. Повторная ссылка не дублирует
текст сноски. Part-wide move identity scan также проверяет unused definitions.

Общий raw preflight включает orphan/special/hidden ветви до DOM. При ошибке активного
содержимого либо unread part весь текст/fragments/references пусты; orphan exclusion
не выдаётся без полного proof. Batch map сравнивает свежий source-derived snapshot,
включая связи, и сохраняет code-point offsets. Исходник не меняется.

`bash scripts/check.sh`: exit 0, **5528 passed, 45 skipped, 78 warnings,
24 subtests passed / 798.24s**. Ruff/format — 774 файла; все 831 финальных хеша
совпадают. Readonly main V8 snapshot совпадает с b1: схема, revision и счётчики
сохранены, содержимое строк не читалось. Логи, хеши и снимки — в ignored `.runtime/`
под префиксом `d03-17a2b4b2-`.

Custom marks, header/nested note references,
сложные paragraph/section/table revisions, fields/MC/media/прочие DOCX gates, native
Word/Windows и application admission остаются отдельной работой. Этот цикл не означает
готовность редактора или полной обработки DOCX. Далее — D03-17A2b5a1, сохранённые
результаты simple/complex fields и source-backed mapping, отдельный контракт до реализации.
