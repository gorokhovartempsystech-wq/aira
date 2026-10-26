"""Генерация обучающих пространств через LLM (по умолчанию GigaChat-2-Max).

    .venv/bin/python -m aira_ml.generate --n 5

Два шага с фиксированными промптами, чтобы процесс был воспроизводим и описывался в методике:
1. фрагменты документации модуля — 40–50 штук, разные типы, статусы и связи;
2. карта фактов по готовым фрагментам — что меняем, где упомянуто, что проверить, ловушки.
Потом автоматическая проверка. Ответы LLM сохраняются в data/spaces/gen/_raw — повторный
запуск их не перезапрашивает.

Пространства из генератора — только для ОБУЧЕНИЯ (source = "synthetic-llm").
Тестовые наборы делаются отдельно и размечаются людьми.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from .llm import GigaChatBackend, load_env
from .spaces import load as load_space

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "spaces" / "gen"

DOMAINS = [
    ("bank-limits", "Банк: переводы между счетами и лимиты", "TRF"),
    ("hotel-booking", "Бронирование отелей: оплата и отмена брони", "HTL"),
    ("food-delivery", "Доставка еды: заказ, курьеры и возвраты", "FD"),
    ("online-courses", "Онлайн-курсы: доступ, дедлайны и сертификаты", "LMS"),
    ("hr-vacation", "HR-портал: заявки на отпуск и согласование", "HR"),
]

DOMAINS_MORE = [
    ("insurance-claims", "Страхование: заявления о страховом случае и выплаты", "INS"),
    ("warehouse", "Склад: приёмка, хранение и отгрузка товаров", "WH"),
    ("taxi-orders", "Такси: заказ поездки, тарифы и отмена", "TX"),
    ("telecom-tariffs", "Мобильная связь: тарифы, пакеты и списания", "TEL"),
    ("pharmacy", "Аптека: заказ лекарств, рецепты и самовывоз", "PH"),
    ("clinic-booking", "Клиника: запись к врачу, переносы и напоминания", "CL"),
    ("car-rental", "Каршеринг: бронирование, поездка и штрафы", "CR"),
    ("iot-alarm", "Автосигнализация с мобильным приложением: команды, уведомления и баланс", "IOT"),
    ("subscriptions", "Онлайн-сервис: подписки, пробный период и автопродление", "SUB"),
    ("loyalty", "Программа лояльности: баллы, уровни и списание", "LOY"),
    ("event-tickets", "Продажа билетов на мероприятия: бронь, оплата и возврат", "EVT"),
    ("rent-housing", "Аренда жилья: заявки, договор и депозит", "RNT"),
    ("school-diary", "Электронный дневник: оценки, домашние задания и уведомления родителям", "SCH"),
    ("gov-services", "Портал госуслуг: подача заявления, статусы и сроки рассмотрения", "GOV"),
    ("utilities", "ЖКХ: показания счётчиков, начисления и оплата", "UTL"),
    ("crm-leads", "CRM: заявки клиентов, распределение и SLA менеджеров", "CRM"),
    ("marketplace-sellers", "Маркетплейс: кабинет продавца, комиссии и выплаты", "MP"),
    ("airline-baggage", "Авиакомпания: регистрация, багаж и доплаты", "AIR"),
    ("fitness-club", "Фитнес-клуб: абонементы, заморозка и посещения", "FIT"),
    ("parking", "Городская парковка: оплата, зоны и штрафы", "PRK"),
    ("microloans", "Микрозаймы: заявка, скоринг и погашение", "ML"),
    ("doc-workflow", "Электронный документооборот: маршруты согласования и подписи", "EDO"),
    ("helpdesk", "Служба поддержки: обращения, приоритеты и SLA", "HD"),
    ("payroll", "Расчёт зарплаты: начисления, удержания и выплаты", "PAY"),
    ("b2b-invoices", "B2B-платформа: счета, акты и отсрочка платежа", "B2B"),
]

TYPES = ("бизнес-требование, бизнес-правило, user story, критерий приёмки, шаг use case, "
         "функциональное требование, нефункциональное требование, статусная модель, поле API, "
         "ошибка API, маппинг, текст для клиента, глоссарий, доработка, обсуждение")

PROMPT_FRAGMENTS = """Ты опытный системный аналитик. Сгенерируй фрагменты документации одного модуля так, как они лежали бы в Confluence продуктовой команды.

