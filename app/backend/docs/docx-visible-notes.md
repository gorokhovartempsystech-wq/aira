# Чтение текста сносок и обратные адреса

`ara.docx_analysis.visible_notes` предоставляет build_note_snapshot и map_note_spans/span.
Профиль `docx-analysis/final-visible-note-stories-v1` создаёт отдельный NoteSnapshot с
полями прежнего visible snapshot и массивом references. Старые профили не меняются и
не принимают этот новый тип как собственный manifest.

Основной текст и колонтитулы читаются в прежнем порядке. Затем читаются обычные сноски
и концевые примечания по первому видимому использованию; несколько ссылок на одну
сноску не дублируют её текст. Разрешение ссылки использует main relationship, вид
примечания и его ID, а не имя файла или отображаемый номер. Служебные разделители
определяются типом. Скрытые/удалённые ссылки не включают примечания в анализ.

Generated marker не является буквальным символом DOCX. На его месте абзац разбивается
на source-backed fragments без подставленной цифры. NoteReference сохраняет исходный
адрес ссылки, абзац, target note anchor и ближайшие fragments слева/справа в том же
абзаце. На краях, у последовательных маркеров и в абзаце только со ссылками допускается
None. Generated self label внутри сноски тоже создаёт границу, но не новую ссылку.
Пустые segments не становятся требованиями. Будущий ML adapter должен учитывать эти
связи; это не автоматическое подключение нового профиля к приложению.

Каждая сноска остаётся subtree своего исходного part, с исходным child-index prefix.
Чтение не создаёт фиктивный document/body и не меняет main_part. Таблицы, видимость,
стили, текущие свойства/правки и hyperlink relationships принадлежат оригинальному
контексту. Перед чтением part проверяется уникальность move range starts, в том числе
в unused notes; pairing не пересекает разные notes. XML каждой используемой части
для reader разбирается один раз; definition catalog выполняет свой свежий bounded proof.

До semantic DOM общие бюджеты считают все main/style/settings/story/note XML, включая
unused, special и hidden branches. Любая ошибка активной ветви либо неизвестная часть
оставляет весь новый snapshot без текста/fragments/references. Только после полного
proof разрешено исключить невостребованные и служебные определения. Batch mapping
один раз перестраивает manifest из исходных bytes, включая empty batch, сравнивает
все поля и переводит span в точные source slices. Подмена links/anchors/text с новым
хешем не проходит проверку. Offsets — code points; synthetic LF не имеют source slices.

CustomMarkFollows=true, note references в колонтитулах или внутри notes, поля и другие
неподдержанные структуры сохраняют явные gates. Native Word/Windows, display numbering,
layout, полноценная обработка DOCX и application admission этим модулем не подтверждены.
[Контракт](d03-17a2b4b2-contract.md), [проверки](d03-17a2b4b2-result.md).
