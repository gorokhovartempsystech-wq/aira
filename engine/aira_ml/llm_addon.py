"""Замер: локальная генеративная модель как дополнение к анализатору (не замена).

    python -m aira_ml.llm_addon --gguf <путь к .gguf> [--threads 6]

А) второе мнение по кандидатам в противоречия: настоящие (синтетика v3, отложенные пространства; учебный
   пример) против трудных ложных (реальные ТЗ dedoc, где старая NLI видела противоречие; ложные из учебного
   примера). Меряем: сколько ложных модель снимает и сколько настоящих теряет.
Б) недостающее условие: 20 пунктов, написанных вручную; 10 с пробелом (точка отсчёта, единица/база,
   исполнитель, условие применения, граница), 10 определённых — в том числе через контекст.
   Меряем: верно ли решение «условие задано», называет ли вопрос нужное условие.
Ответ модели — строгий JSON (грамматика llama.cpp), температура 0. Всё локально.
"""
from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SYS = ("Ты помогаешь системному аналитику проверять требования. Отвечай только JSON. "
       "Не выдумывай факты, которых нет в тексте.")

PROMPT_CONTRA = """Два пункта из одного документа с требованиями.
А: «{a}»
Б: «{b}»
Противоречат ли они друг другу — то есть нельзя выполнить оба одновременно для одного и того же объекта и условия?
Если пункты о разных объектах, разных условиях или разных интервалах — это не противоречие.
Если разные числа следуют из одного правила (например, срок и проверка этого срока) — это не противоречие.
Ответ: {{"contradiction": true|false, "why": "одна короткая фраза"}}"""

PROMPT_SLOT = """Пункт требования: «{req}»
Контекст из того же документа:
{ctx}
Проверь, задано ли в пункте или в контексте всё, чтобы однозначно проверить требование:
точка отсчёта срока, единица или база числа, кто выполняет действие, условие применения, граница (включительно или нет).
Если чего-то не хватает — назови одно самое важное недостающее условие и задай один конкретный вопрос к заказчику.
Если всего хватает — missing = null, question = null.
Ответ: {{"missing": "точка отсчёта"|"единица или база"|"исполнитель"|"условие применения"|"граница"|null, "question": "вопрос"|null}}"""

# Б: 10 с пробелом и 10 определённых. slot — какое условие пропущено (None — всё задано).
SLOT_CASES = [
    ("Возврат товара возможен в течение 14 дней.", [], "точка отсчёта"),
    ("Система должна отправлять напоминание об оплате за 3 дня.", [], "точка отсчёта"),
    ("Скидка постоянного клиента составляет 10%.", [], "единица или база"),
    ("Размер вложения не должен превышать 20.", [], "единица или база"),
    ("Заявка на возврат должна быть согласована до перевода в статус «Одобрена».", [], "исполнитель"),
    ("Отчёт о продажах должен быть проверен перед публикацией.", [], "исполнитель"),
    ("В отдельных случаях заявку можно отправить без фотографий.", [], "условие применения"),
    ("При необходимости система блокирует учётную запись.", [], "условие применения"),
    ("К заявке можно прикрепить до 5 фотографий.", [], "граница"),
    ("Пароль должен содержать от 8 до 64 символов.", ["Пароль хранится только в виде хэша."], None),
    ("Возврат товара возможен в течение 14 дней с даты получения заказа.", [], None),
    ("Система должна отправлять напоминание об оплате за 3 дня до даты окончания резерва.", [], None),
    ("Скидка постоянного клиента составляет 10% от стоимости заказа без учёта доставки.", [], None),
    ("Размер вложения не должен превышать 20 МБ.", [], None),
    ("Менеджер по возвратам согласует заявку до перевода в статус «Одобрена».", [], None),
    ("Возврат товара возможен в течение 14 дней.", ["Все сроки в этом документе считаются с даты получения заказа покупателем."], None),
    ("Скидка постоянного клиента составляет 10%.", ["Все скидки рассчитываются от стоимости заказа без учёта доставки."], None),
    ("Заявку без фотографий можно отправить, если товар стоит меньше 1 000 рублей.", [], None),
    ("Система блокирует учётную запись после 5 неудачных попыток входа подряд.", [], None),
    ("К заявке можно прикрепить не более 5 фотографий включительно; шестая отклоняется.", [], None),
]


