"""Conservative WML projection; never descend through unknown text wrappers."""

from xml.etree import ElementTree as ET

from .. import DocxSource
from .._xml import RELS_TYPE, WORD_NAMESPACES
from ._models import (
    Cell,
    DocxProjection,
    Hyperlink,
    Notice,
    OpaqueBlock,
    Paragraph,
    Row,
    SourceAnchor,
    Span,
    Table,
)

_WORD_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml."
_AUXILIARY_TYPES = frozenset(
    _WORD_TYPE + name + "+xml"
    for name in ("styles", "numbering", "settings", "webSettings", "fontTable")
) | frozenset(
    (
        "application/vnd.openxmlformats-officedocument.theme+xml",
        "application/vnd.openxmlformats-package.core-properties+xml",
        "application/vnd.openxmlformats-officedocument.extended-properties+xml",
        "application/vnd.openxmlformats-officedocument.custom-properties+xml",
    )
)
_STORY_TYPES = frozenset(
    _WORD_TYPE + name + "+xml"
    for name in ("header", "footer", "footnotes", "endnotes", "comments", "document.glossary")
)
_REL_NAMESPACES = dict(
    zip(
        WORD_NAMESPACES,
        (
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
            "http://purl.oclc.org/ooxml/officeDocument/relationships",
        ),
        strict=True,
    )
)
_BOOKMARKS = frozenset(("bookmarkStart", "bookmarkEnd"))
_REVISIONS = frozenset(
    (
        "ins",
        "del",
        "moveFrom",
        "moveTo",
        "tblGridChange",
        "numberingChange",
        "cellIns",
        "cellDel",
        "cellMerge",
    )
)


def _local(node: ET.Element) -> str | None:
    namespace, _, name = node.tag[1:].partition("}")
    return name if namespace in WORD_NAMESPACES else None


def _attribute(node: ET.Element | None, name: str) -> str | None:
    if node is None:
        return None
    namespace = node.tag[1:].partition("}")[0]
    return node.get(f"{{{namespace}}}{name}")


def _children(node: ET.Element | None, name: str) -> list[ET.Element]:
    return [] if node is None else [child for child in node if _local(child) == name]


def _property(node: ET.Element | None, name: str) -> ET.Element | None:
    # Callers first reject duplicate singleton properties; never pick a winner.
    return next(iter(_children(node, name)), None)


def _duplicates(node: ET.Element | None, *names: str) -> bool:
    return any(len(_children(node, name)) > 1 for name in names)


def _has_revision(node: ET.Element) -> bool:
    for child in node.iter():
        name = _local(child)
        if name is not None and (
            name in _REVISIONS
            or name.endswith("PrChange")
            or (name.startswith("move") and name.endswith(("RangeStart", "RangeEnd")))
        ):
            return True
    return False


def _projected_runs(paragraph: ET.Element):
    for child in paragraph:
        if _local(child) == "r":
            yield child
        elif _local(child) == "hyperlink":
            yield from _children(child, "r")


def _paragraph_reason(node: ET.Element) -> str | None:
    if _has_revision(node):
        return "tracked_change"
    if _duplicates(node, "pPr"):
        return "unsupported_structure"
    props = _property(node, "pPr")
    if _duplicates(props, "pStyle", "numPr"):
        return "unsupported_structure"
    if _duplicates(_property(props, "numPr"), "numId", "ilvl"):
        return "unsupported_structure"
    if any(_duplicates(run, "rPr") for run in _projected_runs(node)):
        return "unsupported_structure"
    return None


def _table_reason(table: ET.Element) -> str | None:
    # Only this physical table's properties participate. Nested tables and
    # paragraphs receive their own decisions when their blocks are visited.
    props = _children(table, "tblPr") + _children(table, "tblGrid")
    invalid = _duplicates(table, "tblPr", "tblGrid") or any(
        _local(child) not in ("tblPr", "tblGrid", "tr") for child in table
    )
    for row in _children(table, "tr"):
        props.extend(_children(row, "trPr"))
        invalid |= _duplicates(row, "trPr") or any(
            _local(child) not in ("trPr", "tc") for child in row
        )
        for cell in _children(row, "tc"):
            cell_props = _children(cell, "tcPr")
            props.extend(cell_props)
            invalid |= len(cell_props) > 1 or any(
                _duplicates(prop, "gridSpan", "vMerge") for prop in cell_props
            )
    if any(_has_revision(prop) for prop in props):
        return "tracked_change"
    return "unsupported_structure" if invalid else None


