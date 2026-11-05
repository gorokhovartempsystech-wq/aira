# D03-17E1 — результат фильтров и точной идентичности скрытия

3 ноября 2026. Завершён pure слой по [контракту](d03-17e1-contract.md).
B2 source/request/result проверяются заново перед построением представления.
Фильтры типов и вопросов, hide/show_hidden меняют только представление; полный
результат и исходный признак no_findings остаются прежними. Общий вопрос остаётся,
пока у него есть видимые origins. Private provenance не выдаётся.

SHA256 dismissal key связан с документом, точными байтами источника,
моделью/адаптером/profile/policy, значимыми полями замечания, rule и exact evidence.
Смена attempt/upstream ID/confidence, номера хранения при тех же байтах не создаёт
новую проблему. Изменение source/model/severity/rule/explanation/question/related
или адреса создаёт другой key. Повторяющиеся цитаты по разным адресам не смешиваются.
Между изменёнными DOCX автоматический перенос здесь отсутствует: это отдельный E4.

## Проверки

Freeze `f94fc50`, red31failed0.83s missing namespace. Исходные31 cases green1.36s;
дополнительные2 cases `5ebc909` проверяют смешанные типы/sharedquestion и замену
related при тех же sourcebytes. Исходные functions/assertions AST-identical.
Совместно с B1/B2 **139passed3.59s**.

`bash scripts/check.sh`: **3874passed,41skipped,24subtests,75warnings**,
exit0,504.35s. Ruff/format green.525 gate hashes unchanged; все522 файла
предыдущего D неизменны. Main V8/schema/counts сохранены, ara_test пустая,
временных databases0. Логи/снимки `.runtime/d03-17e1-{red,targeted,regression,full}.log`,
`d03-17e1-hashes.json`, `d03-17e1-runtime.json`.

Основной product scope уточнён техническим presentation-only правилом выбранного
D03-17 design; это не приписанное пользователю новое решение о генерации модели.
Продуктовый перечень категорий окончательно не утверждён; текущие3 типа — B1adapter.

## Следующий цикл

E2A добавит отдельные таблицы preferences/dismissals/receipts и проверит
сохранность миграций; E2B реализует CAS/storage, E3 HTTP, E4 перенос скрытия.
Постоянная память скрытия, UI, настоящий ML и релиз этим pure слоем не завершены.
Ориентировочно осталось **23–38 самостоятельных циклов**, без обещания внешних
модели/фронтенда/Windows Word acceptance. Продолжаем на выбранной Astra.
