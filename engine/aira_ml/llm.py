"""Вторая ступень: классификатор пары «изменение — фрагмент» на LLM.

Одна и та же задача и один промпт для разных моделей — так их честно сравнивать (H2):
- local     — открытая модель у себя (по умолчанию Qwen3-4B-Instruct-2507, 4 бита, GPU);
- gigachat  — GigaChat API (Сбер); ключ в AIRA_GIGACHAT_AUTH, сертификат НУЦ Минцифры в AIRA_GIGACHAT_CA;
- openai    — любая OpenAI-совместимая точка (YandexGPT через совместимый API, vLLM и т.п.):
              AIRA_LLM_BASE_URL, AIRA_LLM_MODEL, AIRA_LLM_API_KEY.

Ответы кэшируются в data/cache/: повторный прогон не тратит ни деньги, ни время.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path

LABELS = {
    "противоречит": "contradiction",
    "нужно обновить": "update",
    "не трогать": "keep",
    "не связано": "unrelated",
}
FLAG = {"contradiction", "update"}          # что остаётся в выдаче аналитику

PROMPT = """Ты помогаешь системному аналитику. В документации изменили одно требование.
Нужно решить, что делать с другим фрагментом той же документации.

Варианты ответа:
- «противоречит» — фрагмент описывает правило, которое после изменения спорит с новым: оба действуют и не могут выполняться вместе;
- «нужно обновить» — фрагмент повторяет, иллюстрирует или выводит старое значение (пример, расчёт, название, перечень, маппинг, текст для клиента) и теперь устарел;
- «не трогать» — фрагмент похож, но изменение его не касается: исключение со своей областью действия, другой параметр, архивная версия, черновик доработки, обсуждение;
- «не связано» — фрагмент про другое.

Было:
{old}

Стало:
{new}

Другой фрагмент ({kind}; документ «{doc}»; статус: {status}):
{cand}

