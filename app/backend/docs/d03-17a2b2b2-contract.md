# D03-17A2b2b2 — итоговый вид inline-перемещений Word

4 ноября2026, следующий bounded цикл после structural catalog b2b1. Основание:
выбранный пользователем итоговый вид правок и только видимый текст; обязательная
DOCX матрица, прежнее разбиение A2b. Реализуем pure opt-in reader и обратные адреса.
Существующий API/ML admission/БД и native Word gates остаются прежними.

## Граница изменений

Новые `src/ara/docx_analysis/visible_moves/`,
`tests/acceptance/test_docx_visible_moves.py`,
`tests/docx_documents/test_visible_moves_edges.py`, этот contract/result/guide/queue.
Оркестратор до реализации разрешает ограниченное выделение private shared pipeline
в `visible_main/_build.py`, `_map.py`, `_shape.py`, `_canonical.py`, `_reader.py`.
Только внутренние параметры fixed profile/reader/validator/builder и default refusal
hook. Public visible_main API, v1 profile/fragment IDs, default schema validation и
все старые тесты должны остаться эквивалентны. Не расширять old profile enum, не
выдавать новый результат за old snapshot, не предоставлять публичный выбор callback.
Другие прежние source/tests, catalog b2b1, dependencies/runner/tasks/progress/DDL
не менять. Main V8/пользовательские файлы untouched. Только synthetic test packages.

## Версия и API

Новый namespace `ara.docx_analysis.visible_moves`:
`build_move_snapshot(data, *, document_id, storage_revision, source_sha256, limits=None)`;
`map_move_spans(data, snapshot, *, requests, limits=None)`;
`map_move_span(data, snapshot, *, fragment_id, start, end, quote, limits=None)`.
Те же exact Visible* records/VisibleLimits/VisibleViewError re-export, immutable
source-bound snapshot. Profile `docx-analysis/final-visible-main-moves-v1`, policy
`docx-analysis-policy/final-visible-no-comments-v2`. Shape validation и fragment
canonical preimage содержат именно этот profile. Old/new mapper взаимно отвергают
чужой profile даже при empty requests и пересчитанном digest. Нет caller-supplied
catalog/reader/profile, новых SQL/HTTP/ML contracts или подключения к приложению.

Exact bytes/UUID/revision1..2^63-1/lowerhexSHA, размер ZIP перед hash, source equality,
existing open_docx DTD/ZIP protection и aggregate main/styles preflight сохранены.
Catalog строится заново из этих же bytes в каждом build; при batch mapping ровно
один authoritative snapshot rebuild, один move catalog и один style catalog.
Отдельный bounded catalog DOM после aggregate preflight разрешён; sanitizer и
удаление тегов перед чтением запрещены: original element paths обязаны сохраняться.

## Итоговая семантика

[Microsoft MoveFromRun](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.movefromrun?view=openxml-3.0.1)
определяет inline содержимое, перемещённое из прежнего расположения;
[MoveToRun](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.movetorun?view=openxml-3.0.1)
— содержимое в месте назначения. Документация прочитана4ноября. Используем только
структурно paired grammar b2b1, не объявляем полную OOXML conformance/Word parity.

Read catalog from original bytes, never trust detached supplied DTO. Если blocked,
никаких main fragments/paragraph/run contexts; coverage blocked move_catalog_blocked.
Если absent, старый поддержанный grammar остаётся, но profile и fragment IDs новые.
Если indexed, каждый range marker даёт metadata/move_range; каждый source wrapper
excluded/moved_source; destination metadata/moved_destination, затем обычный inline
parser с текущими правилами ins/del/comment/hyperlink/style/hidden visibility.
Только wrapper считается moved content: ordinary runs между range endpoints остаются
на месте, source/destination texts могут различаться. В source wrapper текст не
интерпретируется (revision-excluded, аналог del), но move catalog сканирует ВСЕ
вложенные move tags, не прячет неподдержанные/двусмысленные move structures.

Все anchors — исходный ZIP main path, SHA, zero-based element child indices.
Visible character spans относятся к destination atoms, исходные source atoms никогда
не получают false destination coordinates. Никаких изменений документа или принятия
Word revisions. Unicode/codepoint offsets, tabs/breaks, empty paragraph policy,
separator gaps и exact quote semantics наследуются без преобразований.

Retained unknown flow/parts, table/SDT/field, cross-paragraph range, moved/deleted/
hidden paragraph boundary, implicit character visibility и unresolved style guards
сохраняются. Complete означает только coverage этого versioned pure reader; native
Word rendering/parity, editing move structures и runtime admission отдельно.
Main-only catalog не превращает другие parts в прочитанные. Coverage/digest включают
все прежние inventory exclusions/blocked checks. Не возвращать частичный main текст
при ошибке grammar; complete не означает реальный ML result.

## Bounds, mapping, checks

VisibleLimits применяется как прежде к всему main/styles и request/result batches.
Catalog XML caps берутся из соответствующих VisibleLimits; собственные range8192/
member10000 caps остаются default b2b1. MoveCatalogError limit переводится в fixed
VisibleViewError view_limit_exceeded, другие ошибки без текста в fixed diagnostic.
Raw bytes при вызове и frozen records остаются неизменными. Repr не содержит текста,
имён moves/автора/style IDs. Snapshot/fragment hashes deterministic и profile-bound.
Mapper сначала bounded exact shape validation, затем rebuild из exact source,
полное сравнение DTO; пересчёт caller digest не подтверждает подменённые поля.
Используется прежний indexed batch mapper, атомарный отказ, no partial list. Даже
empty request валидирует source/snapshot. No I/O/network/env/Word при import/build/map.

Freeze/red до кода. Independent literal text и exact original XML paths: обе Word
namespaces/UTF16/custom main path, source/destination order/paragraphs, different
texts/IDs, ordinary range content, multiple members, inherited/direct hidden runs,
inserted/deleted/comment/hyperlink destination, tabs/Unicode/gaps. Explicit malformed
catalog/boundary/unsupported flow/part cases. Forged shape/source/text/provenance/
profile/digest, limits before semantic DOM, smaller call limits, batch single rebuild,
fresh-process inertness и old/new non-admission tests. Старые tests immutable; setup
новых tests можно исправлять с письменной причиной без ослабления semantic assertions.
Review additions до full gate. Required `bash scripts/check.sh`, baseline hashes
unchanged кроме пяти прямо разрешённых shared files, readonly main V8 snapshot,
result/guide/local commit, затем следующий independent cycle по команде пользователя.

Native Word простой control4ноября снова timed out(-1712), source unchanged,
собственный документ закрыт. Это не доказательство причины лицензии. Не снимать gate,
не повторять бесконечно, не трогать пользовательские документы. Pure reader можно
проверить автономно; native parity и его application integration пока не закрывать.