def contra_cases(n_pos=20, n_neg=24):
    from .train_cross import req_nli_rows
    rnd = random.Random(5)
    rows = req_nli_rows([str(ROOT / "data/spaces/gen/*-v3.json")])
    pos = [(a, b) for a, b, l, sp in rows if l == "contradiction"]
    rnd.shuffle(pos)
    pos = [("синтетика v3", a, b) for a, b in pos[:n_pos - 1]]
    pos.append(("учебный пример", "Товары, купленные со скидкой более 50%, можно вернуть в течение 7 дней с даты получения.",
                "Возврат товаров, купленных со скидкой более 50%, не допускается."))
    real = [json.loads(l) for l in open(ROOT / "data/train/nli_real_neg.jsonl", encoding="utf-8")]
    hard = [r for r in real if r["p_contra_before"] >= 0.5]
    rnd.shuffle(hard)
    neg = [("реальные ТЗ", r["a"], r["b"]) for r in hard[:n_neg - 3]]
    neg += [("учебный пример", "Дано: заказ получен 15 дней назад. Когда покупатель открывает заказ, то кнопки «Вернуть» нет.",
             "Письмо о доставке заказа: «Если товар не подошёл, вы можете вернуть его в течение 14 дней»."),
            ("учебный пример", "Дано: заказ получен 15 дней назад. Когда покупатель открывает заказ, то кнопки «Вернуть» нет.",
             "Push-уведомление на 11-й день после получения: «Осталось 3 дня, чтобы оформить возврат»."),
            ("пример из гипотезы АР1", "Система ожидает ответ платёжного провайдера не более 10 секунд.",
             "Система меняет статус платежа не позднее 3 секунд после получения ответа провайдера.")]
    return pos, neg


NO_THINK = False                                   # гибридные Qwen3 (1.7B, 8B): выключить «рассуждения» вслух


def ask(llm, prompt):
    if NO_THINK:
        prompt += " /no_think"
    t = time.time()
    r = llm.create_chat_completion(messages=[{"role": "system", "content": SYS}, {"role": "user", "content": prompt}],
                                   temperature=0, max_tokens=160, response_format={"type": "json_object"})
    txt = r["choices"][0]["message"]["content"]
    try:
        out = json.loads(txt)
    except ValueError:
        out = {"_raw": txt}
    return out, time.time() - t, r["usage"]["prompt_tokens"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gguf", required=True)
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--out", default=str(ROOT / "data/bench/llm_addon.jsonl"))
    a = ap.parse_args()
    from llama_cpp import Llama
    global NO_THINK
    NO_THINK = "qwen3-" in Path(a.gguf).name.lower() and "2507" not in Path(a.gguf).name
    t0 = time.time()
    llm = Llama(model_path=a.gguf, n_ctx=2048, n_threads=a.threads, n_gpu_layers=0, verbose=False)
    name = Path(a.gguf).name
    print(f"модель {name}, загрузка {time.time() - t0:.1f} с", flush=True)
    log = open(a.out, "a", encoding="utf-8")
    # А
    pos, neg = contra_cases()
    res = {"pos_kept": 0, "neg_removed": 0, "bad_json": 0, "sec": []}
    for kind, cases in (("pos", pos), ("neg", neg)):
        for src, x, y in cases:
            out, s, _ = ask(llm, PROMPT_CONTRA.format(a=x, b=y))
            res["sec"].append(s)
            c = out.get("contradiction")
            if not isinstance(c, bool):
                res["bad_json"] += 1
            if kind == "pos" and c is True:
                res["pos_kept"] += 1
            if kind == "neg" and c is False:
                res["neg_removed"] += 1
            log.write(json.dumps({"model": name, "task": "contra", "kind": kind, "src": src, "a": x, "b": y, "out": out,
                                  "sec": round(s, 2)}, ensure_ascii=False) + "\n")
            print(f"  [{kind}|{src}] → {c} ({s:.1f} с) {out.get('why', '')[:90]}", flush=True)
    sa = sorted(res["sec"])
    print(f"А) настоящих противоречий подтвердила {res['pos_kept']}/{len(pos)}; ложных сняла {res['neg_removed']}/{len(neg)}; "
          f"битых ответов {res['bad_json']}; медиана {sa[len(sa) // 2]:.1f} с на пару", flush=True)
    # Б
    ok = slot_ok = extra = need = found = 0
    secs = []
    for req, ctx, slot in SLOT_CASES:
        out, s, _ = ask(llm, PROMPT_SLOT.format(req=req, ctx="\n".join(f"— {c}" for c in ctx) or "— (нет)"))
        secs.append(s)
        m = out.get("missing")
        decided_missing = m not in (None, "", "null")
        if slot:
            need += 1
            ok += decided_missing
            found += decided_missing
            slot_ok += decided_missing and m == slot
        else:
            ok += not decided_missing
            extra += decided_missing
        log.write(json.dumps({"model": name, "task": "slot", "req": req, "ctx": ctx, "gold": slot, "out": out, "sec": round(s, 2)},
                             ensure_ascii=False) + "\n")
        print(f"  [{slot or 'задано'}] {req[:60]} → {m} | {str(out.get('question'))[:80]} ({s:.1f} с)", flush=True)
    sb = sorted(secs)
    print(f"Б) решение верно {ok}/{len(SLOT_CASES)}; пробел замечен {found}/{need}, нужное условие названо {slot_ok}/{need}; "
          f"лишних вопросов на определённых {extra}/{len(SLOT_CASES) - need}; медиана {sb[len(sb) // 2]:.1f} с", flush=True)
    log.close()


if __name__ == "__main__":
    main()
