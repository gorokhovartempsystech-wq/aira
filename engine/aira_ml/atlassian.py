"""Коннектор AIRA к Confluence и Jira (Cloud: REST + API-токен) — тестовый стенд «ревью доработки».

    python -m aira_ml.atlassian check-access                  # проверить доступ (ключи из .env)
    python -m aira_ml.atlassian seed-confluence data/spaces/vozvraty.json
    python -m aira_ml.atlassian seed-jira data/spaces/vozvraty.json --facts F1 F4
    python -m aira_ml.atlassian check AIRA-1                  # проверить одну доработку
    python -m aira_ml.atlassian watch                         # опрашивать Jira и проверять новые доработки

Как это работает:
1. Индекс. Читаем все страницы пространства Confluence, режем на фрагменты по
   абзацам вида «[ID] текст». Статус фрагмента берём из меток страницы
   (архив / черновик-доработки / обсуждение). Связи — упоминания ID в тексте.
2. Доработка — задача Jira с меткой `aira`. В описании строки «Было: …» и «Стало: …»
   (так пишут change request). Исходный фрагмент ищем по тексту «Было».
3. Ступень 1 — слова, которые исчезли при правке, плюс смысл (USER-bge-m3), без
   архива, черновиков и обсуждений. Ступень 2 — классификатор пары (GigaChat или
   локальная модель). Светофор: 🔴 классификатор пометил, 🟡 он не пометил, но
   нашёл поиск по словам.
4. Результат — комментарий в задаче со ссылками на страницы Confluence.

Ключи — только в .env: AIRA_ATLASSIAN_SITE (https://<имя>.atlassian.net),
AIRA_ATLASSIAN_EMAIL, AIRA_ATLASSIAN_TOKEN, AIRA_CONFLUENCE_SPACE (ключ пространства),
AIRA_JIRA_PROJECT (ключ проекта). Только синтетические и публичные данные:
рабочие документы сюда не загружать.
"""
from __future__ import annotations

import argparse
import difflib
import html
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

from .llm import FLAG, load_env

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "data" / "cache" / "atlassian-state.json"
STATUS_LABEL = {"deprecated": "архив", "delta": "черновик-доработки", "discussion": "обсуждение"}
LABEL_STATUS = {v: k for k, v in STATUS_LABEL.items()}
TRIGGER = "aira"
MARK = "AIRA · ревью доработки"
_FRAG = re.compile(r"^\s*\[([A-ZА-Я0-9][\w-]*)\]\s*(.+)$", re.S)
_ID = re.compile(r"\b[A-ZА-Я]{2,4}(?:-[A-ZА-Я]{2,4})?-\d{2}(?:-[A-Z]\d)?\b")


