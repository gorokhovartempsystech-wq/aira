# D03-15B1 — позиции курсора в единой истории DOCX

31 октября 2026. Отдельный subcycle D03-15B после 89bad1c, F05/F11. Продолжение без остановки по прямой команде Никиты на Sol 6.1 High. B1 связывает selection и существующую exact history; B2 отдельно реализует compound Enter/typing policy. UX-история D03-15B не объявляется готовой до B2/подключения frontend.

## Публичный API нового пакета ara.docx_package.editor

Frozen/slotted DTO:

```python
Caret(anchor: SourceAnchor, offset: int, affinity: str = "right")
EditorSelection(anchor: Caret, focus: Caret)
CaretTarget(block_index: int, offset: int, affinity: str = "right")
SelectionTarget(anchor: CaretTarget, focus: CaretTarget)
EditorSnapshot(document: SessionSnapshot, selection: EditorSelection, position_id: int)
EditorError
EditorSession(data: bytes, *, limits=None, projection_limits=None, session_limits=None)

editor.snapshot() -> EditorSnapshot
editor.capture(selection: EditorSelection, *, expected_revision: int) -> EditorSnapshot
editor.apply_boundary(command, *, expected_revision: int, boundary_limits=None) -> EditorSnapshot
editor.apply(edits, *, after: SelectionTarget, expected_revision: int, range_limits=None) -> EditorSnapshot
editor.apply_structure(commands, *, after: SelectionTarget, expected_revision: int,
                       structure_limits=None) -> EditorSnapshot
editor.apply_formats(formats, *, expected_revision: int, after: SelectionTarget | None = None,
                     format_limits=None) -> EditorSnapshot
editor.undo(*, expected_revision: int) -> EditorSnapshot
editor.redo(*, expected_revision: int) -> EditorSnapshot
editor.mark_saved(*, expected_revision: int) -> EditorSnapshot
```

Строгие типы без bool/coercion/subclasses, frozen bypass перепроверяется. Offset/block_index неотрицательные int. Affinity только left/right. У Caret SourceAnchor строгий как D03-14. Document и selection исключены из repr EditorSnapshot, сырые данные/текст не логируются. Старые DTO/DocxSession не меняются.

Caret — paragraph anchor и code-point offset текущего source. Selection может быть обратной/между body paragraphs; точки обязаны адресовать прямые projected p и лежать в их тексте. Для capture hash должен совпасть, part/path проверяются. Stale hash → EditorError stale_selection; чужой part/span/cell/opaque/outside text → invalid_selection. Expected session revision проверяется **первой** прежним SessionError. Многопоточная/многоклиентская синхронизация не входит: один controller сериализует вызовы.

CaretTarget адресует block_index в candidate.projection.blocks (индекс включает table/opaque), который обязан быть paragraph, +offset/affinity. У target нет source hash: он описывает позицию после конкретного guarded действия. Before selection берётся из последнего capture. Ошибка target после успешного вычисления pure операции не публикует ни DOCX, ни историю, ни selection. Для range/structure явный after обязателен; не угадывать caret при произвольном batch.

Конструктор ставит collapsed selection на начало первого body p с affinity right, position_id=0; если p нет — invalid_selection без изменения источника. Split автоматически ставит caret в правый результат, offset 0; join — в левый результат, offset длина прежнего левого текста. Новый anchor берётся из post-projection. Formats без after оставляет offsets/path/affinities текущей selection с новым source hash; если это неприменимо, безопасный отказ. No-op не создаёт history position/ID и не очищает redo; явный after может поменять только текущую selection.

## Атомарная история и изоляция

EditorSession владеет скрытой DocxSession. Перед мутирующим вызовом делает shallow copy доверенной core сессии, чей _State/bytes/undo tuples неизменяемы; изменяет только candidate, проверяет after selection, готовит весь EditorSnapshot и только затем одной заменой публикует wrapper state. Нельзя сначала изменить действующую core, а затем пробовать откат через undo. Публичного метода принять произвольный candidate package нет.

Каждой **позиции** истории соответствует локальный монотонно выделяемый ID и immutable selection coordinates. Текущий frame и metadata undo/redo должны иметь те же глубины и порядок, что core. Frame не хранит полный core/SessionSnapshot/DocxProjection/DOCX bytes, чтобы не удерживать скрытую квадратичную историю. Core budgets остаются прежними; metadata удаляется синхронно с eviction. No-op/capture/mark_saved сохраняют ID и глубины. Новый фактический шаг получает следующий никогда не переиспользуемый ID; undo/redo возвращают прежний ID с новой session revision (ABA). Branch удаляет metadata redo вместе с core redo.

Capture обновляет только selection текущего frame и возвращает подтверждение; bytes/revision/history/saved mark не меняются. Undo/redo восстанавливает selection именно сохранённого frame, включая направление и affinity. SourceAnchor заново строится для exact bytes этого frame. Mark_saved не сбрасывает selection/историю и следует прежнему strict expected_revision. Неизвестный исход внешнего save/блокировка вкладки — будущий transport/controller policy, не фиктивное состояние этого in-memory API.

Наружные snapshots/вложенные frozen DTO не разделяются с внутренними metadata. Даже обход frozen в возвращённом selection/source anchor/projection не влияет на controller, другие snapshots или сессии. Ошибки подготовки ответа/selection/native exporter оставляют состояние полностью прежним. Native SessionError/BoundaryError/StructureError/FormattingError/RangeError/DocxError/ProjectionError сохраняются. EditorError codes invalid_input/invalid_selection/stale_selection с постоянными content-free messages.

## Границы и приёмка

Уточнение discovery 31 октября, после первого полного gate: pyproject.toml содержит фиксированный testpaths и не включает новую tests/docx_editor. Разрешается добавить только tests/docx_session/test_editor_history.py, переэкспортирующий четыре test-функции (семь cases) из нового модуля без изменения их assertions. Это подключает все дополнительные проверки в существующий полный gate; pyproject/scripts/старые tests и frozen acceptance не меняются. Первый gate с 1786 tests не выдавать за прогон дополнительных семи; после подключения выполнить общий gate снова. Расширение пути требуется для полноценной проверки в рамках прямого разрешения Никиты автономно выполнять разработку, не ослабляет критерии задачи.

Только новый src/ara/docx_package/editor/**, tests/docx_editor/**, отчёт docs/d03-15b1-result.md. Не менять existing session/pure exporters, их tests/DTO, UI/HTTP/DB/миграции/зависимости/runner/tasks/progress/инструкции. Импорт/операции без I/O/env/secrets/logging; только стандартная библиотека и прежние pure API. Capture не создаёт визуальный renderer. Typing format и команда Enter с next-style/выходом из списка — B2; B1 хранит позиции/affinity и не обещает реализацию будущего набора в пустой paragraph.

До кода заморозить tests/acceptance/test_docx_editor_history.py с валидными synthetic fixtures и показать red. Проверить split/join cursors/точные bytes, reversed selection, mixed range/structure/format state, ABA IDs/branch/no-op, синхронное eviction, strict limits/revisions/anchors, invalid after rollback, failure EditorSnapshot preparation, frozen snapshot poisoning, independence и inert imports/operations. Full bash scripts/check.sh и baseline БД. Выходной package должен совпасть с неизменным core/pure oracle; повторный renderer допустим только для подтверждённого hash уже просмотренного QA. После отчёта/коммита переходить к отдельному B2 на текущем режиме, если хватает качества.
