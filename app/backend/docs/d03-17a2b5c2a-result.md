# D03-17A2b5c2a — verified original-address compatibility view

5 ноября 2026. Baseline `0d2d3bd`, freeze `7597f9a`, preparation/review `6130cbc`.
Red **29 failed /0.31s**. Первый targeted **27 passed, 2 failed /2.31s**: новый
«empty Choice» fixture содержал default абзац; no-serialization guard включался
до создания synthetic fixture. По разрешению frozen contract исправлены только
подготовки: explicit empty content и fixture до guard. Assertions прежние.
После исправлений **29 passed /0.19s**. Review ещё6: исходный DOM не меняется,
root alternative refusal, literal whitespace при удалении attrs, non-XML whitespace,
максимальная XML depth128 и ignored extension child. Combined **152 passed /0.66s**
(35 view +63 compatibility +54 table-controls). Старые source/tests не менялись.

Новый `build_compatibility_view` сначала заново строит C1 catalog по исходным bytes.
Только после всех raw bounds/MC checks читает по одному оригинальному дереву каждой
scoped part. Read-only ViewNode хранит исходные anchor/tag/text/tail, выбранные attrs
и tuple логических детей. Lookup/tree используют один объект; namespace/prefix choice
не пересчитывается. Original DOM/ZIP не меняются и не сериализуются. Unknown ordinary
markup сохраняется для будущего content proof.

Structural wrappers раскрываются/пропускаются без перенумерации anchors; выбранные
Choice/Fallback не становятся фиктивными узлами. Whole-part root transformation и
смешанный текст на границе продвижения/удаления дают атомарный явный отказ, также
любое structural изменение внутри Word text/instruction leaves. Нельзя незаметно
склеить w:t или потерять tail. Прежние публичные readers остаются прежними: этот
view ещё не подключён к snapshot/admission, только основа общей интерпретации.

Full `bash scripts/check.sh`: **5786 passed, 45 skipped, 81 warnings, 24 subtests passed
/807.80s**, exit0; Ruff/format810 files. Все 872 frozen hashes exact; все 865 прежних
unchanged. Readonly основная V8 `0008_docx_edit_drafts`: schema/revision/counts совпали
с C1, содержимое строк не читалось. Выборочный локальный commit; без публикации.
Следующий цикл: opt-in общие anchors/согласованные styles, table-style proof,
sections/settings и note definitions из одного view. Затем whole-story reader/mapping.
Native Word/Windows, media/сложный редактор/export и внешние UI/ML/release gates остаются.
