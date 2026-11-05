# D03-17C2 — сквозной учебный режим проверен

3 ноября 2026, Astra. [Контракт](d03-17c2-fixture-contract.md), freeze `6f743f1`,
red31failed на отсутствии implementation. Исправление подготовки decoder
`62bef49` передаёт обязательный execution digest; все assertions сохранены.

Добавлена отдельная инертная factory `create_review_fixture_supervisor`.
На настоящем macOS native процессе сохранённый DOCX проходит ready/stages,
генерацию явно учебного замечания, source-backed B1/B2 validation, guarded SQL
publication и cleanup. Проверены restart, следующий run и Stop без результата
с сохранённым source. Windows child body проверен shaped wire test; это не
подтверждение Windows HANDLE/Job lifecycle. Старый opaque fixture/fault modes
по-прежнему дают прежние ответы, новый режим opt-in.

Targeted **31passed,1,83s**. Вместе со всей F3 acceptance/edges —
**99passed,20,08s**. **`bash scripts/check.sh`:3804passed,41skipped,
24subtests passed,75warnings,424,93s,exit0**. Ruff/format482files прошли;
513 gate hashes стабильны. Из прежних510 файлов изменены только четыре
разрешённых native fixture paths и добавлены два source/один acceptance файл;
прежние F3/прочие assertions не менялись. Main V8/schema/counts прежние,
ara_test пуста,temporary DB0. Логи `.runtime/d03-17c2-fixture-*.log`, snapshot
`.runtime/d03-17c2-fixture-runtime.json`. PostgreSQL оставлен работающим.

C2 имеет готовые input guards и настоящий сквозной **учебный** путь. Подключение
реальных ONNX buffers/весов и текущего engine353cfee с partial/pairwise остаётся
не завершено. Пакет запрошен у Никиты; отсутствие ответа не блокирует независимые
задачи по его прежнему поручению. Не называть synthetic finding реальным анализом,
готовым пилотом или моделью из установщика.

Продолжаем [D — API проверки сохранённого DOCX](d03-17d-contract.md), затем E.
Самостоятельный ориентир пока **25–40**: C2 не вычтен как полностью подключённая
модель, checkpoints не создают новые ID. Режим Astra сохраняем, push/main migration/
runner/tasks/progress/dependency changes не выполнялись.