Модуль: {domain}
Префикс идентификаторов: {prefix}

Требования:
- 42–50 фрагментов, каждый — одно-два предложения по-русски, конкретно, с числами, названиями полей, статусов, ролей, каналов.
- Типы фрагментов: {types}. Используй большинство типов; не меньше 4 полей API, 3 текстов для клиента, 2 терминов глоссария, 1 статусной модели.
- Документы: «Бизнес-требования», «Спецификация модуля / <раздел>», «API <сервис>», «Интеграции / <система>», «Тексты для клиента», «Глоссарий», «Архив / <название> <год>», «Доработки / <номер> <название>», «Заметки к релизу».
- Статусы: active — почти все; exception — 2 правила-исключения со своей узкой областью; deprecated — 2 старые версии правил в архиве с другими значениями; delta — 1 черновик доработки, который ещё не влит; discussion — 1 фрагмент, начинающийся со «Обсуждается:».
- Одни и те же ключевые значения (сроки, лимиты, названия статусов и полей, перечни) должны повторяться в нескольких фрагментах разных типов — прямо, другими словами («две недели» вместо «14 дней») и косвенно (пример в критерии приёмки, расчёт в уведомлении, код ошибки в API).
- Добавь «ловушки»: фрагменты с похожими числами или словами, но про другой параметр или другую сущность.
- links — ID фрагментов, на которые ссылается этот (как ссылки в Confluence). Связи неполные: тексты для клиента обычно ни на что не ссылаются.
- ID вида {prefix}-BR-01, {prefix}-FR-03, {prefix}-API-02, {prefix}-TXT-01, {prefix}-ARC-01 и т.п., уникальные.

Ответь только JSON без комментариев:
{{"fragments": [{{"id": "...", "type": "...", "document": "...", "status": "active|exception|deprecated|delta|discussion", "links": ["..."], "text": "..."}}]}}"""

PROMPT_FACTS = """Ты опытный системный аналитик. Ниже фрагменты документации модуля «{domain}».

{fragments}

Выбери 8 ключевых фактов (срок, лимит, название статуса или поля, перечень значений, роль, канал и т.п.), которые упоминаются в нескольких фрагментах. Для каждого факта:
- source — ID действующего (status = active) фрагмента, где факт задан основным правилом;
- change — новый текст этого фрагмента после реалистичного изменения факта (изменить значение, переименовать, добавить или убрать элемент перечня);
- search_terms — 1–2 строки, которые аналитик ввёл бы в поиск Confluence; каждая должна дословно встречаться в тексте фрагмента source;
- mentions — ДРУГИЕ действующие фрагменты, которые после изменения нужно поправить, с видом упоминания: «прямо», «другими словами» или «косвенно»; у каждого факта не меньше 2;
- soft — фрагменты, которые стоит проверить, но править, скорее всего, не нужно (ссылка по ID, граничный пример) — можно пусто;
- traps — фрагменты, которые выглядят затронутыми, но трогать их не нужно, с причиной: «исключение», «похожий параметр», «другая сущность», «архив», «доработка», «обсуждение»; у каждого факта не меньше 1.
Один фрагмент не может быть сразу в двух списках одного факта. Используй только ID из списка выше.

