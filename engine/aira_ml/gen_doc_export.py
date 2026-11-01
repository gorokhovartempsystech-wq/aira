"""Пакет для экспертной проверки набора v5: документы в .docx и таблица разметки для двух экспертов.

    uv run --with openpyxl python -m aira_ml.gen_doc_export      # из корня aira-ml (нужен openpyxl)

Таблица: по строке на каждую заложенную правку (дефект или двойник) — было/стало, цитата, нужный контекст,
пояснение генератора и пустые колонки «Эксперт 1 / Эксперт 2: верно | неверно | спорно» с комментарием.
Отдельный лист — «самодостаточные» пункты (для АР1: контекст не нужен) и инструкция.
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

from .proto import export_docx

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "spaces" / "gen5"
OUT = SRC / "_review"
TYPE_RU = {"vague": "размытая формулировка", "conflict": "несовместимые требования", "missing": "недостающее условие",
           "conflict_twin": "двойник: похоже на противоречие, но совместимо", "missing_twin": "двойник: условие задано в другом месте",
           "vague_twin": "двойник: измеримая формулировка"}
GUIDE = [
    "Что это: черновик проверочного набора AIRA. Документы синтетические (GigaChat-2-Max), в каждый намеренно внесены правки.",
    "Задача эксперта: для каждой строки листа «Разметка» решить, верна ли разметка генератора.",
    "Дефект верен, если в документе действительно есть этот дефект и он существенный (влияет на поведение, понимание или проверяемость).",
    "Двойник верен, если это действительно НЕ дефект (совместимо / условие задано / формулировка измерима).",
    "«Нужный контекст» верен, если без перечисленных пунктов нельзя правильно оценить пункт, и в нём нет лишнего.",
    "Если в документе нашёлся дефект, которого нет в разметке, — допишите его в лист «Найдено дополнительно».",
    "Ответы: верно / неверно / спорно; комментарий — обязательно для «неверно» и «спорно».",
    "«Пометка автопроверки» — подсказка программы, где разметка может быть неверной; решение всё равно за экспертом.",
    "Эксперты работают независимо и не видят ответов друг друга.",
]


def main():
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    OUT.mkdir(parents=True, exist_ok=True)
    docs = [json.loads(Path(p).read_text(encoding="utf-8")) for p in sorted(glob.glob(str(SRC / "*-v5.json")))]
    wb = Workbook()
    ws = wb.active
    ws.title = "Инструкция"
    for i, t in enumerate(GUIDE, 1):
        ws.cell(i, 1, t)
    ws.column_dimensions["A"].width = 140
    m = wb.create_sheet("Разметка")
    head = ["Документ", "Отрасль", "ID", "Тип", "Слот", "Пункт(ы)", "Текст в документе", "Было (до правки)", "Цитата",
            "Нужный контекст", "Пояснение генератора", "Пометка автопроверки", "Эксперт 1", "Комментарий 1", "Эксперт 2", "Комментарий 2"]
    m.append(head)
    for d in docs:
        fr = {f["id"]: f for f in d["fragments"]}
        lines = []
        for f in d["fragments"]:
            lines.append(f"# {f['document']}" if not lines or lines[-1] != f"# {f['document']}" else None)
            lines.append(f"- [{f['id']}] {f['text']}" + (" (архив)" if f["status"] == "deprecated" else ""))
        (OUT / f"{d['id']}.docx").write_bytes(export_docx(d["module"], "\n".join(x for x in lines if x)))
        for x in d["defects"] + d["twins"]:
            m.append([d["id"], d["sector"], x["id"], TYPE_RU[x["type"]], x.get("slot", ""), ", ".join(x["fragments"]),
                      "\n".join(f"{i}: {fr[i]['text']}" for i in x["fragments"]), x.get("original", ""), x.get("quote", ""),
                      "\n".join(f"{i}: {fr[i]['text']}" for i in x.get("needed_context", []) if i in fr),
                      x.get("explanation") or x.get("why") or x.get("why_generator", ""), x.get("hint", ""), "", "", "", ""])
    for col, w in zip("ABCDEFGHIJKLMNOP", (18, 12, 6, 26, 14, 18, 60, 45, 18, 55, 45, 30, 11, 30, 11, 30)):
        m.column_dimensions[col].width = w
    for c in m[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="EEEAF8")
    for row in m.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    m.freeze_panes = "A2"
    s = wb.create_sheet("Самодостаточные (АР1)")
    s.append(["Документ", "Пункт", "Текст", "Эксперт 1: контекст не нужен?", "Эксперт 2"])
    for d in docs:
        fr = {f["id"]: f for f in d["fragments"]}
        for q in d.get("queries", []):
            if q["kind"] == "none":
                s.append([d["id"], q["fragment"], fr[q["fragment"]]["text"], "", ""])
    s.column_dimensions["C"].width = 100
    e = wb.create_sheet("Найдено дополнительно")
    e.append(["Эксперт", "Документ", "Пункт(ы)", "Тип дефекта", "Описание"])
    path = OUT / "Разметка v5 — для экспертов.xlsx"
    wb.save(path)
    print(f"документов {len(docs)}, строк разметки {m.max_row - 1}, самодостаточных {s.max_row - 1} → {path}")


if __name__ == "__main__":
    main()
