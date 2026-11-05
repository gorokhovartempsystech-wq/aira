# D03-17E4A — консервативное сопоставление замечаний

3 ноября 2026. Реализован [контракт pure mapper](d03-17e4a-contract.md): оба B2
результата проверяются заново, exact-source ключи E1 сохранены, cross-source
correspondence требует уникального полного текста, дерева paragraph, контекста,
соседей и отсутствия пересечений порядка. Все primary/related slices сравниваются
в относительных адресах с исходными Unicode offsets. Новая severity/правило/
модель/related evidence не наследует hide. Повреждённые records отвергаются целиком.

Перенос через вставку/правку далеко от неизменённого фрагмента проверен.
Повторы, split/join, перестановка групп, изменения соседей/heading/стилей/section,
скрытого текста или evidence не переносятся. Ключи confidence/upstream ID/suggestion
не становятся семантической идентичностью. Нет файлового/сетевого/SQL I/O.

Это вычисление соответствий, ещё не persistent integration. Поддержан только
проверенный текущим B2 main-body profile; tables/stories не добавлены. Любое
изменение предыдущего paragraph с pPr консервативно блокирует перенос далее;
это включает обычный форматированный текст, поэтому часть безопасных совпадений
может оставаться видимой. Не называем алгоритм доказательством смысловой
эквивалентности после произвольных внешних перестановок.

## Проверки

Freeze b1024da:42 independent cases; red42failed1.85s, targeted42passed4.03s.
59659fd добавляет3 проверки всех сторон inversion/whitespace/isolated execution,
первоначальные functions/assertions AST preserved. E4A/E1/B2 regression
**127passed5.77s**. Изменены только четыре новых source files.

`bash scripts/check.sh`: **4019passed,41skipped,24subtests,76warnings**,
exit0,565.61s. Ruff/format green;544 gate hashes и все539 предыдущих files unchanged.
Main `0008_docx_edit_drafts`, schema/counts unchanged, ara_test пустая, временных
БД0. Артефакты `.runtime/d03-17e4a-{red,targeted,regression,full}.log`,
`d03-17e4a-hashes.json`, `d03-17e4a-runtime.json`.

Далее E4B scoped resolution активных origin references, E4C explicit hide/unhide
и API integration. Ориентир оставшейся самостоятельной очереди **19–34 цикла**;
границы крупных reader/desktop задач ещё уточняются. Пакета модели нет, продолжаем
независимо. Frontend Ани, реальные ML/Word/Windows release gates остаются внешними.
Выбранная Astra достаточна, остановка для смены режима не требуется.
