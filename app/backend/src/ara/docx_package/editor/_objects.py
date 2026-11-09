"""Atomic block insertion over the existing lexical paragraph split."""

import re
from dataclasses import dataclass
from xml.etree import ElementTree as ET

from ..boundaries import SplitParagraph, export_boundary
from ..boundaries._tree import bounded_join
from ..projection import project_docx
from ..structure._package import read_main, repack
from ..structure._xml import scan
from ._models import EditorError


@dataclass(frozen=True, slots=True)
class TableSize:
    rows: int
    columns: int

    def __post_init__(self):
        rows, columns = getattr(self, "rows", None), getattr(self, "columns", None)
        if not (
            type(rows) is int
            and type(columns) is int
            and 1 <= rows <= 100
            and 1 <= columns <= 32
            and rows * columns <= 1024
        ):
            raise EditorError("invalid_input")


def body_geometry(main, namespace, index):
    ns = "{" + namespace + "}"
    body = ET.fromstring(main).find(ns + "body")
    section = None
    for block in list(body)[index:]:
        section = block if block.tag == ns + "sectPr" else block.find(ns + "pPr/" + ns + "sectPr")
        if section is not None:
            break
    if section is None:
        return 8640, 11520

    def number(node, key, default):
        value = None if node is None else node.get(ns + key)
        if value is None:
            return default
        if re.fullmatch(r"-?[0-9]{1,7}", value) is None:
            raise EditorError("unsupported_intent")
        return int(value)

    size, margins, columns = (section.find(ns + k) for k in ("pgSz", "pgMar", "cols"))
    width = number(size, "w", 12240) - sum(
        number(margins, k, d) for k, d in (("left", 1440), ("right", 1440), ("gutter", 0))
    )
    height = number(size, "h", 15840) - sum(
        abs(number(margins, k, 1440)) for k in ("top", "bottom")
    )
    if columns is not None:
        specified = list(columns)
        if specified:
            if any(n.tag != ns + "col" for n in specified):
                raise EditorError("unsupported_intent")
            width = min(number(n, "w", 0) for n in specified)
        else:
            count = number(columns, "num", 1)
            if not 1 <= count <= 64:
                raise EditorError("unsupported_intent")
            width = (width - (count - 1) * number(columns, "space", 720)) // count
    if width < 32 or height < 32:
        raise EditorError("unsupported_intent")
    return min(width, 8640), min(height, 11520)


def body_width(main, namespace, index):
    return body_geometry(main, namespace, index)[0]


def split_for_block(core, before, index, offset):
    p = before.projection.blocks[index]
    data = export_boundary(
        before.data,
        SplitParagraph(p.anchor, p.text, offset),
        limits=core._limits,
        projection_limits=core._projection_limits,
    )
    view = project_docx(data, limits=core._limits, projection_limits=core._projection_limits)
    main = read_main(data, view.source, core._limits)
    nodes, codec, _ = scan(main)
    target = nodes[view.blocks[index + 1].anchor.path]
    namespace = target.name.rpartition("}")[0]
    return data, view, main, target.start, codec, namespace


def table(core, before, index, offset, rows, columns):
    TableSize(rows, columns)
    data, view, main, at, codec, ns = split_for_block(core, before, index, offset)
    width = body_width(main, ns, view.blocks[index + 1].anchor.path[-1])
    widths = [width // columns + (i < width % columns) for i in range(columns)]
    edges = "".join(
        f'<a:{e} a:val="single" a:sz="4" a:color="B8C4D0"/>'
        for e in ("top", "left", "bottom", "right", "insideH", "insideV")
    )
    grid = "".join(f'<a:gridCol a:w="{w}"/>' for w in widths)
    cells = "".join(
        f'<a:tc><a:tcPr><a:tcW a:w="{w}" a:type="dxa"/></a:tcPr><a:p/></a:tc>' for w in widths
    )
    xml = (
        f'<a:tbl xmlns:a="{ns}"><a:tblPr><a:tblW a:w="{width}" a:type="dxa"/>'
        f'<a:tblBorders>{edges}</a:tblBorders><a:tblLayout a:type="fixed"/></a:tblPr>'
        f"<a:tblGrid>{grid}</a:tblGrid>" + f"<a:tr>{cells}</a:tr>" * rows + "</a:tbl>"
    )
    changed = bounded_join(
        (main[:at], xml.encode(codec), main[at:]),
        min(core._limits.max_xml_bytes, core._limits.max_part_bytes),
    )
    return repack(data, view.source, changed, core._limits), index + 2