class _Projector:
    def __init__(self, source: DocxSource, root: ET.Element) -> None:
        self.source = source
        self.anchors: dict[ET.Element, SourceAnchor] = {}
        self.notices: list[Notice] = []
        stack = [(root, ())]
        while stack:
            node, path = stack.pop()
            self.anchors[node] = SourceAnchor(source.sha256, source.main_part, path)
            stack.extend((child, path + (index,)) for index, child in enumerate(node))

    def _notice(self, code: str, node: ET.Element) -> None:
        self.notices.append(Notice(code, self.source.main_part, self.anchors[node]))

    def _opaque(self, node: ET.Element, reason: str) -> OpaqueBlock:
        self._notice(reason, node)
        return OpaqueBlock(self.anchors[node], reason, node.tag)

    def _properties_anchor(self, node: ET.Element, name: str) -> SourceAnchor | None:
        prop = _property(node, name)
        return None if prop is None else self.anchors[prop]

    def _paragraph(self, node: ET.Element) -> Paragraph:
        spans: list[Span] = []
        offset = 0

        def inline(child, run=None, link=None):
            nonlocal offset
            name = _local(child)
            if name in _BOOKMARKS:
                return
            kind, text, space, break_type, reason = "opaque", "\ufffc", None, None, None
            if name in ("t", "tab", "br", "cr") and len(child):
                reason = "unsupported_structure"
            elif run is not None and name in ("t", "tab", "br", "cr"):
                if name == "t":
                    kind, text = "text", child.text or ""
                    space = child.get("{http://www.w3.org/XML/1998/namespace}space")
                elif name == "tab":
                    kind, text = "tab", "\t"
                else:
                    kind, text = "break", "\n"
                    break_type = _attribute(child, "type") if name == "br" else None
                    if break_type is None:
                        break_type = "textWrapping"
            if kind == "opaque":
                reason = reason or "unsupported_element"
                self._notice(reason, child)
            spans.append(
                Span(
                    kind=kind,
                    anchor=self.anchors[child],
                    run_anchor=None if run is None else self.anchors[run],
                    text=text,
                    start=offset,
                    end=offset + len(text),
                    xml_space=space,
                    break_type=break_type,
                    hyperlink=link,
                    reason=reason,
                )
            )
            offset += len(text)

        def run_spans(run, link=None):
            for child in run:
                if _local(child) != "rPr":
                    inline(child, run, link)

        for child in node:
            name = _local(child)
            if name == "pPr" or name in _BOOKMARKS:
                continue
            if name == "r":
                run_spans(child)
            elif name == "hyperlink":
                namespace = child.tag[1:].partition("}")[0]
                link = Hyperlink(
                    self.anchors[child],
                    child.get(f"{{{_REL_NAMESPACES[namespace]}}}id"),
                    _attribute(child, "anchor"),
                )
                for item in child:
                    if _local(item) == "r":
                        run_spans(item, link)
                    else:
                        inline(item, link=link)
            else:
                inline(child)
        props = _property(node, "pPr")
        numbering = _property(props, "numPr")
        return Paragraph(
            anchor=self.anchors[node],
            text="".join(span.text for span in spans),
            spans=tuple(spans),
            properties_anchor=self._properties_anchor(node, "pPr"),
            style_id=_attribute(_property(props, "pStyle"), "val"),
            numbering_id=_attribute(_property(numbering, "numId"), "val"),
            numbering_level=_attribute(_property(numbering, "ilvl"), "val"),
            has_opaque=any(span.kind == "opaque" for span in spans),
        )

    def _table(self, node: ET.Element, projected: dict) -> Table:
        rows = []
        for row in _children(node, "tr"):
            cells = []
            for cell in _children(row, "tc"):
                props = _property(cell, "tcPr")
                merge = _property(props, "vMerge")
                merge_value = _attribute(merge, "val")
                if merge is not None and merge_value is None:
                    merge_value = "continue"
                cells.append(
                    Cell(
                        anchor=self.anchors[cell],
                        blocks=tuple(projected[child] for child in cell if _local(child) != "tcPr"),
                        properties_anchor=self._properties_anchor(cell, "tcPr"),
                        grid_span=_attribute(_property(props, "gridSpan"), "val"),
                        vertical_merge=merge_value,
                    )
                )
            rows.append(Row(self.anchors[row], tuple(cells), self._properties_anchor(row, "trPr")))
        return Table(self.anchors[node], tuple(rows), self._properties_anchor(node, "tblPr"))

    def blocks(self, body: ET.Element) -> tuple[Paragraph | Table | OpaqueBlock, ...]:
        if any(_local(child) in ("fldChar", "instrText") for child in body.iter()):
            return (self._opaque(body, "complex_field"),)

        children = [child for child in body if _local(child) != "sectPr"]
        projected: dict[ET.Element, Paragraph | Table | OpaqueBlock] = {}
        # Explicit postorder jobs avoid Python recursion even if callers grant
        # enough XML depth for hundreds of nested tables. Unsupported wrappers
        # are terminal jobs: their descendants never become ordinary blocks.
        pending = [(child, False) for child in reversed(children)]
        while pending:
            node, finish = pending.pop()
            name = _local(node)
            if finish:
                projected[node] = self._table(node, projected)
            elif name == "p":
                reason = _paragraph_reason(node)
                projected[node] = self._opaque(node, reason) if reason else self._paragraph(node)
            elif name == "tbl":
                reason = _table_reason(node)
                if reason:
                    projected[node] = self._opaque(node, reason)
                    continue
                pending.append((node, True))
                blocks = [
                    child
                    for row in _children(node, "tr")
                    for cell in _children(row, "tc")
                    for child in cell
                    if _local(child) != "tcPr"
                ]
                pending.extend((child, False) for child in reversed(blocks))
            else:
                projected[node] = self._opaque(node, "unsupported_element")
        return tuple(projected[child] for child in children)


def project_main(source: DocxSource, root: ET.Element) -> DocxProjection:
    projector = _Projector(source, root)
    body_tag = root.tag.rpartition("}")[0] + "}body"
    body = next(child for child in root if child.tag == body_tag)
    blocks = projector.blocks(body)
    for child in root:
        if child is not body and _local(child) != "background":
            projector._notice("unprojected_root_element", child)
    # Tuple paths sort in element preorder, including ancestor-before-descendant.
    notices = sorted(projector.notices, key=lambda notice: notice.anchor.path)
    for entry in sorted(source.entries, key=lambda entry: entry.name):
        if (
            entry.name == source.main_part
            or entry.content_type in (None, RELS_TYPE)
            or entry.content_type in _AUXILIARY_TYPES
        ):
            continue
        code = "unprojected_story" if entry.content_type in _STORY_TYPES else "unprojected_part"
        notices.append(Notice(code, entry.name, None))
    return DocxProjection(source, projector.anchors[body], blocks, tuple(notices), bool(notices))