Ответь только JSON без комментариев:
{{"facts": [{{"id": "F1", "name": "...", "source": "...", "change": "...", "search_terms": ["..."], "mentions": {{"ID": "прямо"}}, "soft": {{"ID": "причина"}}, "traps": {{"ID": "причина"}}}}]}}"""


def extract_json(raw):
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M)
    start = raw.find("{")
    depth = 0
    for i, ch in enumerate(raw[start:], start):
        depth += ch == "{"
        depth -= ch == "}"
        if depth == 0:
            return json.loads(raw[start:i + 1])
    raise ValueError("JSON не закрыт — ответ обрезан?")


def ask(backend, prompt, cache):
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    raw = backend.chat(prompt, max_tokens=12000, temperature=0.7)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(raw, encoding="utf-8")
    return raw


def quality(space):
    """Проверки сверх spaces.load: то, что генератор легко нарушает."""
    frag = {f["id"]: f for f in space["fragments"]}
    probs = []
    st = {}
    for f in space["fragments"]:
        st[f["status"]] = st.get(f["status"], 0) + 1
    for need in ("exception", "deprecated", "delta", "discussion"):
        if not st.get(need):
            probs.append(f"нет фрагментов со статусом {need}")
    for fact in space["facts"]:
        src = frag.get(fact["source"])
        if src and src["status"] != "active":
            probs.append(f"{fact['id']}: исходный фрагмент не действующий")
        if src and fact["change"].strip() == src["text"].strip():
            probs.append(f"{fact['id']}: изменение ничего не меняет")
        for t in fact.get("search_terms", []):
            if src and t.lower() not in src["text"].lower():
                probs.append(f"{fact['id']}: «{t}» нет в тексте исходного фрагмента")
        if len(fact.get("mentions", {})) < 2:
            probs.append(f"{fact['id']}: меньше 2 упоминаний")
        if not fact.get("traps"):
            probs.append(f"{fact['id']}: нет ловушек")
        for m in fact.get("mentions", {}):
            if m in frag and frag[m]["status"] != "active":
                probs.append(f"{fact['id']}: упоминание {m} не действующее")
    return probs


TRAP_BY_STATUS = {"deprecated": "архив", "delta": "доработка", "discussion": "обсуждение", "exception": "исключение"}
_WORD = re.compile(r"[\w%№«»-]+", re.UNICODE)


def changed_terms(old, new, k=2):
    """Слова исходного фрагмента, которых нет в новой версии, — то, что аналитик искал бы.
    Предпочтение числам и словам в кавычках или с подчёркиванием (поля, статусы)."""
    new_words = {w.lower() for w in _WORD.findall(new)}
    diff = [w for w in _WORD.findall(old) if w.lower() not in new_words and len(w) > 1]
    diff.sort(key=lambda w: (not any(c.isdigit() for c in w), "_" not in w and "«" not in w))
    return [w.strip("«»") for w in diff[:k]]


def repair(space):
    """Чинит типичные огрехи генератора по правилам. Возвращает журнал починок."""
    frag = {f["id"]: f for f in space["fragments"]}
    log, keep = [], []
    for fact in space["facts"]:
        fid = fact.get("id", "?")
        src = frag.get(fact.get("source"))
        if not src or src.get("status", "active") != "active":
            log.append(f"{fid}: удалён — исходный фрагмент отсутствует или не действует")
            continue
        seen = set()
        for group in ("mentions", "traps", "soft"):
            fixed = {}
            for i, why in (fact.get(group) or {}).items():
                if i not in frag:
                    log.append(f"{fid}: убран несуществующий {i} из {group}")
                elif i == fact["source"] or i in seen:
                    log.append(f"{fid}: убран повтор {i} из {group}")
                elif group == "mentions" and frag[i].get("status", "active") != "active":
                    fact.setdefault("traps", {})[i] = TRAP_BY_STATUS.get(frag[i]["status"], "не действует")
                    log.append(f"{fid}: {i} перенесён из упоминаний в ловушки ({frag[i]['status']})")
                else:
                    fixed[i] = why
                    seen.add(i)
            fact[group] = fixed
        terms = [t for t in fact.get("search_terms", []) if t.lower() in src["text"].lower()]
        if len(terms) < len(fact.get("search_terms", [])):
            auto = [t for t in changed_terms(src["text"], fact["change"]) if t.lower() not in map(str.lower, terms)]
            log.append(f"{fid}: слова для поиска заменены на изменившиеся: {terms + auto}")
            terms = terms + auto
        fact["search_terms"] = terms or changed_terms(src["text"], fact["change"])
        keep.append(fact)
    space["facts"] = keep
    return log


def generate(slug, domain, prefix, backend):
    raw_dir = OUT / "_raw"
    r1 = ask(backend, PROMPT_FRAGMENTS.format(domain=domain, prefix=prefix, types=TYPES),
             raw_dir / f"{slug}.fragments.txt")
    fragments = extract_json(r1)["fragments"]
    listing = "\n".join(f"{f['id']} [{f.get('type', '')}; {f.get('status', 'active')}]: {f['text']}" for f in fragments)
    r2 = ask(backend, PROMPT_FACTS.format(domain=domain, fragments=listing), raw_dir / f"{slug}.facts.txt")
    facts = extract_json(r2)["facts"]
    for f in fragments:
        f.setdefault("links", [])
        f.setdefault("status", "active")
    space = {"id": f"gen-{slug}", "domain": domain, "source": "synthetic-llm", "generator": backend.name,
             "split": "train", "note": "Сгенерировано LLM для обучения; в тест не идёт.",
             "fragments": fragments, "facts": facts}
    space["repairs"] = repair(space)
    path = OUT / f"{slug}.json"
    path.write_text(json.dumps(space, ensure_ascii=False, indent=1), encoding="utf-8")
    _, _, errors = load_space(path)
    return path, len(fragments), len(facts), errors + quality(space)


# --- режим «сначала карта, потом текст» ------------------------------------

PROMPT_PLAN = """Ты опытный системный аналитик. Модуль: «{domain}».
Предложи 8 разных ключевых фактов этого модуля, которые в настоящей документации повторяются во многих местах: сроки, лимиты и суммы, названия статусов, поля API и их значения, перечни (категории, каналы, роли), правила доступа.
Для каждого: name — короткое название; kind — срок | лимит | статус | поле | перечень | роль | канал; value — текущее значение дословно, как оно пишется в тексте (например «14 дней», «PENDING_PAYMENT», «email и SMS»); new_value — реалистичное новое значение.
Ответь только JSON: {{"facts": [{{"name": "...", "kind": "...", "value": "...", "new_value": "..."}}]}}"""

PROMPT_FACT_TEXT = """Ты опытный системный аналитик продуктовой команды. Модуль: «{domain}».
Факт: «{name}» ({kind}). Текущее значение: «{value}». Новое значение: «{new_value}».

