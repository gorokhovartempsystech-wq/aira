# D03-17D — результат API проверки сохранённого DOCX

3 ноября 2026. Завершён по [контракту](d03-17d-contract.md), в рамках автономного
продолжения на выбранной пользователем Astra. Пакета модели пока нет — Никита
подтвердил это в чате и разрешил продолжать без него. Настоящий ML остаётся C2.

Добавлен opt-in API saved editor→supervisor→SQL result. Default app сохраняет
старые routes. Явная установка проверяет server-owned scope/issued supervisor,
не запускает runtime и не мигрирует БД. Bootstrap владеет native жизненным циклом.
Новый read pool имеет ограниченные соединения/SQL timeouts и закрывается с app.

Реализованы admission receipt/GET/retry/Stop/run/result/latest success, строгий
JSON и OpenAPI. 202 может предшествовать enqueue; pending и неизвестный ACK не
выдаются за durable success. Повтор exact key/body не вызывает новый анализ;
потерянный save сначала reconcile. Known Stop использует отдельный HTTP/thread
канал без ожидания SQL. Cache ограничен активными записями и LRU terminal metadata,
после вытеснения доступен scoped durable lookup.

Результат полностью повторно проверяется B2 по source/request/result; decode
вне SQL locks, затем scope recheck. Private confidence/rule/suggestion не выдаются.
Актуальность относится к durable saved source, не к несохранённому RAM тексту.
Новый failed run сохраняет прежний success; retry закреплён за исходником старого
run. Подробности для фронтенда: [API guide](docx-analysis-api.md).

## Проверки

- Freeze `bacc664`:35 независимых cases. Red до source:2failed+33errors, missing
  namespace. Supplemental `d558475`: ещё2 cases для Stop gate/eviction. Все
  исходные35 functions/assertions AST-identical; приёмка не ослаблялась.
- Targeted35passed18.58s. Совместный API+F3 regression **76passed70.58s**.
- `bash scripts/check.sh`: **3841passed,41skipped,24subtests,79warnings**,
  exit0,493.44s. Ruff/check+format green. Native macOS editor→save→child→result→
  edit/save→new result/reopen прошёл. Native Windows здесь не подтверждён.
- 522 gate hashes неизменны. Из513 файлов прошлого gate изменён только разрешённый
  `src/ara/app.py`: optional argument + installer. Старые tests/schema/runner/
  tasks/progress/dependencies неизменны.
- Main остаётся `0008_docx_edit_drafts`, tables/counts неизменны; ara_test пустая,
  временных databases0. Миграции только в disposable acceptance databases.

Логи/снимки локально: `.runtime/d03-17d-{red,targeted,regression,full}.log`,
`d03-17d-hashes.json`, `d03-17d-runtime.json`. Первое подключение lifespan
исправлено в новом source под установленную FastAPI; тесты ради этого не менялись.

## Дальше

E1: pure presentation filters и exact dismissal identity. Затем persistence/API/
однозначный перенос между изменёнными документами отдельными циклами. Общая
ориентировочная очередь самостоятельной работы **24–39 циклов**, включая эти
части и остальные desktop/license/quality задачи; это диапазон планирования,
не обещание готового релиза. Реальная модель, фронтенд Ани, Word/Windows release
checks остаются зависимыми gate. Фильтры/скрытие/лицензия/установщик этим API не
объявляются реализованными. Переключение режима не требуется.
