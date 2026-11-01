# ML-часть AIRA

Актуальный CPU-движок — `aira_ml.engine`, браузерный прототип — `aira_ml.proto`. Рабочий пакет 0.2m: исходный rubert-tiny2, pair2 и nli5. Веса передаются отдельно; опубликованный Release пока не гарантирован.

```bash
pip install -r requirements-engine.txt -r requirements-test.txt
python -m pytest -q
python -m aira_ml.proto --models /path/to/models-0.2m --port 8780
python -m aira_ml.engine serve --models /path/to/models-0.2m --port 0
```

Рантайм: numpy, tokenizers, onnxruntime, без PyTorch. DOCX-парсер использует стандартную библиотеку. Для обучения и экспорта нужны `requirements-train.txt`; для таблиц экспертной разметки дополнительно `openpyxl`.

## Исследовательские модули

- `train_cross`, `train_emb`, `pack`: обучение классификаторов, эмбеддера и ONNX-пакеты.
- `nli_eval`, `engine_eval`, `realtz`, `gen5_eval`: внешние и синтетические проверки.
- `branches`, `decomp`, `gen_doc`, `gen_doc_export`: генерация и подготовка материалов; v5 требует экспертов.
- `llm_addon`: сравнение локальных LLM, эксперимент вне основного конвейера.

Генераторы могут обращаться к внешнему API и требуют отдельной настройки `.env`; документы клиентов в них передавать нельзя. Внешние корпуса и реальные отрицательные пары остаются локально. Старые модули `service`, `analyze`, `select` сохранены для прежних экспериментов; основной контракт desktop-движка — `../contracts/engine-api.md`.

## Ограничения качества

v3a/v3b не заменили pair2. Дообученный эмбеддер не улучшил итог на наборе настройки. nli5 снижает шум на реальных ТЗ, но теряет часть противоречий и не заменяет экспертное ревью. Набор «Возвраты» многократно использовался для настройки. Результаты на нём и слабая автоматическая разметка не подтверждают гипотезы АР1/АР2.


## Архив описания прежнего сервиса

# aira-ml

ML-модуль AI Requirements Assistant (AIRA): линтинг формулировок, поиск дублей
и противоречий при изменении требования. Отдаёт ответ в формате, который
показывает интерфейс (макет Анны от 04.10), и заменяет fixture в backend.

Часть Артёма Горохова (NLP/ML), команда С15, МФТИ, трек «Стартап», НИР 3.

## Запуск

```bash
cd /root/Личное/aira-ml
.venv/bin/python -m pytest -q                                   # тесты без модели и LLM
.venv/bin/python -m aira_ml.evaluate data/packets --details      # замер гипотезы
.venv/bin/uvicorn aira_ml.service:app --port 8090                # сервис для backend
```

Сервис: `GET /health`, `POST /v1/analyze` — контракт в [docs/contract.md](docs/contract.md).

LLM подключается переменными окружения (любая OpenAI-совместимая точка входа):
`AIRA_LLM_BASE_URL`, `AIRA_LLM_MODEL`, `AIRA_LLM_API_KEY`. Без них противоречия
ищет эвристика по числам и единицам, а ответ помечает это в `skipped`.

## Устройство

```
aira_ml/schema.py     контракт и формат пакетов данных
aira_ml/lint.py       правила ISO/IEC/IEEE 29148 (неизмеримое, оговорки, открытые перечни, и/или)
aira_ml/embed.py      USER-bge-m3 (GPU) или TF-IDF без модели
aira_ml/select.py     отбор контекста: similarity и structured — переменная эксперимента
aira_ml/classify.py   классификатор пары: LLM или эвристика
aira_ml/analyze.py    сборка ответа по контракту
aira_ml/service.py    FastAPI
aira_ml/evaluate.py   метрики и бутстреп по пакетам
data/packets/         калибровочные пакеты (синтетика, dev)
docs/                 контракт, правила разметки, протокол и журнал эксперимента
```

## Документы

- [docs/experiment.md](docs/experiment.md) — гипотеза, метрики, журнал прогонов
- [docs/annotation-guide.md](docs/annotation-guide.md) — правила разметки
- [docs/contract.md](docs/contract.md) — формат запроса и ответа

Исследовательские заметки — в Obsidian-vault: `2 Проекты/Стартап AI Requirements Assistant/`.

---

## Движок для десктопа (с 25.10.2026)

Рантайм без PyTorch: `aira_ml/engine.py` (onnxruntime + tokenizers + numpy). Контракт —
`../contracts/engine-api.md`.

```bash
pip install -r requirements-engine.txt
python -m aira_ml.engine serve  --models ../models/models-0.1          # для приложения
python -m aira_ml.engine review  документ.md --models ../models/models-0.1
python -m aira_ml.engine impact  документ.md --id F001 --new "новый текст" --models ../models/models-0.1
```

**Пакет моделей** (~400 МБ, ONNX int8) в git не хранится — скачать из GitHub Releases
(`models-0.1.zip`) и распаковать в `../models/`. В пакете `manifest.json`: версии, sha256,
лицензии, метки классов, температура калибровки.

**Обучение и сборка пакета** — только у ML, нужна видеокарта:

```bash
pip install -r requirements-train.txt
python -m aira_ml.train_cross nli     --base ai-forever/ruBert-base --out models/nli-rubert-base
python -m aira_ml.train_cross nli-req --init models/nli-rubert-base --out models/nli2-rubert-base
python -m aira_ml.train_cross pairs   --init models/nli-rubert-base --out models/pair1-rubert-base \
    --pairs data/train/pairs_v2.jsonl data/train/pairs_c.jsonl data/train/pairs_v3.jsonl
python -m aira_ml.pack --pair models/pair1-rubert-base --nli models/nli2-rubert-base --out dist/models-0.1
```

Журнал экспериментов — `docs/experiment.md`. Данные: `data/spaces/` — синтетические пространства
(происхождение — `data/spaces/gen/PROVENANCE.md`), `data/train/` — пары после проверки учителем.
Реальные документы компаний сюда не кладём (см. `../docs/decisions/0004-real-data-local-only.md`).

**Песочница** — страница в браузере поверх движка, пока нет приложения:

```bash
python -m aira_ml.playground --models ../models/models-0.1   # открыть http://127.0.0.1:8770
```

Вставить требования → «Ревью»; «Разобрать на пункты» → выбрать пункт → поправить →
«Проверить влияние правки». Только для демо: слушает 127.0.0.1, без токена.