Напиши фрагменты документации в Confluence, по одному-два предложения, конкретно, по-русски:
1. source — основное правило, где значение «{value}» написано ДОСЛОВНО; type — бизнес-правило или функциональное требование.
2. change — тот же текст source, но с новым значением «{new_value}» (остальное без изменений).
3. mentions — 5 других фрагментов разных типов, которые после изменения нужно поправить:
   - 2 с kind «прямо»: значение «{value}» встречается дословно (например, поле API, текст для клиента, статусная модель);
   - 1 с kind «другими словами»: то же значение, но иначе («две недели» вместо «14 дней», описание статуса словами и т.п.);
   - 2 с kind «косвенно»: значение не названо, но выводится (пример в критерии приёмки, расчёт в уведомлении, код ошибки, строка маппинга).
4. traps — 3 фрагмента, которые похожи, но трогать их НЕ нужно, у каждого reason:
   - «похожий параметр» — то же слово или похожее число, но другой параметр (status active);
   - «исключение» — правило-исключение со своей узкой областью и своим значением (status exception);
   - одна из причин «архив» (status deprecated, старая версия с другим значением), «доработка» (status delta, черновик) или «обсуждение» (status discussion, начинается с «Обсуждается:»).
Типы фрагментов выбирай из: {types}. document — например «Спецификация модуля / Бизнес-правила», «API <сервис>», «Тексты для клиента», «Интеграции / <система>», «Глоссарий», «Архив / Правила <год>», «Доработки / <номер>», «Заметки к релизу».

