"""Генератор v5 «один документ» — схема «конструктор»: корректная основа + точечные правки с известным эталоном.
Черновик материалов для П0, П5 (АР1) и П6 (АР2); эталоном он становится только после проверки двумя экспертами
(протокол запрещает брать эталон из ответа ИИ).

    python -m aira_ml.gen_doc --n 2                    # первые 2 документа по весам тем
    python -m aira_ml.gen_doc --n 40                   # весь набор (~25 вызовов GigaChat-2-Max на документ)

Почему не «одним запросом»: пробный документ 30.10 (GigaChat-2-Max, весь документ и разметка за раз) дал 24
фрагмента вместо 45–70, бессмысленные «противоречия», 17 ошибок разметки.

Шаги:
  1) основа — проверенный генератор v3 (8 фактов × источник, упоминания, ловушки, исключения, архив, черновик,
     обсуждение + фон); пишется в data/spaces/gen5/_base, НЕ в gen/ — иначе попадёт в обучение;
  2) правки — по одному короткому запросу на правку, результат проверяет программа:
     • vague    — точное значение в пункте заменяется размытым словом; цитата = найденное размытое слово;
     • missing  — из пункта убирается условие (точка отсчёта / единица или база / исполнитель / условие применения /
                  граница); какое — определяет программа по признакам в тексте; исходный текст = исправление;
                  если убранное встречается в другом действующем пункте — это missing_twin (условие задано там);
     • conflict — к правилу добавляется пункт про тот же объект и условие с несовместимым значением;
     • conflict_twin — пункт с другим числом, но совместимый (другой объект, условие, интервал или следствие);
     • vague_twin — точный пункт того же факта, рядом с размытым;
  3) «шум» реальных ТЗ — шаблонами: нормативные ссылки, условия договора, строки таблицы;
  4) проверка: ID, цитаты дословно, один пункт — одна правка, состав; запросы для АР1 (пункт → нужный контекст).
Темы взвешены по 1 798 вакансиям аналитиков: банки и финтех ~45 %, 1С/ERP ~20 % и т.д.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import random
import re
import time
from collections import Counter
from pathlib import Path

from . import generate as G

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "spaces" / "gen5"
CACHE = ROOT / "data" / "cache" / "gen5"
SLOTS = ("точка отсчёта", "единица или база", "исполнитель", "условие применения", "граница")
PLAN = {"vague": 3, "conflict": 3, "missing": 4, "conflict_twin": 3, "missing_twin": 2, "vague_twin": 1}

# (slug, отрасль, модуль, префикс, документов) — 40 документов, 22 семейства
TOPICS = [
    ("bank-credit", "банк", "Банк: онлайн-заявка на потребительский кредит и скоринг", "CRD", 3),
    ("bank-cards", "банк", "Банк: выпуск, перевыпуск и блокировка карт", "CARD", 2),
    ("bank-transfers", "банк", "Банк: переводы по СБП и лимиты операций", "SBP", 2),
    ("bank-deposits", "банк", "Банк: открытие и досрочное закрытие вкладов", "DEP", 2),
    ("bank-kyc", "банк", "Банк: удалённая идентификация клиента и проверки ПОД/ФТ", "KYC", 2),
    ("bank-mortgage", "банк", "Банк: ипотечная заявка и выдача", "MTG", 1),
    ("insurance-claims", "страхование", "Страхование: заявление о страховом случае и выплата", "INS", 2),
    ("acquiring", "финтех", "Интернет-эквайринг: платежи, возвраты и чарджбэки", "ACQ", 2),
    ("bnpl", "финтех", "Оплата частями (BNPL): одобрение, график и просрочка", "BNPL", 1),
    ("broker", "финтех", "Брокер: заявки на покупку ценных бумаг и маржинальные требования", "BRK", 1),
    ("erp-purchase", "1С/ERP", "1С:ERP: заказ поставщику, приёмка и взаиморасчёты", "PUR", 2),
    ("erp-warehouse", "1С/ERP", "1С:ERP: ордерный склад, отгрузка и инвентаризация", "WMS", 2),
    ("erp-treasury", "1С/ERP", "1С: казначейство и бюджетирование заявок на оплату", "TRS", 2),
    ("erp-payroll", "1С/ERP", "1С:ЗУП: начисление зарплаты, отпуска и больничные", "ZUP", 2),
    ("mes", "промышленность", "Промышленность: учёт выпуска продукции на линии (MES)", "MES", 2),
    ("maintenance", "промышленность", "Промышленность: плановое ТОиР оборудования и наряды", "TOR", 2),
    ("marketplace-returns", "ритейл", "Маркетплейс: возвраты товаров и компенсации продавцу", "RET", 2),
    ("loyalty", "ритейл", "Ритейл: программа лояльности, начисление и списание баллов", "LOY", 1),
    ("delivery-tracking", "логистика", "Логистика: курьерская доставка и отслеживание отправлений", "DLV", 3),
    ("telecom-tariffs", "телеком", "Мобильная связь: смена тарифа, пакеты и списания", "TEL", 2),
    ("gov-services", "госсектор", "Портал госуслуг: подача заявления и сроки рассмотрения", "GOV", 1),
    ("clinic-booking", "медицина", "Клиника: запись к врачу, переносы и напоминания", "CLN", 1),
]

# --- «шум» реальных ТЗ: шаблоны по отрасли ----------------------------------------------------------------
NORMATIVE = {
    "*": ["ГОСТ 34.602-2020 «Информационные технологии. Комплекс стандартов на автоматизированные системы. Техническое задание на создание автоматизированной системы».",
          "ГОСТ Р 59795-2021 «Информационные технологии. Комплекс стандартов на автоматизированные системы. Автоматизированные системы. Требования к содержанию документов».",
          "Федеральный закон от 27.07.2006 № 152-ФЗ «О персональных данных»."],
    "банк": ["Федеральный закон от 27.06.2011 № 161-ФЗ «О национальной платёжной системе».",
             "Положение Банка России от 17.04.2019 № 683-П об обязательных для кредитных организаций требованиях к обеспечению защиты информации."],
    "финтех": ["Федеральный закон от 27.06.2011 № 161-ФЗ «О национальной платёжной системе».",
               "Стандарт PCI DSS версии 4.0 в части хранения и передачи данных платёжных карт."],
    "страхование": ["Закон РФ от 27.11.1992 № 4015-1 «Об организации страхового дела в Российской Федерации»."],
    "госсектор": ["Федеральный закон от 27.07.2010 № 210-ФЗ «Об организации предоставления государственных и муниципальных услуг»."],
    "медицина": ["Федеральный закон от 21.11.2011 № 323-ФЗ «Об основах охраны здоровья граждан в Российской Федерации»."],
}
CONTRACT = ["Оплата работ производится Заказчиком в размере 30 % аванса в течение 10 банковских дней с даты подписания договора, остаток — в течение 15 рабочих дней с даты подписания акта сдачи-приёмки.",
            "Гарантийный срок на результаты работ составляет 12 месяцев с даты подписания Заказчиком акта сдачи-приёмки.",
            "Исполнитель обязан устранить недостатки, указанные Заказчиком в мотивированном отказе, в течение 5 рабочих дней за свой счёт."]

VAGUE_WORDS = ("быстро", "оперативно", "своевременно", "в разумный срок", "по возможности", "при необходимости",
               "достаточн", "удобн", "оптимальн", "в кратчайшие сроки", "незамедлительно", "регулярно", "и/или")

# признаки слотов: регэксп, который в пункте есть, и после правки должен исчезнуть
SLOT_MARK = {
    "точка отсчёта": r"(?i)\b(с|от) (даты|момента|дня)\b[^,.;]*|\bпосле (получения|оплаты|подачи|регистрации|подписания|создания|отправки|оформления)\b[^,.;]*",
    "единица или база": r"(?i)\d+\s?%\s+(от|с)\s[^,.;]+|\d[\d\s]*\s?(руб\w*|₽|дн\w+|час\w*|минут\w*|секунд\w*|МБ|ГБ|шт\.?|рабоч\w+ дн\w+)",
    # исполнитель — подлежащее в начале пункта, за ним (через 0–4 слова) глагол: «Менеджер по возвратам согласует…»
    "исполнитель": r"^(?:[А-ЯЁ][а-яё]+ )?(?i:менеджер\w*|оператор\w*|администратор\w*|сотрудник\w*|специалист\w*|кассир\w*|"
                   r"клиент\w*|покупател\w*|руководител\w*|бухгалтер\w*|кладовщик\w*|врач\w*)(?:\s+[^\s.,;]+){0,4}?\s+"
                   r"[а-яё]+(?:ет|ит|ют|ят)\b",
    "условие применения": r"(?i)\b(если|в случае|при условии|при наличии|при отсутствии|только для|только при)\b[^.;]*",
    "граница": r"(?i)\b(не более|не позднее|включительно|не превышающ\w+)\b[^,.;]*",
}

P_VAGUE = """Перепиши требование, заменив точное значение «{value}» размытой формулировкой, которую нельзя проверить тестом
(например: «быстро», «оперативно», «своевременно», «в разумный срок», «по возможности», «достаточное количество»).
Остальной текст оставь как есть.
Требование: «{text}»
Ответь только JSON: {{"text": "..."}}"""
P_MISSING = """Перепиши требование так, чтобы из него исчезло указание {what}: «{mark}». Не добавляй ничего взамен,
остальной текст оставь как есть, предложение должно остаться грамматически правильным.
Требование: «{text}»
Ответь только JSON: {{"text": "..."}}"""
SLOT_WHAT = {"точка отсчёта": "на момент, от которого считается срок", "единица или база": "на единицу измерения или базу расчёта",
             "исполнитель": "на того, кто выполняет действие (перепиши безлично или в пассивной форме)",
             "условие применения": "на условие, при котором действует требование", "граница": "на то, включается ли граница"}
P_CONFLICT = """Это требование из документа модуля «{module}»: «{text}»
Напиши ОДНО другое требование для раздела «{section}» про тот же самый объект и то же условие, но с несовместимым
значением вместо «{value}» — так, чтобы выполнить оба требования одновременно было невозможно. Не ссылайся на первое.
Ответь только JSON: {{"text": "...", "why": "в чём несовместимость"}}"""
P_TWIN = """Это требование из документа модуля «{module}»: «{text}»
Напиши ОДНО другое требование для раздела «{section}» с другим числом или значением, которое С НИМ СОВМЕСТИМО:
оно про другой объект, другое условие или другой интервал, либо прямо следует из этого правила (например, проверка
этого же срока в другом месте процесса). Читатель может принять пару за противоречие, но выполнить оба можно.
Ответь только JSON: {{"text": "...", "why": "почему это не противоречие"}}"""
P_GENERAL = """В документе требований к модулю «{module}» в пункте убрали указание {what}: «{mark}».
Напиши ОДНО общее правило для раздела «Общие положения», которое задаёт это для всех подобных требований документа
(например: «Все сроки в документе считаются с даты получения заказа покупателем»).
Ответь только JSON: {{"text": "..."}}"""


def llm(backend, prompt, key):
    p = CACHE / f"{key}-{hashlib.md5(prompt.encode()).hexdigest()[:8]}.txt"   # ключ зависит от запроса
    if p.exists():
        raw = p.read_text(encoding="utf-8")
    else:
        raw = backend.chat(prompt, max_tokens=600, temperature=0.4)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(raw, encoding="utf-8")
    raw = re.sub(r"(?m)^\s*//.*$", "", raw)
    return G.extract_json(raw)


def removed_part(old, new):
    """Что удалили из старого текста — по словам (по символам выходила каша)."""
    a, b = old.split(), new.split()
    sm = difflib.SequenceMatcher(None, a, b)
    return " ".join(" ".join(a[i:j]) for op, i, j, _, _ in sm.get_opcodes() if op in ("delete", "replace")).strip(" ,.")


# величина с единицей — то, что можно сделать размытым или с чем можно спорить; коды ошибок и номера не берём
QTY = re.compile(r"(?i)\b\d[\d\s]*(?:[.,]\d+)?\s?(?:%|процент\w*|руб\w*|₽|тыс\w*|млн|дн\w+|рабоч\w+ дн\w+|календарн\w+ дн\w+|"
                 r"час\w*|минут\w*|секунд\w*|сут\w*|месяц\w*|лет|год\w*|недел\w*|раз\w*|попыт\w*|шт\w*|МБ|ГБ|символ\w*|баллов|балл\w*)")
STOP = set("и в во на с со по к ко о об от до для из у за при не что как это или а также быть должен должна должно "
           "должны система системы может могут который которая которые".split())


def content_words(t):
    return {w for w in re.findall(r"[а-яёa-z]{4,}", t.lower()) if w not in STOP}


def numbers(t):
    return set(re.findall(r"\d+(?:[.,]\d+)?", t))


def regex_edit(slot, text):
    """Правки без модели для двух слотов: результат гарантирован, грамматика сохраняется."""
    if slot == "точка отсчёта":
        new = re.sub(r"(?i),?\s*\b(с|от) (даты|момента|дня)\b[^,.;]*|,?\s*\bпосле (получения|оплаты|подачи|регистрации|"
                     r"подписания|создания|отправки|оформления)\b[^,.;]*", "", text, count=1)
    elif slot == "условие применения":
        new = re.sub(r"(?i),\s*(если|в случае,? если|в случае|при условии,? что|при условии)\b[^.;]*", "", text, count=1)
    elif slot == "граница":
        new = re.sub(r"(?i)\bне более\b|\bне позднее\b|\bне превышающ\w+\b", "до", text, count=1)
        new = re.sub(r"(?i)\s*\(?включительно\)?", "", new, count=1)
    else:
        return None
    new = re.sub(r"\s{2,}", " ", new).replace(" .", ".").strip()
    return new if new != text else None


def build(backend, slug, sector, module, prefix, k):
    key = f"{slug}-{k}"
    G.OUT = OUT / "_base"                                    # основа — не в gen/, чтобы не попала в обучение
    G.OUT.mkdir(parents=True, exist_ok=True)
    path, *_ = G.generate_planned(key, module, f"{prefix}{k}", backend, "v3")
    base = json.loads(path.read_text(encoding="utf-8"))
    fr = {f["id"]: dict(f) for f in base["fragments"]}
    facts = base["facts"]
    rnd = random.Random(key)
    counters = Counter()
    order = [f["id"] for f in base["fragments"]]

    def new_id(code):
        counters[code] += 1
        return f"{prefix}{k}-{code}-{90 + counters[code]:02d}"

    def insert(f, after=None):
        fr[f["id"]] = f
        order.insert(order.index(after) + 1 if after in order else rnd.randrange(len(order) + 1), f["id"])

    taken, defects, twins, log = set(), [], [], []
    fact_frags = {fid: f for f in facts for fid in [f["source"], *f["mentions"]]}
    noise = ("глоссарий",)
    active = [i for i in order if fr[i]["status"] == "active" and fr[i].get("type") not in noise]

    def pick(cond):
        cands = [i for i in active if i not in taken and cond(fr[i])]
        rnd.shuffle(cands)
        return cands[0] if cands else None

    def ctx_of(fid):
        f = fact_frags.get(fid)
        return sorted({f["source"], *f["mentions"]} - {fid}) if f else []

    # conflict / conflict_twin — от исходных правил фактов
    # только правила с величиной: спорить и совмещать можно числа; источник — правило факта или его упоминание
    sources = [i for i in order if fr[i]["status"] == "active" and i not in taken and QTY.search(fr[i]["text"])]
    rnd.shuffle(sources)
    sections = sorted({fr[i]["document"] for i in order if fr[i].get("document")}) or ["Функциональные требования"]
    for kind, prompt in (("conflict", P_CONFLICT), ("conflict_twin", P_TWIN)):
        n = 0
        while sum(x["type"] == kind for x in defects + twins) < PLAN[kind] and sources and n < PLAN[kind] + 3:
            src = sources.pop()
            n += 1
            if src in taken:
                continue
            val = QTY.search(fr[src]["text"]).group().strip()
            sec = rnd.choice([s for s in sections if s != fr[src]["document"]] or sections)
            try:
                out = llm(backend, prompt.format(module=module, text=fr[src]["text"], section=sec, value=val), f"{key}-{kind}{n}")
            except Exception as e:
                log.append(f"{kind}{n}: {type(e).__name__}"); continue
            txt = out.get("text", "").strip()
            shared = content_words(txt) & content_words(fr[src]["text"])
            if not txt or txt == fr[src]["text"] or len(shared) < 2 or not numbers(txt) - numbers(fr[src]["text"]):
                log.append(f"{kind}{n}: не про тот же объект или без другого числа"); continue
            nid = new_id("CNF" if kind == "conflict" else "TWN")
            insert({"id": nid, "type": fr[src]["type"], "document": sec, "status": "active", "links": [], "text": txt})
            taken.update({src, nid})
            item = {"fragments": [src, nid], "needed_context": [], "why_generator": out.get("why", "")}
            if kind == "conflict":
                q = val
                defects.append({"id": f"D{len(defects) + 1}", "type": "conflict", "quote": q,
                                "explanation": out.get("why", "Два требования про один объект несовместимы."),
                                "fix": "Оставить одно значение и согласовать второе требование с ним.", **item})
            else:
                twins.append({"id": f"T{len(twins) + 1}", "type": "conflict_twin", "why": out.get("why", ""), **item})

    # vague
    for n in range(PLAN["vague"] + 8):                     # с запасом: часть правок не пройдёт проверку
        if sum(d["type"] == "vague" for d in defects) >= PLAN["vague"]:
            break
        fid = pick(lambda f: QTY.search(f["text"]))
        if not fid:
            break
        val = QTY.search(fr[fid]["text"]).group().strip()
        try:
            out = llm(backend, P_VAGUE.format(value=val, text=fr[fid]["text"]), f"{key}-vague{n}")
        except Exception as e:
            log.append(f"vague{n}: {type(e).__name__}"); continue
        txt = out.get("text", "").strip()
        word = next((w for w in VAGUE_WORDS if w in txt.lower()), None)
        num = re.match(r"\d+", val).group()
        if not word or num in numbers(txt):
            log.append(f"vague{n}: правка не прошла проверку"); taken.add(fid); continue
        q = re.search(rf"\w*{re.escape(word)}\w*", txt, re.I).group()
        defects.append({"id": f"D{len(defects) + 1}", "type": "vague", "fragments": [fid], "quote": q,
                        "needed_context": ctx_of(fid), "explanation": f"«{q}» нельзя проверить тестом: нужна измеримая граница.",
                        "fix": fr[fid]["text"], "original": fr[fid]["text"]})
        fr[fid] = dict(fr[fid], text=txt)
        taken.add(fid)
        # vague_twin: точный пункт того же факта
        if sum(t["type"] == "vague_twin" for t in twins) < PLAN["vague_twin"]:
            sib = next((i for i in ctx_of(fid) if i not in taken and fr[i]["status"] == "active"
                        and re.search(r"\d", fr[i]["text"])), None)
            if sib:
                twins.append({"id": f"T{len(twins) + 1}", "type": "vague_twin", "fragments": [sib], "needed_context": [],
                              "why": "то же правило, сформулировано измеримо — замечание о размытости не нужно"})
                taken.add(sib)

    # missing / missing_twin
    slot_cycle = list(SLOTS)
    rnd.shuffle(slot_cycle)
    need_m, need_mt = PLAN["missing"], PLAN["missing_twin"]
    need_m_start, need_mt_start = need_m, need_mt
    for n in range(30):
        if need_m <= 0 and need_mt <= 0:
            break
        # сначала дефекты (разные слоты по кругу), затем двойники
        slot = slot_cycle[n % len(slot_cycle)]
        fid = pick(lambda f: re.search(SLOT_MARK[slot], f["text"]))
        if not fid:
            continue
        mark = re.search(SLOT_MARK[slot], fr[fid]["text"]).group().strip(" ,")
        txt = regex_edit(slot, fr[fid]["text"])
        if txt is None:
            try:
                out = llm(backend, P_MISSING.format(what=SLOT_WHAT[slot], mark=mark, text=fr[fid]["text"]), f"{key}-miss{n}")
            except Exception as e:
                log.append(f"missing{n}: {type(e).__name__}"); continue
            txt = out.get("text", "").strip()
        actor = re.search(r"(?i)менеджер|оператор|администратор|сотрудник|специалист|кассир|клиент|покупател|руководител|"
                          r"бухгалтер|кладовщик|врач", mark) if slot == "исполнитель" else None
        if not txt or re.search(re.escape(mark[:25]), txt) or len(txt) < 0.5 * len(fr[fid]["text"]) \
                or (actor and actor.group().lower() in txt.lower()):
            log.append(f"missing{n}: правка не прошла проверку"); taken.add(fid); continue
        gone = removed_part(fr[fid]["text"], txt) or mark
        # «задано в другом месте» — только если там дословно есть убранная фраза (не меньше двух слов)
        probe = gone.lower() if len(gone.split()) >= 2 else mark.lower()
        elsewhere = [i for i in order if i != fid and fr[i]["status"] == "active" and probe[:40] in fr[i]["text"].lower()]
        original = fr[fid]["text"]
        taken.add(fid)
        if elsewhere:                                     # условие встречается в другом пункте — разметка двусмысленна
            log.append(f"missing{n}: убранное «{probe[:30]}» есть в {elsewhere[0]} — пропуск"); continue
        fr[fid] = dict(fr[fid], text=txt)
        # двойники чередуются с дефектами (каждая третья удачная правка), иначе до них не доходит очередь
        made = need_m_start - need_m + need_mt_start - need_mt
        if need_mt > 0 and (need_m <= 0 or made % 3 == 2):   # двойник: условие задаёт общее правило документа
            try:
                g = llm(backend, P_GENERAL.format(module=module, what=SLOT_WHAT[slot], mark=mark), f"{key}-gen{n}")
                gid = new_id("GEN")
                insert({"id": gid, "type": "бизнес-правило", "document": "Общие положения", "status": "active",
                        "links": [], "text": g["text"].strip()}, after=order[0])
                twins.append({"id": f"T{len(twins) + 1}", "type": "missing_twin", "slot": slot, "fragments": [fid],
                              "needed_context": [gid], "removed": gone, "original": original,
                              "why": f"{slot} не указано в пункте, но задано общим правилом {gid}"})
                need_mt -= 1
            except Exception as e:
                log.append(f"general{n}: {type(e).__name__}")
                fr[fid] = dict(fr[fid], text=original)
        elif need_m > 0:
            q = txt[:80] if len(txt) <= 80 else txt[:80].rsplit(" ", 1)[0]
            defects.append({"id": f"D{len(defects) + 1}", "type": "missing", "slot": slot, "fragments": [fid], "quote": q,
                            "needed_context": ctx_of(fid), "removed": gone, "original": original,
                            "explanation": f"Не указано: {slot} ({gone}).", "fix": original})
            need_m -= 1

    # шум
    for i, t in enumerate(NORMATIVE["*"] + NORMATIVE.get(sector, [])):
        insert({"id": f"{prefix}{k}-NRM-{i + 1:02d}", "type": "нормативная ссылка", "document": "Нормативные ссылки",
                "status": "active", "links": [], "text": t}, after=order[-1])
    for i, t in enumerate(CONTRACT):
        insert({"id": f"{prefix}{k}-CTR-{i + 1:02d}", "type": "условие договора", "document": "Условия договора",
                "status": "active", "links": [], "text": t}, after=order[-1])
    fields = sorted({w for f in fr.values() for w in re.findall(r"\b[a-z]+(?:_[a-z]+)+\b", f["text"])})[:4]
    for i, w in enumerate(fields):
        insert({"id": f"{prefix}{k}-TBL-{i + 1:02d}", "type": "строка таблицы", "document": "Модель данных",
                "status": "active", "links": [], "text": f"{w} | string | обязательно | см. описание в спецификации"}, after=order[-1])

    doc = {"id": f"{key}-v5", "version": "v5", "source": "synthetic-llm-v5-constructor", "generator": backend.name,
           "created": time.strftime("%Y-%m-%d"), "sector": sector, "family": slug, "module": module,
           "fragments": [fr[i] for i in order], "defects": defects, "twins": twins, "log": log + base.get("repairs", []),
           "base": str(path.relative_to(ROOT)), "expert_review": None}
    clean(doc)
    doc["errors"] = validate(doc)
    doc["queries"] = queries(doc)
    return doc


COND = re.compile(r"(?i)\b(?:если|при|в случае|при условии|когда)\b")
LIMITS = [(r"не более|не позднее|не превыша\w*|максим\w*|до\s+(?=\d)", "≤"), (r"не менее|не ранее|миним\w*", "≥"),
          (r"менее|меньше", "≤"), (r"более|больше|свыше|от\s+(?=\d)", "≥")]


def direction(t):
    """Куда ограничивает пункт: {'≤'}, {'≥'} или обе / ни одной стороны («не более» не считается за «более»)."""
    t, out = t.lower(), set()
    for pat, sign in LIMITS:
        t, n = re.subn(rf"\b(?:{pat})", " ", t)
        if n:
            out.add(sign)
    return out


def clean(doc):
    """Снять правки, которые проверка при генерации пропустила (по выборочной проверке 30.10).

    - размыто / недостающее условие в «текстах для клиента» — это не требования; правку откатываем;
    - «условие применения»: условие перефразировано, а не убрано («в случае наличия» → «при наличии»);
    - противоречие, где оба ограничения в одну сторону («менее 5 с» ↔ «менее 1 с»): оставляем, но с пометкой
      для экспертов — это скорее несогласованность, чем несовместимость.
    """
    fr = {f["id"]: f for f in doc["fragments"]}
    keep_d, keep_t = [], []
    for x in doc["defects"] + doc["twins"]:
        f = fr[x["fragments"][0]]
        drop = None
        if x["type"] in ("vague", "missing", "vague_twin", "missing_twin") and f.get("type") == "текст для клиента":
            drop = "текст для клиента — не требование"
        elif x["type"] == "missing" and x.get("slot") == "условие применения" and x.get("original") \
                and len(COND.findall(f["text"])) >= len(COND.findall(x["original"])):
            drop = "условие перефразировано, а не убрано"
        if drop:
            if x.get("original"):
                f["text"] = x["original"]
            doc["log"].append(f"чистка {x['id']} ({x['type']}): {drop}")
            continue
        if x["type"] == "conflict":
            a, b = (fr[i]["text"] for i in x["fragments"][:2])
            if direction(a) == direction(b) and len(direction(a)) == 1:
                x["hint"] = ("оба ограничения в одну сторону: выполнимы вместе, но значение задано по-разному — "
                             "противоречие или несогласованность, решает эксперт")
        (keep_d if x in doc["defects"] else keep_t).append(x)
    for i, x in enumerate(keep_d, 1):
        x["id"] = f"D{i}"
    for i, x in enumerate(keep_t, 1):
        x["id"] = f"T{i}"
    doc["defects"], doc["twins"] = keep_d, keep_t


def validate(doc):
    errors = []
    fr = {f["id"]: f for f in doc["fragments"]}
    if len(fr) != len(doc["fragments"]):
        errors.append("повторяющиеся ID")
    used = Counter()
    for x in doc["defects"] + doc["twins"]:
        bad = [i for i in x["fragments"] + x.get("needed_context", []) if i not in fr]
        if bad:
            errors.append(f"{x['id']}: нет фрагментов {bad}")
        used.update(x["fragments"])
        if x in doc["defects"] and not any(x["quote"] in fr[i]["text"] for i in x["fragments"] if i in fr):
            errors.append(f"{x['id']}: цитаты нет в тексте")
    twice = [i for i, n in used.items() if n > 1]
    if twice:
        errors.append(f"размечены дважды: {twice}")
    got = Counter(x["type"] for x in doc["defects"] + doc["twins"])
    doc["shortfall"] = {t: f"{got[t]}/{n}" for t, n in PLAN.items() if got[t] < n}   # предупреждение, не ошибка
    return errors


def queries(doc):
    """Запросы АР1: пункт → нужный контекст (у дефектов и двойников) + 5 самодостаточных пунктов без разметки."""
    marked = {i for x in doc["defects"] + doc["twins"] for i in x["fragments"]}
    out = []
    for x in doc["defects"] + doc["twins"]:
        for i in x["fragments"]:
            ctx = sorted(set(x.get("needed_context", []) + [j for j in x["fragments"] if j != i]) - {i})
            if ctx:
                out.append({"fragment": i, "needed_context": ctx, "source": x["id"], "kind": x["type"]})
    noise = ("нормативная ссылка", "условие договора", "строка таблицы", "глоссарий")
    plain = sorted((f["id"] for f in doc["fragments"] if f["id"] not in marked and f["status"] == "active"
                    and f["type"] not in noise), key=lambda i: hashlib.md5((doc["id"] + i).encode()).hexdigest())
    return out + [{"fragment": i, "needed_context": [], "source": "self-contained", "kind": "none"} for i in plain[:5]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2)
    ap.add_argument("--only", default="")
    ap.add_argument("--clean", action="store_true", help="только чистка уже собранных документов, без генерации")
    a = ap.parse_args()
    if a.clean:
        total = Counter()
        for p in sorted(OUT.glob("*-v5.json")):
            doc = json.loads(p.read_text(encoding="utf-8"))
            clean(doc)
            doc["errors"], doc["queries"] = validate(doc), queries(doc)
            p.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
            total.update(x["type"] for x in doc["defects"] + doc["twins"])
            total.update("hint" for x in doc["defects"] if x.get("hint"))
        print(f"после чистки: {dict(total)}")
        return
    from .llm import GigaChatBackend, load_env
    load_env()
    os.environ["AIRA_GIGACHAT_MODEL"] = os.getenv("AIRA_GEN_MODEL", "GigaChat-2-Max")
    backend = GigaChatBackend()
    OUT.mkdir(parents=True, exist_ok=True)
    todo = [(s, sec, m, p, k) for s, sec, m, p, cnt in TOPICS for k in range(1, cnt + 1) if not a.only or s == a.only]
    ok, total = 0, Counter()
    for slug, sector, module, prefix, k in todo[:a.n]:
        t = time.time()
        try:
            doc = build(backend, slug, sector, module, prefix, k)
        except Exception as e:
            print(f"{slug}-{k}: ошибка {type(e).__name__}: {str(e)[:150]}", flush=True)
            continue
        (OUT / f"{doc['id']}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        ok += not doc["errors"]
        c = Counter(x["type"] for x in doc["defects"] + doc["twins"])
        print(f"{doc['id']}: фрагментов {len(doc['fragments'])}, {dict(c)}, запросов {len(doc['queries'])}, "
              f"ошибок {doc['errors'][:3]} ({time.time() - t:.0f} с)", flush=True)
        total.update(c)
    print(f"готово: без ошибок структуры {ok} из {min(a.n, len(todo))}; всего {dict(total)}")


if __name__ == "__main__":
    main()
