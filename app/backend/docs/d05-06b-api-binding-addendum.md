# D05-06B — дополнение: identity binding HTTP analysis

4 ноября 2026. Обнаружено первым красным integration прогоном после реализации:
`docx_analysis_api.Service` сравнивает legacy database_url, а его `_reads.read_runtime`
создаёт новый URL-based pool. DesktopDatabaseSettings намеренно не содержит URL.
Поэтому контракт B требует небольшого дополнительного bridge до общей приёмки.
Это техническое уточнение orchestrator в рамках прямой команды Никиты продолжать
самостоятельно; оно не называется отдельным согласованием пользователя. Frozen
B contract/tests сохраняются; ни один критерий не удаляется/ослабляется.

Дополнительно разрешены ровно два старых source:
`src/ara/desktop/database/_source.py` — новый tracked `analysis_read` lane cap2,
уже существующие supervisor OPTIONS (statement2s/lock0.5s/transaction5s), NullPool;
`src/ara/docx_analysis_api/_service.py` — branch только exact DesktopDatabaseSettings.
Новый `src/ara/desktop/database/http_binding.py` проверяет живой issued source,
exact DocumentRuntime/registry engine identity + Home IDs, supervisor scope, выдаёт
отдельный lazy analysis_read Engine из того же source. URL equality недостаточно:
все desktop engines имеют одинаковый placeholder URL. Нельзя принять другой Engine
даже с тем же URL. Service.close закрывает только свой read Engine. Общий Source
отслеживает и ждёт read connections, так же как document/control/publication.
Legacy branch/URL/pools/options, `_reads.py`, старые tests остаются неизменными.

Новая независимая acceptance `test_desktop_composition_binding.py`: inert setup,
foreign/duplicate URL engine/registry scope rejects, real connection same owned DB,
read options/cap2, Source Stop waits borrowed read/denies new connect. Freeze/red
до двух source edits. Этот prerequisite проверяется вместе с исходным B full gate,
но commit выделяет его файлы отдельно для review. Final hash exceptions: исходный
LicenseClient runtime и ровно эти два bridge source. Остальные предыдущие690 exact.
