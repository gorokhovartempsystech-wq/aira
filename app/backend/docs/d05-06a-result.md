# D05-06A — owned desktop SQL bridge

4 ноября 2026. [Контракт](d05-06a-contract.md), freeze **ff3d06a**.
Новый DatabaseSource выдаёт lazy DocumentRuntime и явные settings supervisor,
проверяет каждое actual SQL connection против Home/PG identity и учитывает native
cleanup независимо от SQLAlchemy. [Интерфейс](desktop-database.md).

Red **17failed**,14.29s — модуля не было. Первый targeted **16passed,1failed**,
17.64s: отказ подменённой БД уже был корректным, но тест пытался прочитать сохранённую
БД по имени, которое закрытый HBA специально запрещает. Разрешённый контрактом
preparation fix: сохранить обе синтетические БД и вернуть прежней исходное имя
только для наблюдения. Проверки отказа по OID и exact DOCX сохранены. Далее
**17passed**,22.69s; frozen contract/lifecycle/supervisor files unchanged.

Review **2failed,2passed**,5.16s выявил две границы: известный отказ metadata до
native connect ошибочно считался unknown; typed cleanup error после attempted
native creation мог ошибочно освобождать claim. Исправлен source: граница
native_attempted отделяет эти исходы. Final combined **111passed**,44.22s, включая
новые21 и прежние supervisor runtime/SQL/semantic fixture проверки.

Native semantic fixture дважды запускается через public factory на той же owned
Home/PG, сохраняет явно fixture result, исходный DOCX остаётся exact. Проверены
inert construction, foreign/unprepared/duplicate handles, PID/copy/huge timeout,
per-lane caps, environment до native IO, actual revision/identity/replaced OID,
COMMIT при Stop и Stop до выдачи connection caller. Изолированные unknown native
creation/close остаются pending; после driver.finish исключение не маскируется
одним closed=True и native close не повторяется.

`bash scripts/check.sh`: **4869passed,45skipped,24subtests,80warnings**,767.42s,exit0.
Ruff/format green; все690 final hashes совпали после прогона. Предыдущие679 paths
unchanged, два разрешённых additive
bridge changes — supervisor/database.py и supervisor/runtime.py. Их legacy URL/
QueuePool/options путь сохранён; старые tests/migrations/dependencies/runner unchanged.
Readonly main snapshot совпал с D2: revision `0008_docx_edit_drafts`, прежние
schema/counts, ara_test пустая, temporaryDB0. Пользовательские строки не читались.
Логи `.runtime/d05-06a-{red,targeted,review-red,regression,full}.log`, hash manifest
`.runtime/d05-06a-hashes.json`.

Следующий D05-06B — общий owned desktop backend lifecycle: Home/PG/schema/source/
supervisor/licensed HTTP и корректная обратная остановка. В нём требуется явное
ожидание license worker: прежний close только инвалидирует доступ и не доказывает
окончание уже начатого atomic save. Реальная модель/frontend/Windows/installer и
внешняя release приёмка отдельно; текущая Astra подходит, продолжаем. Ориентир20–30 самостоятельных циклов по
оставшимся DOCX/desktop/adapter/final блокам, внешние release gates отдельно.