Ответь только JSON:
{{"source": {{"type": "...", "document": "...", "text": "..."}}, "change": "...",
 "mentions": [{{"type": "...", "document": "...", "kind": "прямо", "text": "..."}}],
 "traps": [{{"type": "...", "document": "...", "status": "active", "reason": "похожий параметр", "text": "..."}}]}}"""

PROMPT_FACT_TEXT_V3 = PROMPT_FACT_TEXT.replace(
    "Типы фрагментов выбирай из",
    "5. conflicts — 1 фрагмент: самостоятельное действующее правило (status active), которое значение «{value}» НЕ повторяет, "
    "но после изменения на «{new_value}» станет с ним несовместимо (например, другой лимит, срок или условие, которое новое "
    "значение нарушает). Укажи reason — в чём несовместимость.\nТипы фрагментов выбирай из").replace(
    ' "traps": [', ' "conflicts": [{{"type": "...", "document": "...", "reason": "...", "text": "..."}}],\n "traps": [')

PROMPT_FILLER = """Ты опытный системный аналитик. Модуль: «{domain}». Напиши 10 фрагментов его документации в Confluence (по одному-два предложения, разные типы: {types}), которые НЕ касаются этих фактов: {facts}. Это обычный фон документации: роли, логирование, безопасность, интерфейс, интеграции.
Ответь только JSON: {{"fragments": [{{"type": "...", "document": "...", "text": "..."}}]}}"""

TYPE_CODE = {"бизнес-требование": "BRQ", "бизнес-правило": "BR", "user story": "US", "критерий приёмки": "AC",
             "шаг use case": "UC", "функциональное требование": "FR", "нефункциональное требование": "NFR",
             "статусная модель": "SM", "поле API": "API", "ошибка API": "API", "маппинг": "MAP",
             "текст для клиента": "TXT", "глоссарий": "GL", "доработка": "DLT", "обсуждение": "DSC"}


def generate_planned(slug, domain, prefix, backend, version="v2"):
    raw = OUT / "_raw"
    fact_prompt = PROMPT_FACT_TEXT_V3 if version == "v3" else PROMPT_FACT_TEXT
    facts_plan = extract_json(ask(backend, PROMPT_PLAN.format(domain=domain), raw / f"{slug}.{version}.plan.txt"))["facts"][:8]
    for fp in facts_plan:     # LLM иногда возвращает значение списком — склеиваем в строку
        for k in ("name", "kind", "value", "new_value"):
            if isinstance(fp.get(k), list):
                fp[k] = ", ".join(map(str, fp[k]))
            fp[k] = str(fp.get(k, ""))
    counters, fragments, facts, log = {}, [], [], []

    def add(f, status="active"):
        code = TYPE_CODE.get(f.get("type", ""), "FRG")
        if status == "deprecated":
            code = "ARC"
        counters[code] = counters.get(code, 0) + 1
        fid = f"{prefix}-{code}-{counters[code]:02d}"
        fragments.append({"id": fid, "type": f.get("type", "фрагмент"), "document": f.get("document", ""),
                          "status": status, "links": [], "text": f["text"].strip()})
        return fid

    for n, fp in enumerate(facts_plan, 1):
        try:
            d = extract_json(ask(backend, fact_prompt.format(domain=domain, types=TYPES, **fp),
                                 raw / f"{slug}.{version}.fact{n}.txt"))
        except Exception as e:
            log.append(f"F{n}: ответ не разобран — {type(e).__name__}")
            continue
        src = add(d["source"])
        value = fp["value"]
        terms = [value] if value.lower() in d["source"]["text"].lower() else changed_terms(d["source"]["text"], d["change"])
        if value.lower() not in d["source"]["text"].lower():
            log.append(f"F{n}: значение «{value}» не дословно в исходном правиле — слова для поиска взяты из разницы")
        mentions, traps, conflicts = {}, {}, {}
        for m in d.get("mentions", []):
            mid = add(m)
            mentions[mid] = m.get("kind", "прямо")
            # связи как в Confluence: требования и API ссылаются на правило, тексты для клиента — нет
            if m.get("type") != "текст для клиента":
                fragments[-1]["links"].append(src)
        for c in d.get("conflicts", []) or []:
            if isinstance(c, dict) and c.get("text"):
                conflicts[add(c)] = c.get("reason", "противоречит новому значению")
        for t in d.get("traps", []):
            st = t.get("status", "active")
            st = st if st in ("active", "exception", "deprecated", "delta", "discussion") else "active"
            traps[add(t, st)] = t.get("reason", "похожий параметр")
        facts.append({"id": f"F{n}", "name": fp["name"], "source": src, "change": d["change"].strip(),
                      "search_terms": terms, "mentions": mentions, "soft": {}, "traps": traps,
                      **({"conflicts": conflicts} if conflicts else {})})
    filler = extract_json(ask(backend, PROMPT_FILLER.format(domain=domain, types=TYPES,
                                                            facts="; ".join(f["name"] for f in facts_plan)),
                              raw / f"{slug}.{version}.filler.txt"))["fragments"]
    for f in filler:
        add(f)
    import random
    random.Random(slug).shuffle(fragments)          # чтобы порядок не выдавал принадлежность к факту
    space = {"id": f"gen{version[1:]}-{slug}", "domain": domain, "source": "synthetic-llm-planned", "generator": backend.name,
             "split": "train", "note": "Сначала карта, потом текст: разметка задана планом. Только для обучения.",
             "fragments": fragments, "facts": facts}
    space["repairs"] = log + repair(space)
    path = OUT / f"{slug}-{version}.json"
    path.write_text(json.dumps(space, ensure_ascii=False, indent=1), encoding="utf-8")
    _, _, errors = load_space(path)
    return path, len(fragments), len(facts), errors + quality(space)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--planned", action="store_true", help="сначала карта, потом текст")
    ap.add_argument("--v3", action="store_true", help="planned + противоречия, все домены (DOMAINS + DOMAINS_MORE)")
    ap.add_argument("--start", type=int, default=0)
    a = ap.parse_args()
    load_env()
    import os
    os.environ["AIRA_GIGACHAT_MODEL"] = os.getenv("AIRA_GEN_MODEL", "GigaChat-2-Max")
    backend = GigaChatBackend()
    OUT.mkdir(parents=True, exist_ok=True)
    domains = (DOMAINS + DOMAINS_MORE) if a.v3 else DOMAINS
    for slug, domain, prefix in domains[a.start:a.start + a.n]:
        if a.v3 and (OUT / f"{slug}-v3.json").exists():
            print(f"{slug}: уже есть, пропуск")
            continue
        try:
            if a.v3:
                path, nf, nfact, probs = generate_planned(slug, domain, prefix, backend, "v3")
            else:
                gen = generate_planned if a.planned else generate
                path, nf, nfact, probs = gen(slug, domain, prefix, backend)
            reps = json.loads(path.read_text(encoding="utf-8")).get("repairs", [])
            print(f"{slug}: фрагментов {nf}, фактов {nfact}, починок {len(reps)}, замечаний после починки {len(probs)}")
            for p in probs[:12]:
                print("   -", p)
        except Exception as e:
            print(f"{slug}: ОШИБКА {type(e).__name__}: {str(e)[:200]}")


if __name__ == "__main__":
    main()
