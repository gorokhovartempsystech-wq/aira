# Сохранённый результат полей Word

`ara.docx_analysis.visible_fields` предоставляет build_field_snapshot и
map_field_spans/span с профилем `docx-analysis/final-visible-field-results-v1`.
Используется NoteSnapshot: прежние исходные адреса, fragments и связи со сносками
сохраняются. Старые публичные профили и их поведение не изменены.

Reader читает stored result, не выполняет инструкцию поля и не обновляет оглавление,
PAGE, LINK, DDE или внешние источники. У fldSimple результат находится внутри wrapper;
у complex field область code отделяется от result маркерами begin/separate/end.
Вложенные поля разрешены, но результат вложенного поля внутри внешнего code не становится
требованием. instrText за пределами complex code region читается как обычный текст с
адресом своего настоящего XML-узла. Empty simple и закрытый code-only field не создают
искусственных символов.

Границы полей обрабатываются до effective visibility: скрытый marker сохраняет
структурную роль, а скрытый текст результата исключается. Deleted/history/moveFrom
ветви не меняют текущий стек. Поле может продолжаться в следующем абзаце того же body
или той же ячейки. Переход через другую ячейку, вложенную таблицу, границу раздела,
другую story либо пересечение simple wrapper остаются блокирующими. Неоднозначный
или незакрытый field не восстанавливается по догадке. True dirty означает явный gate
invalidated_field_result; locked не даёт права очистить флаг или пересчитать значение.

Все XML branches уже проходят общие лимиты; дополнительный raw field count идёт до
semantic DOM, включая unused/excluded части. Активный стек ограничен по глубине.
Private планы используют реальные runs и source anchors, не добавляют XML-узлы и не
сохраняются в публичных DTO. Ошибка активного поля оставляет весь новый snapshot без
текста/fragments/references. Original bytes сохраняются.

Batch map один раз перестраивает source-derived snapshot, также для empty batch,
сравнивает профиль/coverage/text/references и возвращает точные code-point source slices.
Это не гарантия свежести вычисленного значения, разметки страниц или native Word parity;
результат относится к сохранённому файлу. Подключение профиля к приложению, редактирование
сложных полей и оставшаяся DOCX матрица выполняются отдельно.
[Контракт и первичные источники](d03-17a2b5a1-contract.md),
[проверки](d03-17a2b5a1-result.md).