Ответь только JSON без пояснений вокруг: {{"ответ": "<один из четырёх вариантов>", "почему": "<одно предложение>"}}"""

STATUS_RU = {"active": "действует", "exception": "исключение", "deprecated": "отменено",
             "delta": "черновик доработки", "discussion": "обсуждение"}


def parse(raw):
    m = re.search(r"\{.*\}", raw, re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        d = {}
    ans = str(d.get("ответ", "")).strip().strip("«»\"").lower()
    label = next((v for k, v in LABELS.items() if ans.startswith(k)), None)
    if label is None:   # модель ответила не по формату — ищем вариант в тексте
        low = raw.lower()
        label = next((v for k, v in LABELS.items() if k in low), "unrelated")
    return label, str(d.get("почему", ""))[:300]


# --- бэкенды ---------------------------------------------------------------

class LocalBackend:
    def __init__(self, model_id=None):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        self.name = model_id or os.getenv("AIRA_LOCAL_MODEL", "Qwen/Qwen3-4B-Instruct-2507")
        self.tok = AutoTokenizer.from_pretrained(self.name)
        q = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                               bnb_4bit_compute_dtype=torch.float16)
        self.model = AutoModelForCausalLM.from_pretrained(self.name, quantization_config=q, device_map="auto")
        self.torch = torch

    def chat(self, prompt):
        enc = self.tok.apply_chat_template([{"role": "user", "content": prompt}], add_generation_prompt=True,
                                           return_tensors="pt", return_dict=True).to(self.model.device)
        with self.torch.no_grad():
            out = self.model.generate(**enc, max_new_tokens=120, do_sample=False,
                                      temperature=None, top_p=None, top_k=None,
                                      pad_token_id=self.tok.pad_token_id or self.tok.eos_token_id)
        return self.tok.decode(out[0][enc["input_ids"].shape[1]:], skip_special_tokens=True)

    def score(self, prompt, options):
        """Вероятность каждого варианта ответа: сумма логарифмов вероятностей его токенов
        после префикса {"ответ": " — так уверенность считается по самой модели, а не с её слов."""
        torch = self.torch
        base = self.tok.apply_chat_template([{"role": "user", "content": prompt}], add_generation_prompt=True,
                                            tokenize=False) + '{"ответ": "'
        base_ids = self.tok(base, return_tensors="pt", add_special_tokens=False)["input_ids"][0]
        scores = []
        for opt in options:
            opt_ids = self.tok(opt, return_tensors="pt", add_special_tokens=False)["input_ids"][0]
            ids = torch.cat([base_ids, opt_ids]).unsqueeze(0).to(self.model.device)
            with torch.no_grad():
                logits = self.model(ids).logits[0].float()
            logp = torch.log_softmax(logits, dim=-1)
            n = len(base_ids)
            scores.append(sum(logp[n - 1 + j, t].item() for j, t in enumerate(opt_ids)))
        p = torch.softmax(torch.tensor(scores), dim=0)
        return [float(x) for x in p]


class OpenAIBackend:
    def __init__(self):
        import httpx
        self.name = os.environ["AIRA_LLM_MODEL"]
        self.url = os.environ["AIRA_LLM_BASE_URL"].rstrip("/") + "/chat/completions"
        key = os.getenv("AIRA_LLM_API_KEY", "")
        self.http = httpx.Client(timeout=60, headers={"Authorization": f"Bearer {key}"} if key else {})

    def chat(self, prompt):
        r = self.http.post(self.url, json={"model": self.name, "temperature": 0,
                                           "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


class GigaChatBackend:
    OAUTH = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    CHAT = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"

    def __init__(self):
        import httpx
        self.name = os.getenv("AIRA_GIGACHAT_MODEL", "GigaChat-2")
        self.auth = os.environ["AIRA_GIGACHAT_AUTH"]          # Authorization key из личного кабинета
        self.scope = os.getenv("AIRA_GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
        ca = os.getenv("AIRA_GIGACHAT_CA")                    # путь к сертификату НУЦ Минцифры
        self.http = httpx.Client(timeout=60, verify=ca if ca else True)
        self.token, self.expires = None, 0

    def _token(self):
        if self.token and time.time() < self.expires - 60:
            return self.token
        r = self.http.post(self.OAUTH, data={"scope": self.scope},
                           headers={"Authorization": f"Basic {self.auth}", "RqUID": str(uuid.uuid4()),
                                    "Content-Type": "application/x-www-form-urlencoded"})
        r.raise_for_status()
        d = r.json()
        self.token, self.expires = d["access_token"], d["expires_at"] / 1000
        return self.token

    def chat(self, prompt, max_tokens=None, temperature=0.01):
        body = {"model": self.name, "temperature": temperature,
                "messages": [{"role": "user", "content": prompt}]}
        if max_tokens:
            body["max_tokens"] = max_tokens
        for attempt in range(6):                              # 429 — лимит запросов, ждём и повторяем
            r = self.http.post(self.CHAT, headers={"Authorization": f"Bearer {self._token()}"}, json=body,
                               timeout=300)
            if r.status_code != 429:
                break
            time.sleep(min(60, 5 * 2 ** attempt))
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


BACKENDS = {"local": LocalBackend, "openai": OpenAIBackend, "gigachat": GigaChatBackend}


class Judge:
    """Классификатор пары с кэшем ответов."""

    def __init__(self, backend, cache_dir=Path(__file__).resolve().parent.parent / "data" / "cache"):
        self.backend = backend
        self.name = backend.name
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.path = cache_dir / f"judge-{re.sub(r'[^A-Za-z0-9._-]', '_', self.name)}.json"
        self.cache = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.calls = 0
        self.seconds = 0.0

    def judge(self, old, new, frag):
        prompt = PROMPT.format(old=old, new=new, cand=frag["text"], kind=frag.get("type", "фрагмент"),
                               doc=frag.get("document", ""), status=STATUS_RU.get(frag.get("status"), "действует"))
        key = hashlib.sha1(prompt.encode()).hexdigest()
        if key not in self.cache:
            t = time.time()
            raw = self.backend.chat(prompt)
            self.seconds += time.time() - t
            self.calls += 1
            label, why = parse(raw)
            self.cache[key] = {"label": label, "why": why, "raw": raw[:500], "fragment": frag["id"]}
            self.path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=1), encoding="utf-8")
        return self.cache[key]["label"], self.cache[key]["why"]

    def proba(self, old, new, frag):
        """Вероятности четырёх вариантов {label: p}. Только для бэкендов, которые это умеют (локальная модель)."""
        if not hasattr(self.backend, "score"):
            raise NotImplementedError(f"{self.name}: оценка вероятностей недоступна")
        prompt = PROMPT.format(old=old, new=new, cand=frag["text"], kind=frag.get("type", "фрагмент"),
                               doc=frag.get("document", ""), status=STATUS_RU.get(frag.get("status"), "действует"))
        key = "p:" + hashlib.sha1(prompt.encode()).hexdigest()
        if key not in self.cache:
            t = time.time()
            ps = self.backend.score(prompt, list(LABELS))
            self.seconds += time.time() - t
            self.calls += 1
            self.cache[key] = {"proba": dict(zip(LABELS.values(), ps)), "fragment": frag["id"]}
            self.path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=1), encoding="utf-8")
        return self.cache[key]["proba"]


# Светофор: доля вероятности «затронуто» = P(противоречит) + P(нужно обновить).
RED = 0.6       # уверенно затронуто — основной список
YELLOW = 0.15   # сомнительно — «проверьте»; ниже — зелёный, «не трогать»


def light(p):
    flag = p.get("contradiction", 0) + p.get("update", 0)
    return "red" if flag >= RED else "yellow" if flag >= YELLOW else "green"


def load_env(path=Path(__file__).resolve().parent.parent / ".env"):
    """Простое чтение .env: KEY=VALUE, без перезаписи уже заданных переменных."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            if v.strip():
                os.environ.setdefault(k.strip(), v.strip())


def make_judge(kind):
    load_env()
    return Judge(BACKENDS[kind]())
