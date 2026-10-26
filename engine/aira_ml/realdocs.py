"""Реальные документы требований → текст → фрагменты. Только локально: данные в aira-ml-data, наружу не уходят.

    python -m aira_ml.realdocs extract <папка_архива> <выход>

Достаёт текст из .md/.txt/.docx (абзацы, пункты списков, строки таблиц), режет на
фрагменты по абзацам и пунктам и пишет по файлу на документ + manifest с ролями и связями.
PDF и прочее пропускаются — это справочные материалы, не требования.
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_blocks(path):
    """Абзацы и строки таблиц docx в порядке следования. Заголовки помечаются «# »."""
    root = ET.fromstring(zipfile.ZipFile(path).read("word/document.xml"))
    body = root.find(f"{W}body")
    out = []

    def para_text(p):
        return "".join(t.text or "" for t in p.iter(f"{W}t")).strip()

    for el in body:
        if el.tag == f"{W}p":
            txt = para_text(el)
            if not txt:
                continue
            style = el.find(f"{W}pPr/{W}pStyle")
            sv = style.get(f"{W}val", "") if style is not None else ""
            if re.match(r"(?i)(heading|заголовок|title)", sv):
                txt = "# " + txt
            elif el.find(f"{W}pPr/{W}numPr") is not None:
                txt = "- " + txt
            out.append(txt)
        elif el.tag == f"{W}tbl":
            for tr in el.iter(f"{W}tr"):
                cells = [" ".join(para_text(p) for p in tc.iter(f"{W}p")).strip() for tc in tr.iter(f"{W}tc")]
                cells = [c for c in cells if c]
                if cells:
                    out.append(" | ".join(cells))
    return out


def md_blocks(path):
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    blocks, cur = [], []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            if cur:
                blocks.append(" ".join(cur))
                cur = []
            continue
        if re.match(r"^(#{1,6}\s|[-*+]\s|\d+[.)]\s|\|)", s):
            if cur:
                blocks.append(" ".join(cur))
                cur = []
            if re.match(r"^\|[\s:|-]+\|?$", s):     # разделитель таблицы
                continue
            blocks.append(s)
        else:
            cur.append(s)
    if cur:
        blocks.append(" ".join(cur))
    return blocks


def fragments(doc_id, blocks, min_len=25):
    """Фрагмент = абзац / пункт / строка таблицы. Короткие куски приклеиваются к следующему;
    текущий заголовок раздела сохраняется в поле section."""
    frags, section, carry = [], "", ""
    for b in blocks:
        if b.startswith("#"):
            section = b.lstrip("# ").strip()
            continue
        text = (carry + " " + b).strip() if carry else b
        if len(text) < min_len:
            carry = text
            continue
        carry = ""
        frags.append({"id": f"{doc_id}-{len(frags) + 1:03d}", "section": section, "text": text})
    if carry:
        frags.append({"id": f"{doc_id}-{len(frags) + 1:03d}", "section": section, "text": carry})
    return frags


def extract(src, dst):
    src, dst = Path(src), Path(dst)
    man = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
    dst.mkdir(parents=True, exist_ok=True)
    nfc = lambda x: unicodedata.normalize("NFC", x)
    actual = {nfc(str(f.relative_to(src))): f for f in src.rglob("*") if f.is_file()}   # архив с мака — имена в NFD
    out, skipped = [], []
    for d in man:
        p = actual.get(nfc(d["archive_path"]), src / d["archive_path"])
        ext = p.suffix.lower()
        if not p.exists():
            skipped.append((d["id"], "нет файла"))
            continue
        if ext == ".docx":
            blocks = docx_blocks(p)
        elif ext in (".md", ".txt") or ext == "":
            blocks = md_blocks(p)
        else:
            skipped.append((d["id"], ext))
            continue
        frs = fragments(d["id"], blocks)
        rec = {"id": d["id"], "title": d["title"], "role": d["role"], "family": d["family"],
               "type": d.get("document_type"), "educational": d.get("educational", False),
               "related": d.get("resolved_related_ids") or d.get("related_ids") or [],
               "n_fragments": len(frs), "chars": sum(len(f["text"]) for f in frs)}
        (dst / f"{d['id']}.json").write_text(json.dumps(rec | {"fragments": frs}, ensure_ascii=False, indent=1),
                                            encoding="utf-8")
        out.append(rec)
    (dst / "index.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out, skipped


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "extract":
        docs, skipped = extract(sys.argv[2], sys.argv[3])
        roles = {}
        for r in docs:
            roles.setdefault(r["role"], []).append(r)
        for role, rs in roles.items():
            print(f"{role}: {len(rs)} док., фрагментов {sum(r['n_fragments'] for r in rs)}")
        print("пропущено:", len(skipped), sorted({s[1] for s in skipped}))
    else:
        print(__doc__)
