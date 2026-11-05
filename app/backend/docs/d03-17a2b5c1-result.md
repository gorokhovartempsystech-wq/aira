# D03-17A2b5c1 — verified compatibility selection catalog

5 ноября 2026. Baseline `9da0058`; freeze `eb8ac3c`; new-test preparation/review
`40eb356`. Red **55 failed /0.42s**. Первый targeted **54 passed, 1 failed /0.17s**:
new test заменял TreeBuilder класс функцией, блокируя declaration старого subclass
до любой аллокации. По явному разрешению frozen contract исправлена только подготовка:
TreeBuilder subclass запрещает __new__, прежние assertions/I/O guards сохранены.
Review добавил 8 проверок URI scopes/Requires/MU/Unicode/metadata. Финальный targeted
**63 passed /0.17s**; совместный regression **271 passed /0.91s**.

Новый pure catalog `docx-compatibility/base-word-selection-v1` выбирает первую
поддерживаемую Choice, иначе Fallback или отсутствие ветви; игнорирует/раскрывает
только явно объявленные URI и описывает удаляемые атрибуты. Prefix resolution
использует область самого узла; inherited rules хранят URI, sibling/rebinding
восстанавливаются. Source bytes и physical paths остаются исходными. Каталог не
содержит текста/значений metadata/DOM и не утверждает complete/admission.

Все scoped main/styles/settings/header/footer/notes parts, включая unused, проходят
aggregate SAX bounds до semantics. Затем второй streaming pass без semantic DOM
строит атомарный metadata-only manifest. Namespaces/expanded names/list tokens и
inactive branches учитываются лимитами. Unsupported MU активного содержимого,
неподдержанные MC extensions и синтаксические ошибки возвращают явный отказ без
ранних decisions; unknown non-ignorable markup остаётся для downstream content proof.

Full `bash scripts/check.sh`: **5751 passed, 45 skipped, 80 warnings, 24 subtests passed
/800.43s**, exit0; Ruff/format804 files. Все 865 финальных hashes exact; все 855 прежних
unchanged. Readonly основная V8 `0008_docx_edit_drafts`: schema/revision/counts совпали с
b5b2; содержимое строк не читалось. Выборочный локальный commit, без публикации.
Это ещё не MC support в application reader: C2 должен подключить одно view ко всем
semantic consumers, сохранив original anchors/source-backed mapping. Native Word,
graphics/extension capabilities, полноценный сложный редактор/export остаются gates.
