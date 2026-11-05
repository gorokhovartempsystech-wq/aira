# D03-17C2 — проверка пакета и токенов готова

3 ноября 2026, Astra. [Контракт](d03-17c2-contract.md), freeze `505b52b`:
67 independent tests red на отсутствии namespace, затем **67 passed,0,06s**.

`model_input.verify_pack` проверяет manifest/files SHA, closed path names, размеры,
модельные metadata и выдаёт immutable bytes. `encode_batches/run_guarded`
отключают truncation/padding, проверяют specials/весь фактически отправляемый
single/pair input и передают inference те же проверенные IDs. Oversize не
превращается в успешный частичный ответ. Модули не импортируют ML и не имеют I/O.

**`bash scripts/check.sh`:3773 passed,41 skipped,24 subtests passed,75 warnings,
437,43s,exit0.** Ruff/format479files прошли. Все510 gate hashes совпали до/после;
504 файла предыдущего F3 gate неизменны. Main V8/schema/counts прежние,
ara_test пуста,temporary DB0. Логи `.runtime/d03-17c2-input-{red,full}.log`,
snapshot `.runtime/d03-17c2-input-runtime.json`. Чужие правки сохранены.

Это готовая граница входа, **не завершённое подключение реальной модели и не весь
C2**. Fake tokenizer/synthetic pack доказывают guards, не ONNX качество/скорость.
Нет установки dependencies, downloads, запуска весов, изменения БД или wire.
Constructor VerifiedPack — обычный record, не security capability; дальнейший
bootstrap обязан передавать только результат verifier с trusted installer pin.

Продолжаем [сквозной review fixture](d03-17c2-fixture-contract.md), затем независимый
D API. Новый engine353cfee требует явного adapter profile для partial/pairwise;
веса запрошены у Никиты без блокировки работы. Самостоятельный остаток25–40,
checkpoint не вычтен как целый C2; режим Astra сохраняется по поручению Никиты.
