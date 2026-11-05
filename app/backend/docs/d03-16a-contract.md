# D03-16A — восстановление pure editor из checkpoint

31 октября 2026. Первый реализационный подцикл [проекта D03-16](d03-16-design.md), F05/F11/F12. Рекомендованный режим Sol 6.1 High. Реализация в этом проектном проходе не выполнялась. Перед кодом зафиксировать executable acceptance отдельным локальным коммитом и получить red; этот документ не объявляет будущие тесты выполненными.

## Результат

Восстановить точные рабочие DOCX bytes, selection/affinity и digest последней сохранённой версии без ложного dirty=false и без выдуманной undo-истории. Источник saved digest в будущей интеграции — проверенный scoped checkpoint/current. Pure API не делает SQL/сеть и сам не доказывает, что соответствующий файл когда-либо был сохранён.

Новые classmethods:

```python
DocxSession.restore(
    data: bytes, *, saved_sha256: str,
    limits: DocxLimits | None = None,
    projection_limits: ProjectionLimits | None = None,
    session_limits: SessionLimits | None = None,
) -> DocxSession

EditorSession.restore(
    data: bytes, *, saved_sha256: str, selection: EditorSelection,
    limits: DocxLimits | None = None,
    projection_limits: ProjectionLimits | None = None,
    session_limits: SessionLimits | None = None,
) -> EditorSession
```

saved_sha256 — настоящий str, ровно 64 lowercase hex; без auto-lower/strip/coercion. Invalid -> SessionError invalid_input. Data/limits/package/projection/history budgets и их существующие типы ошибок как у обычного конструктора. SessionSnapshot и EditorSnapshot не расширяются. Прежние constructors/methods/семантика ошибок сохраняются.

Core initial state: data exact, revision=0, undo_depth=redo_depth=0, saved_digest=bytes.fromhex(saved_sha256); is_dirty = SHA256(data) != saved_digest. Не применять fake edit от base к working, не присваивать revision из metadata старого процесса, не удерживать отдельную копию base package. Core restored session должна принимать все прежние команды.

Editor initial state: core выше, position_id=0, next new position ID=1, оба history stacks пусты; selection соответствует именно working package, сохраняет направление и обе affinity. Проверить типы EditorSelection/Caret/SourceAnchor и frozen bypass прежним строгим путём, source hash/main part/body p path/offset. Stale hash -> EditorError stale_selection; неверный path/part/offset -> invalid_selection, форма -> invalid_input. Пустой DOCX без редактируемого body paragraph сохраняет прежний отказ, не создаёт новый p молча.

Private state не ссылается на mutable caller DTO/projection/limits; публичные snapshots независимы. Невалидные данные/сбой подготовки ответа не возвращают частично восстановленный объект и не меняют переданные объекты. Предыдущая живая сессия вообще не аргумент этого factory; её историю не очищать ради recovery.

После новой правки undo возвращает restored working bytes/selection и исходный dirty (он может быть true). Redo возвращает новый итог. Mark_saved подтверждает только текущую revision, меняет saved_digest и сохраняет историю. Undo после mark_saved снова становится dirty, если bytes отличаются; повтор к сохранённым bytes снимает dirty. Overflow/DB/session epoch/transport не входят в pure restore.

## Обязательные acceptance cases до реализации

1. Core.restore с SHA текущих bytes → clean/rev0/empty history; с SHA другого синтетического DOCX → dirty/rev0/empty history. Exact bytes, original source anchors рабочей копии.
2. Editor.restore обратного выделения между двумя body p, разной affinity, пустого p и non-BMP/combining text → те же selection и offsets, position0. UTF-16 translation не выполняется.
3. Restored dirty → insert_text/split/style/paste → undo/redo: проверять exact bytes/selection/dirty и новые monotonic IDs, отсутствие fake base в undo. Если операция требует collapsed selection, до неё явно capture, не менять её старые ограничения.
4. Restored dirty → mark_saved → edit → undo → redo и stale mark_saved: прежние строгие правила, не сбрасывать историю.
5. Invalid digest: None/bool/bytes/subclass str/short/nonhex/uppercase/whitespace; invalid/mutated limits; превышенные package/projection/current-history budgets; все прежние constructors по-прежнему clean.
6. Selection with foreign source/main part/invalid p/opaque or table/negative or too-large offset; mutated frozen DTO; нужные existing error codes. Invalid data и source field не попадают в repr/errors/logs.
7. После factory менять caller-owned anchors/limits через object.__setattr__: session bytes/selection/history не меняются. Мутировать возвращённый snapshot таким же способом: новая snapshot неизменна.
8. First import/restore в отдельном процессе при запрещённых open/env/socket/process/log calls. Никакого открытия checkpoint файла или чтения secrets.env самим модулем.
9. Exact rich-source bytes на restore и после edit/undo; другие ZIP parts не меняются. Сам restore не требует нового визуального экспорта, если SHA совпал с уже проверенным source; показать hash proof, не заявлять новый Word render.

## Разрешённые пути и проверка

Source: src/ara/docx_package/session/_session.py, src/ara/docx_package/editor/_session.py; при необходимости только документирование новых factories в соответствующих __init__.py. Новый frozen tests/acceptance/test_docx_editor_restore.py; дополнительные tests/docx_session/test_restore_*.py в уже собираемой папке. docs/d03-16a-result.md и docs/development-queue.md. Не менять старые tests/DTO/exporters/HTTP/models/migrations/dependencies/scripts/runner/tasks/progress/AGENTS. Не добавлять общий публичный arbitrary replace-package setter.

Acceptance подготовить/проверить fixtures по реальным именам полей до freeze. После freeze исправления ошибок тестов документировать отдельно, не ослаблять критерии. Red -> реализация -> targeted -> bash scripts/check.sh (реальный PostgreSQL для общего набора) -> baseline схемы/счётчиков -> result -> отдельный local commit. Push/deploy не требуются. Затем автоматически следующий согласованный подцикл D03-16B1 с собственным контрактом, если текущего режима достаточно.