class Atlassian:
    def __init__(self):
        load_env()
        miss = [k for k in ("AIRA_ATLASSIAN_SITE", "AIRA_ATLASSIAN_EMAIL", "AIRA_ATLASSIAN_TOKEN") if not os.getenv(k)]
        if miss:
            sys.exit("Не заданы в .env: " + ", ".join(miss))
        self.site = os.environ["AIRA_ATLASSIAN_SITE"].rstrip("/")
        self.space_key = os.getenv("AIRA_CONFLUENCE_SPACE", "")
        self.project = os.getenv("AIRA_JIRA_PROJECT", "")
        self.http = httpx.Client(base_url=self.site, timeout=60,
                                 auth=(os.environ["AIRA_ATLASSIAN_EMAIL"], os.environ["AIRA_ATLASSIAN_TOKEN"]),
                                 headers={"Accept": "application/json"})

    def req(self, method, url, **kw):
        for attempt in range(5):
            r = self.http.request(method, url, **kw)
            if r.status_code != 429:
                break
            time.sleep(float(r.headers.get("Retry-After", 2 ** attempt)))
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {url} → {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else {}

    # --- Confluence ---------------------------------------------------------

    def space_id(self):
        d = self.req("GET", "/wiki/api/v2/spaces", params={"keys": self.space_key})
        if not d.get("results"):
            sys.exit(f"Пространство {self.space_key} не найдено или нет доступа")
        return d["results"][0]["id"], d["results"][0].get("homepageId")

    def pages(self):
        sid, _ = self.space_id()
        out, url, params = [], f"/wiki/api/v2/spaces/{sid}/pages", {"body-format": "storage", "limit": 100}
        while url:
            d = self.req("GET", url, params=params)
            out += d["results"]
            url, params = d.get("_links", {}).get("next"), None
            if url and url.startswith("/wiki") is False:
                url = "/wiki" + url
        for p in out:
            p["labels"] = [l["name"] for l in self.req("GET", f"/wiki/api/v2/pages/{p['id']}/labels")["results"]]
        return out

    def create_page(self, space_id, title, body, parent=None):
        data = {"spaceId": space_id, "status": "current", "title": title,
                "body": {"representation": "storage", "value": body}}
        if parent:
            data["parentId"] = parent
        return self.req("POST", "/wiki/api/v2/pages", json=data)

    def add_labels(self, page_id, labels):
        if labels:
            self.req("POST", f"/wiki/rest/api/content/{page_id}/label",
                     json=[{"prefix": "global", "name": l} for l in labels])

    def page_url(self, page):
        return self.site + "/wiki" + page["_links"]["webui"]

    # --- Jira ---------------------------------------------------------------

    def issue_type(self):
        d = self.req("GET", f"/rest/api/2/issue/createmeta/{self.project}/issuetypes")
        types = [t for t in d.get("issueTypes", d.get("values", [])) if not t.get("subtask")]
        return next((t for t in types if t["name"] in ("Task", "Задача")), types[0])["id"]

    def create_issue(self, summary, description, labels):
        return self.req("POST", "/rest/api/2/issue", json={"fields": {
            "project": {"key": self.project}, "summary": summary, "description": description,
            "issuetype": {"id": self.issue_type()}, "labels": labels}})

    def issue(self, key):
        return self.req("GET", f"/rest/api/2/issue/{key}", params={"fields": "summary,description,labels,comment"})

    def search(self, jql):
        d = self.req("POST", "/rest/api/3/search/jql", json={"jql": jql, "fields": ["summary", "labels"], "maxResults": 50})
        return d.get("issues", [])

    def comment(self, key, body):
        return self.req("POST", f"/rest/api/2/issue/{key}/comment", json={"body": body})


# --- пространство ↔ страницы -----------------------------------------------

def to_storage(frags):
    rows = []
    for f in frags:
        prefix = "Исключение. " if f.get("status") == "exception" else ""
        links = f" <em>Связано: {', '.join(f['links'])}.</em>" if f.get("links") else ""
        rows.append(f"<p><strong>[{html.escape(f['id'])}]</strong> <em>({html.escape(f['type'])})</em> "
                    f"{prefix}{html.escape(f['text'])}{links}</p>")
    return "\n".join(rows)


def from_storage(page):
    """Фрагменты страницы: абзацы вида «[ID] (тип) текст»."""
    body = page.get("body", {}).get("storage", {}).get("value", "")
    status = next((LABEL_STATUS[l] for l in page.get("labels", []) if l in LABEL_STATUS), "active")
    out = []
    for p in re.findall(r"<p>(.*?)</p>", body, re.S):
        txt = html.unescape(re.sub(r"<[^>]+>", "", p)).strip()
        m = _FRAG.match(txt)
        if not m:
            continue
        rest = m.group(2)
        kind = re.match(r"\(([^)]+)\)\s*", rest)
        text = rest[kind.end():] if kind else rest
        rel = re.search(r"\s*Связано: ([^.]+)\.\s*$", text)
        links = [x.strip() for x in rel.group(1).split(",")] if rel else []
        text = text[:rel.start()] if rel else text
        st = "exception" if text.startswith("Исключение. ") and status == "active" else status
        out.append({"id": m.group(1), "type": kind.group(1) if kind else "фрагмент", "document": page["title"],
                    "status": st, "text": text.removeprefix("Исключение. "), "page_id": page["id"],
                    "links": sorted((set(links) | set(_ID.findall(text))) - {m.group(1)})})
    return out


def seed_confluence(a, space_path):
    space = json.loads(Path(space_path).read_text(encoding="utf-8"))
    sid, home = a.space_id()
    docs = {}
    for f in space["fragments"]:
        docs.setdefault(f["document"], []).append(f)
    existing = {p["title"]: p for p in a.pages()}
    root_title = f"Модуль «{space.get('domain', space['id'])}» — документация"
    root = existing.get(root_title) or a.create_page(sid, root_title,
        "<p>Тестовое пространство AIRA. Синтетические данные. Каждый абзац — фрагмент требования с ID.</p>", home)
    made = 0
    for title, frags in docs.items():
        if title in existing:
            continue
        page = a.create_page(sid, title, to_storage(frags), root["id"])
        statuses = {f["status"] for f in frags}
        a.add_labels(page["id"], [STATUS_LABEL[s] for s in statuses if s in STATUS_LABEL])
        made += 1
        print("  +", title, flush=True)
    print(f"страниц создано: {made}, уже было: {len(docs) - made}")


def seed_jira(a, space_path, fact_ids):
    space = json.loads(Path(space_path).read_text(encoding="utf-8"))
    frag = {f["id"]: f for f in space["fragments"]}
    for fact in space["facts"]:
        if fact_ids and fact["id"] not in fact_ids:
            continue
        old = frag[fact["source"]]["text"]
        desc = (f"Доработка по требованию {fact['source']}.\n\n"
                f"Было: {old}\nСтало: {fact['change']}\n\n"
                f"Нужно учесть изменение во всех связанных документах.")
        d = a.create_issue(f"Доработка: {fact['name']} — изменение", desc, [TRIGGER])
        print("  +", d["key"], fact["name"])


# --- ревью доработки --------------------------------------------------------

def parse_change(description):
    old = re.search(r"Было:\s*(.+?)(?:\n|$)", description or "")
    new = re.search(r"Стало:\s*(.+?)(?:\n|$)", description or "")
    return (old.group(1).strip() if old else None), (new.group(1).strip() if new else None)


def review(a, key, judge_kind="gigachat", k=8, post=True):
    from . import spaces
    from .embed import STEmbedder
    from .generate import changed_terms
    from .llm import make_judge

    issue = a.issue(key)
    f = issue["fields"]
    old, new = parse_change(f.get("description"))
    if not old or not new:
        return a.comment(key, f"{MARK}\nНе нашла в описании строки «Было: …» и «Стало: …» — не понимаю, что меняется.") if post else None
    pages = a.pages()
    frags = [x for p in pages for x in from_storage(p)]
    frag = {x["id"]: x for x in frags}
    url = {p["id"]: a.page_url(p) for p in pages}
    src = max(frags, key=lambda x: difflib.SequenceMatcher(None, x["text"], old).ratio())
    fact = {"source": src["id"], "change": new, "search_terms": changed_terms(old, new) or [old[:30]]}
    cands = spaces.plus_statuses(fact, frag, STEmbedder(), k)
    lit = set(spaces.words(fact, frag))
    judge = make_judge(judge_kind)
    red, yellow = [], []
    for i in cands:
        label, why = judge.judge(old, new, frag[i])
        if label in FLAG:
            red.append((i, label, why))
        elif i in lit:
            yellow.append((i, label, why))
    skipped = sum(1 for x in frags if x["status"] in spaces.SKIP_STATUSES)

    def line(i, why):
        x = frag[i]
        return f"* [{x['document']}|{url[x['page_id']]}] *{i}* ({x['type']}): {{quote}}{x['text']}{{quote}} _{why}_"

    lab = {"contradiction": "противоречит", "update": "нужно обновить"}
    body = [f"*{MARK}*", f"Изменение в *{src['id']}* ({src['document']}): «{old}» → «{new}»", ""]
    body.append(f"🔴 *Затронуто — {len(red)}*" if red else "🔴 Затронутых мест не нашла.")
    body += [line(i, f"{lab[l]}: {w}") for i, l, w in red]
    if yellow:
        body += ["", f"🟡 *Проверьте — {len(yellow)}* (совпадает по словам, но модель считает, что можно не трогать)"]
        body += [line(i, w) for i, _, w in yellow]
    body += ["", f"Проверено: {len(pages)} страниц пространства {a.space_key}, {len(frags)} фрагментов; "
                 f"{skipped} в архиве, черновиках и обсуждениях не предлагались. Классификатор: {judge.name}."]
    text = "\n".join(body)
    if post:
        a.comment(key, text)
    return text


def watch(a, judge_kind, every=30):
    done = set(json.loads(STATE.read_text())) if STATE.exists() else set()
    print(f"слежу за {a.project}: задачи с меткой «{TRIGGER}», раз в {every} с. Ctrl+C — стоп", flush=True)
    while True:
        try:
            for it in a.search(f'project = "{a.project}" AND labels = "{TRIGGER}" ORDER BY created DESC'):
                if it["key"] in done:
                    continue
                comments = a.issue(it["key"])["fields"].get("comment", {}).get("comments", [])
                if not any(MARK in (c.get("body") or "") for c in comments):
                    print("проверяю", it["key"], flush=True)
                    review(a, it["key"], judge_kind)
                done.add(it["key"])
                STATE.parent.mkdir(parents=True, exist_ok=True)
                STATE.write_text(json.dumps(sorted(done)))
        except (httpx.HTTPError, RuntimeError) as e:     # сеть пропала или API ответил ошибкой — ждём и пробуем снова
            print(f"{time.strftime('%H:%M:%S')} ошибка, повтор через {every} с: {type(e).__name__}: {str(e)[:120]}", flush=True)
        time.sleep(every)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check-access")
    s = sub.add_parser("seed-confluence"); s.add_argument("space")
    s = sub.add_parser("seed-jira"); s.add_argument("space"); s.add_argument("--facts", nargs="*")
    s = sub.add_parser("check"); s.add_argument("key"); s.add_argument("--judge", default="gigachat"); s.add_argument("--dry", action="store_true")
    s = sub.add_parser("watch"); s.add_argument("--judge", default="gigachat"); s.add_argument("--every", type=int, default=30)
    s = sub.add_parser("read")
    x = ap.parse_args()
    a = Atlassian()
    if x.cmd == "check-access":
        me = a.req("GET", "/rest/api/2/myself")
        print("Jira: вход выполнен; проект", a.project or "—")
        if a.space_key:
            sid, _ = a.space_id()
            print("Confluence: пространство", a.space_key, "найдено")
        if a.project:
            print("Jira: тип задачи для доработок", a.issue_type())
        print("аккаунт активен:", me.get("active"))
    elif x.cmd == "seed-confluence":
        seed_confluence(a, x.space)
    elif x.cmd == "seed-jira":
        seed_jira(a, x.space, x.facts)
    elif x.cmd == "read":
        frags = [f for p in a.pages() for f in from_storage(p)]
        print(f"фрагментов: {len(frags)}; по статусам:",
              {s: sum(f['status'] == s for f in frags) for s in {f['status'] for f in frags}})
    elif x.cmd == "check":
        print(review(a, x.key, x.judge, post=not x.dry))
    elif x.cmd == "watch":
        watch(a, x.judge, x.every)


if __name__ == "__main__":
    main()
