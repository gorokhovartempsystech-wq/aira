# D03-15A — общая snapshot-история операций DOCX

31 октября 2026. Самостоятельный bounded subcycle общего D03-15 после e995893, F05/F11. По прямой команде Никиты продолжать циклы на Sol 6.1 High. Дизайн d03-14-design.md сохраняется; selection/controller/составные Enter intents выполняются отдельным D03-15B, persistence — далее. Новый scope продукта не вводится.

## API и поведение

Существующая DocxSession получает три метода:

```python
apply_boundary(command: SplitParagraph | JoinParagraphs, *, expected_revision: int,
               boundary_limits: BoundaryLimits | None = None) -> SessionSnapshot
apply_structure(commands: tuple[InsertParagraph | DeleteParagraph, ...], *,
                expected_revision: int, structure_limits: StructureLimits | None = None) -> SessionSnapshot
apply_formats(formats: tuple[ParagraphFormat, ...], *, expected_revision: int,
              format_limits: FormatLimits | None = None) -> SessionSnapshot
```

Каждый вызывает соответствующий неизменный pure exporter на текущих bytes с прежними session package/projection limits. Одна успешная фактическая операция/batch — один undo шаг, session_revision +1; единый стек для прежнего RangeEdit и всех новых видов. Сначала проверить expected_revision прежним строгим способом (bool/не-int/отрицательное → invalid_input, несовпадение → stale_revision), затем нижние DTO/export errors сохраняют класс/code. Никакой переадресации старых anchors. Ошибка не меняет bytes/history/saved digest/revision.

Общий private accept-changed путь готовит новый state/reply до публикации. Все прежние гарантии D02-05 обязательны: точный undo/redo bytes, revision монотонна; no-op/ошибка не сбрасывают redo; новая фактическая правка удаляет redo; mark_saved не сбрасывает историю и не подтверждает старую revision. Saved digest определяет dirty независимо от способа изменения. Вытеснение старейших undo позиций по обоим прежним бюджетам, включая current, одинаково для всех методов. Невозможность поместить current или подготовить ответ откатывает весь шаг. Не вызывать undo как rollback неудачной операции.

SessionSnapshot, SessionLimits, SessionError, публичный apply(RangeEdit), конструктор/undo/redo/mark_saved и их contracts/tests не менять. Нового публичного метода «принять произвольный пакет» нет. В этом subcycle нет selection/клавиш, комбинированных split+style intents, HTTP/DB/recovery/таймеров. Импорт и операции инертны: без файлов/сети/secrets/logging/новых зависимостей. Данные/history не попадают в repr/errors.

## Подготовка и разрешённые пути

До реализации зафиксировать этот контракт и tests/acceptance/test_docx_session_commands.py, проверить fixtures прежними pure API, выполнить red. Далее source только src/ara/docx_package/session/_session.py и уточнение docstring session/__init__.py; собственные tests/docx_session/test_command_*.py; docs/d03-15a-result.md. Не менять DTO/другие pure exporters/старые tests/HTTP/БД/миграции/dependencies/runner/tasks/progress/инструкции. Локальный commit разрешён; чужие dirty-файлы сохранять.

Приёмка: смешанный range→split→insert/delete→style/list→join (когда совместимо), exact snapshots при полном undo/redo; save/undo/redo dirty; stale revision/ABA; ошибка и no-op после undo сохраняют redo; branch очищает redo; state/byte budget и их инклюзивные границы; лимиты нижних API; ошибка подготовки SessionSnapshot; сохранность projection и отсутствие I/O. Пакет после каждого нового метода сравнивается с неизменным pure exporter. Это сравнение oracle, а основная проверка — единая история, атомарность и восстановление.

Полный bash scripts/check.sh и baseline основной БД. QA: synthetic rich split→format→undo all→redo all→mark_saved; exact bytes на undo, пост-история совпадает с pure exports. Визуальный QA при новом выходном пакете через documents skill; если hash совпадает с просмотренным D03-14, подтвердить это и повторно осмотреть соответствующую страницу. После отчёта/коммита автоматически перейти к отдельному D03-15B, оставаясь на Sol 6.1 High, если не обнаружена необходимость более сильного режима.
