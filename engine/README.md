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
