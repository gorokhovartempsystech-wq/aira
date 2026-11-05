# D03-17C2 — граница пакета модели и токенизации

3 ноября 2026, после F3 `9e5ec9f`. F06–F08 текущего продукта. Продолжаем
самостоятельно на Astra по последнему поручению Никиты. Этот checkpoint C2
проверяет данные перед inference; он не объявляет реальные веса/качество/установщик
готовыми. Новых продуктовых функций и HTTP endpoints нет.

## Проверенные основания и граница с ML

GitHub доступен. Прочитан commit
[`353cfee98b1cc9db92b1251dc0f59beeb5b8717b`](https://github.com/gorokhovartempsystech-wq/aira/commit/353cfee98b1cc9db92b1251dc0f59beeb5b8717b):
engine.py blob `26d5cbbcb83455d8be08e568d814e8571b3df9ee`, pack.py blob
`9912515b5e0f5d876963f3e3e858fd90374c51d3`. Это read-only аудит, remote не менялся.
README говорит о пакете 0.2m и отдельной передаче весов; самих весов здесь нет.

Onnx.run всё ещё включает truncation256. Новый review добавляет partial и
checked.pairwise, фильтрует часть fragments из pairwise analysis, хотя engine
version осталась0.1.0. Старый B1 требует exact complete reply. Нельзя молча
удалить новые поля/скрыть пропуски или объявить partial успехом. Нужны проверенный
пакет и отдельное согласование нового adapter profile; существующие B1/F3/native
contracts этим checkpoint не меняются. По прежнему решению Никиты отсутствие
модели не останавливает независимую разработку.

## API пакета — без чтения файлов и импорта ML

Новый namespace `ara.docx_analysis_worker.model_input` с `__init__.py`,
`_pack.py`, `_tokens.py`, `_errors.py`. Только stdlib. Import/construction
не запускают threads, SQL, OS processes, сеть и не читают секреты/файлы.

`verify_pack(manifest: bytes, files: dict[str,bytes], *, expected_sha256: str)
-> VerifiedPack` проверяет exact bytes SHA manifest и каждого файла. Expected
digest даёт trusted installer/bootstrap, не сам manifest или пользовательский
HTTP запрос. Проверенный результат содержит immutable byte references и safe
metadata; repr не показывает manifest/model/tokenizer contents. Выданные bytes
не могут измениться после hash check. Helper не принимает paths/URL/callback.

Формат соответствует pack.py: name=aira-models, version (1..128), built/runtime
строки, models с embedder/pair/nli, files, total_mb. JSON strict UTF-8, без
duplicate keys/NaN/Infinity, глубина≤16, manifest≤1MiB. Не навязывать training
metadata структуру сверх bounded JSON. labels nli ровно entailment,neutral,
contradiction в этом порядке; pair содержит ровно keep/unrelated/update/
contradiction без повторов, порядок сохраняется. Temperature finite positive.
Лицензии — непустая metadata, не доказательство разрешения распространения.

Файлы только в embedder/pair/nli и только: model.int8.onnx, tokenizer.json,
config.json, tokenizer_config.json, special_tokens_map.json, added_tokens.json,
vocab.txt. Первые два обязательны в каждой папке. Exact files set, без traversal,
absolute/backslash/case aliases. До32 files, один≤512MiB, сумма≤1GiB,
tokenizer.json≤16MiB. Limits — техническая граница verifier, не обещание RAM
инференса и не продуктовый лимит документа. Без распаковки архивов/downloader.
total_mb совпадает с round(sum(bytes)/1e6,1). Manifest version не заменяет digest.

## Токены — один и тот же encoding для проверки и inference

`encode_batches(tokenizer, left, right=None, *, batch_size=32)` возвращает tuple
`TokenBatch(input_ids,attention_mask,token_type_ids)` из immutable tuples.
Tokenizer — trusted per-attempt backend (tests явно synthetic), не capability
доказательства качества. Списки/tuple строк, right той же длины, без zip truncation;
≤4096 пар/строк, суммарно≤2M codepoints, строки не trim/normalize/split.
Batch size целое1..32, bool запрещён.

Перед encode: no_truncation/no_padding, затем подтверждение обеих properties=None.
Один encode_batch всего фактически вызванного runner input, add_special_tokens=True;
после encode ещё раз проверить отсутствие truncation/padding. Переполнение или
неправильный tokenizer shape — safe error, ни одного inference. Проверять каждый
encoding:1..256 ids вместе со specials, overflowing пуст, ids и type_ids целые
неотрицательные≤2**31-1 (bool запрещён), attention_mask целиком1, одинаковые длины.
PAD token `[PAD]` должен иметь valid ID. Padding собственный, до max длины только
данного batch: PAD IDs, mask0, type_ids0, никогда более256.

`run_guarded(tokenizer, infer_batch, concatenate, left, right=None,
*, batch_size=32)` сначала полностью encode/validate, затем передаёт **те же**
TokenBatch в trusted infer callback. Не вызывать старый Onnx.run, который заново
токенизирует/обрезает. Возвращает concatenate(tuple(outputs)), включая пустой tuple
для пустого input; zero inputs не вызывают tokenizer/inference. Callback errors
становятся safe adapter_error без private strings. Token overflow даёт
model_input_limit_exceeded; malformed tokenizer/encoding — model_unavailable;
bad caller input — invalid_input. No successful partial result.

## Приёмка и следующий шаг

Новые independent files `tests/acceptance/test_docx_model_pack.py` и
`test_docx_model_tokens.py`: strict manifest/digests/labels/paths/immutable output,
special tokens256/257, пары в обоих направлениях, tail overflow до inference,
Unicode/whitespace сохранены, пустые inputs, padding exact batch, tokenizer не
снимает truncation/overflow/malformed shapes, private errors без утечки. Все
данные synthetic, fake tokenizer не называется реальной моделью.

Freeze→red→source→targeted→полный check→result/local commit. Старые tests/source,
DB/runner/contracts/dependencies не меняются. Настоящие ONNX buffers, pinned
engine import и child wiring требуют отдельного следующего checkpoint C2 после
этого слоя; C2 целиком не закрывать только по verifier/token tests. Самостоятельный
остаток пока25–40, checkpoint не вычитается как целый C2 и не добавляет новый ID.
