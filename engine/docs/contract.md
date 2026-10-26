# Контракт ML ↔ backend

Черновик от 04.10.2026, выведен из макета Анны. Ещё не согласован с Никитой.
Реализация — `aira_ml/schema.py`, сервис — `POST /v1/analyze`.


Поля выведены из того, что макет показывает пользователю.

**Запрос**

```json
{
  "project_id": "hotel-booking",
  "checks": ["lint", "duplicates", "contradictions"],
  "target": { "requirement_id": "REQ-128", "version": 7 },
  "change": { "requirement_id": "REQ-128", "old_text": "…", "new_text": "…" },
  "requirements": [
    {
      "id": "REQ-072", "version": 3, "title": "Таймаут платёжного провайдера",
      "section": "2.3 Оплата", "text": "…",
      "status": "active",
      "links": ["REQ-128"]
    }
  ]
}
```

`status`: `active` | `deprecated` | `exception` | `discussion` — без него гипотезу
не проверить. `change` — пусто для обычной проверки, заполнено для сценария
изменения.

**Ответ**

```json
{
  "model_version": "req-ml 0.1 / USER-bge-m3 / <LLM-снимок>",
  "issues": [
    {
      "id": "iss-1",
      "type": "contradiction",
      "severity": "critical",
      "requirement_id": "REQ-128",
      "span": { "start": 112, "end": 158, "quote": "быстро обрабатывает ответ…" },
      "related": {
        "requirement_id": "REQ-072", "version": 3, "status": "active",
        "quote": "таймаут ответа — 10 секунд"
      },
      "explanation": "Два требования задают несовместимые ограничения: 3 с и 10 с.",
      "rule": "ISO/IEC/IEEE 29148: непротиворечивость набора",
      "suggestion": null,
      "score": 0.87
    },
    {
      "id": "iss-2",
      "type": "lint",
      "severity": "warning",
      "requirement_id": "REQ-128",
      "span": { "start": 120, "end": 126, "quote": "быстро" },
      "explanation": "Наречие «быстро» не проверяемо.",
      "rule": "ISO/IEC/IEEE 29148: проверяемость",
      "suggestion": { "before": "быстро обрабатывает ответ", "after": "обрабатывает ответ не позднее 3 секунд" }
    }
  ],
  "skipped": [ { "check": "contradictions", "reason": "LLM недоступна — показаны только кандидаты" } ]
}
```

- `span` — позиции символов в тексте требования: макет подсвечивает фрагмент прямо в тексте.
- `related.quote` — второй фрагмент-основание: карточка гипотезы требует два фрагмента.
- `skipped` — честная деградация: как `NullGateway` в пайплайне, без LLM отдаём то, что можем.
- Решения «Применить / Отклонить / Сравнить» хранит backend (история решений у Никиты уже есть) —
  это же будущая разметка для оценки качества.
