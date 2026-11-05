# D03-17C1E3 — результат проектирования startup/recovery

2 ноября 2026. Продолжение после preflight `21ad022`. **Проектирование завершено**, подготовлен [точный контракт E3](d03-17c1e3-contract.md). Поведение приложения пока не менялось: E3 source/acceptance ещё не создавались. Последний checked implementation остаётся E2 `134633c`.

Выбрано сохранить JOB_LIST и двух владельцев Job, но не подтверждать physical cleanup без evidence. Штатный failed create, successful create с retained handles и unknown outcome теперь различаются. Для неизвестного исхода — quarantine/no retry/no candidate, без PID cleanup или ложного cancelled. Отсутствие proof не объявлено найденным Windows-багом.

Контракт задаёт preallocated strongly retained holder, native ABI/flags, exact handle allowlist и reduced-rights events, единственный Resume, условия teardown/actual wait, отдельные I/O owners по frozen E2, bounded guardian/bootstrap/fixture и новую acceptance. S Stop не закрывает buffers/Job во время native create; failed setup не теряет pending I/O. Old source/tests не подгонялись под новый контракт.

Автоматическое восстановление после потери владельца **ещё не реализовано и не обещано**. C1F перед production wiring должен сохранить durable crash fence до create и снимать его только по physical proof, SQL reconciliation и I/O quiescence. Свободный slot/terminal SQL не заменяют этот gate; reaper может уже завершить run. Это уточнение существующей ответственности C1F, без изменения схемы/служебных файлов в E3 и без нового продуктового scope.

## Проверка и сохранность

`bash scripts/check.sh`: **3378 passed +24 subtests,10 skipped,77 warnings,375,58s,exit0**. Ruff и format414files прошли. Лог `.runtime/d03-17c1e3-design-full-check.log`. Это регрессия существующего кода на Mac;10 skips требуют реальной Windows. Проверка E3 implementation не заявляется, искусственный red для документационного цикла не создавался. Новая acceptance/freeze/red — следующий шаг реализации.

Read-only start snapshot совпал с E2 final, final — со start: `ara_dev` остаётся V8, schema/counts неизменны, `ara_test` пуста, временных check databases не осталось. PostgreSQL оставлен работающим.445 tracked source/test/contracts/runner/config files совпали по SHA-256 с baseline до gate. UTF-8, относительные ссылки и `git diff --check` проверены.

Изменены только собственные design/status документы; чужие README/spec/backlog/материалы сохранены. Секреты, архив, .artifact-build/output, Word и реальная модель не использовались. Внешнее чтение — публичные первичные страницы Microsoft, ссылки рядом с решениями в контракте. Нет миграций, новых dependencies, runner/task/progress изменений, push или публикации.

## Следующий цикл

**Переключиться на Sol6.1 High и реализовать D03-17C1E3** по контракту: acceptance/freeze/red → source → targeted/full → result/local commit. Затем E4 отдельным циклом, если режим достаточен и нет нового конфликта. Стартовать production Windows runtime из E3 нельзя.

Native ordinary suite и pre-return crash gate остаются обязательными. Последний запускается только в disposable Windows VM с внешней процедурой полного cleanup, без дополнительного Job HANDLE у harness; случайный crash stress не доказывает все kernel interleavings. Mac mocks это не заменяют. C1F recovery, full DOCX/Word, модель/веса, frontend, лицензия и поставка остаются впереди в своих границах.

Самостоятельный остаток **28–43 цикла**. Дизайн уточнил уже учтённый E3, его реализация ещё не вычитается; дополнительный ID не создан. Native среды/работа Ани и Артёма отдельно, оценка не гарантированный потолок.
