# D05-01 — локальный доступ и сохранение после истечения лицензии

4 ноября 2026. [Контракт](d05-01-contract.md) выполнен. Opt-in LicensedApplication
проверяет локальный caller, exact origin/Host и временную capability процесса,
затем текущую лицензию. Доступен только явно перечисленный современный DOCX API;
старые development/Markdown/merge/writer endpoints не открываются этим wrapper.
Токен не уходит в inner app, лицензия проверяется отдельно от него.

Без первого online-подтверждения документы закрыты. После expiry/неудачного повторного
check сохраняются read/checkpoint/save/reconcile/export/Stop уже разрешённого процесса;
новые edits/create/import/open/analysis/retry/preferences запрещены. Новый wrapper
не наследует preservation state. Закрытый LicenseClient блокирует и preservation.
Принятую запись/проверку wrapper не прерывает в середине операции.

Добавлены status/activate/verify с ограниченными JSON/body/concurrency, безопасными
ошибками и no-store. [API/handoff](desktop-access-api.md). Старые create_app,source,
tests,миграции и зависимости не менялись; обычный dev launcher прежний.

Freeze **ad4e058**:113 independent cases, red2failed/111errors1.77s. Первая реализация:
**113passed**,2.22s. Затем7 review cases (настоящий loopbackHTTP, отменаbody,
partial-response ownership, expiry/status race, nested IDs,inert constructor):
совместно с licensing **307passed,2skipped**,6.50s. Ещё2 controlled pending-analysis
cases гарантируют, что проверка не закончена до expiry, и проверяют late success
либо Stop: **2passed**,1.58s. Frozen приёмка/старые assertions неизменны.

`bash scripts/check.sh`: **4411passed,43skipped,24subtests,77warnings**,exit0,
670.45s; Ruff/format green.594 final hashes и все582 предыдущих совпали.
Main `0008_docx_edit_drafts`, schema/counts прежние; ara_test пустая, temporaryDB0.
Логи/manifest/snapshot `.runtime/d05-01-{red,targeted,regression,pending,full}.log`,
`d05-01-hashes.json`, `d05-01-runtime.json`.

Проверены реальный TCP server на127.0.0.1 с отключёнными proxy headers/access logs,
затем его полное закрытие; disposableV13 editor: create/open/edit→expiry→отказы
на новые действия→exact working/saved DOCX, checkpoint/save/close, неизменный original.
Pending fixture analysis после expiry завершается успешно либо останавливается;
в БД остаётся ровно один ранее принятый запуск. Device/clock/upstream license
transport в этих сценариях явно synthetic; production TLS и настоящие веса не заявляются.

Wrapper сохраняет уже принятый backend текст. Непереданный DOM/IME input будущего
frontend требует отдельного flush/rescue у Ани. UI/static assets, автоматический
запуск/закрытие сервера, установка PostgreSQL/модели, публичный license deployment
и native Windows release ещё не готовы. Старый development app без wrapper не
объявляется защищённым приложением.

Следующий **D05-02** — владение loopback server: запуск/остановка, bounded body и
graceful drain без отмены принятой записи. В ходе чтения выявлено, что старые
editor/upload readers ограничивают bytes, но не время ожидания тела: новый host
должен ограничивать его внешним envelope, сохранив старые handlers/tests.
Ориентир **13–28 самостоятельных циклов**, этот этап вычтен один раз.
Текущая Astra; продолжаем без остановки и смены режима.
