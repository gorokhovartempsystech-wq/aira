# Каталог перемещений текста в DOCX

`ara.docx_analysis.moves.read_move_catalog(data, source_sha256=...)` читает только
структуру inline move ranges основной части документа. Вход — точные bytes и их
SHA256. Ничего не записывает, не запускает Word и не принимает исправления.

Результат MoveCatalog содержит profile `docx-moves/main-inline-catalog-v1`,
source/catalog SHA, main part, пары MovePair и диагностические MoveIssue.
`indexed` означает распознанные структурные пары; `absent` — отсутствие шести
поддерживаемых видов move markup в main part; `blocked` — неподдержанный контекст
или противоречивые связи. Ни один статус не означает complete analysis/Word parity.
Каталог не возвращает текст требований и не определяет его видимость.

В паре source/destination имеют одно точное `w:name`. Start/end своего range связаны
нормализованным числовым `w:id`; ID wrapper revision независим. Source и destination
могут появляться в любом порядке и в разных абзацах. Разный текст в них допустим:
после перемещения могли быть другие правки. Совпадение цитат не используется.

Первый профиль допускает range markers/wrappers непосредственно внутри обычного
main-body абзаца, start/end каждого range внутри одного абзаца. В MoveRange.members
попадают только соответствующие moveFrom/moveTo wrappers. Обычные runs между
метками остаются обычными: наличие range container не делает весь текст перемещённым.
Каждый SourceAnchor указывает на исходный XML элемент по SHA/part/element-index path.
Комментарий XML или processing instruction не добавляет element index.

Nested/crossing/unmatched/duplicate ranges, unsupported attributes и контексты,
paragraph-mark moves, таблицы/customXml/SDT/history и межабзацные ranges дают blocked.
Это очередность реализации полного DOCX, а не исключение этих элементов из продукта.
Catalog не заменяет existing visible reader: тот по-прежнему блокирует moves.
Следующий reader должен сам построить каталог из тех же pinned bytes, проверить
содержимое/visibility и использовать новый versioned profile с отдельной приёмкой.
Произвольный созданный caller DTO не является доказательством правильности документа.

MoveLimits ограничивает main XML nodes/depth/characters, число range starts и
move wrappers; нижние пределы можно передать явно. Предварительный streaming pass
учитывает также исключённые ветви, text/tails, attribute values и namespace URI
values до построения semantic DOM. Успешная частичная выдача при превышении лимита
запрещена. Existing package ZIP/DTD/entity/size protections сохранены.

[Контракт](d03-17a2b2b1-contract.md), [результат](d03-17a2b2b1-result.md).
