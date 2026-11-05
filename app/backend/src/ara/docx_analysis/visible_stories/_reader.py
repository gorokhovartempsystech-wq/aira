"""Same retained table/visible-run grammar, with actual per-story source ownership."""

from ara.docx_analysis.visible_grid_tables._reader import GridReader
from ara.docx_analysis.visible_main._reader import check

LEAVES = {
    "type",
    "pgSz",
    "pgMar",
    "paperSrc",
    "lnNumType",
    "pgNumType",
    "formProt",
    "vAlign",
    "noEndnote",
    "textDirection",
    "bidi",
    "rtlGutter",
    "docGrid",
}
CONTAINERS = {
    "cols": {"col"},
    "pgBorders": {"top", "left", "bottom", "right"},
    "footnotePr": {"pos", "numFmt", "numStart", "numRestart"},
    "endnotePr": {"pos", "numFmt", "numStart", "numRestart"},
}


class StoryReader(GridReader):
    def __init__(
        self,
        root,
        source,
        limits,
        *,
        part,
        kind,
        main_namespace,
        section_catalog,
        table_catalog,
        catalog,
        proof_factory,
    ):
        self.original_part, self.kind, self.main_namespace = part, kind, main_namespace
        self.sections = {s.anchor for s in section_catalog.sections if s.anchor is not None}
        self.section_refs = {r.anchor for s in section_catalog.sections for r in s.references}
        self.section_histories = {
            h.anchor for h in section_catalog.histories if h.kind == "section"
        }
        super().__init__(
            root,
            source,
            limits,
            table_catalog=table_catalog,
            catalog=catalog,
            proof_factory=proof_factory,
        )

    def part_name_for(self, source):
        return self.original_part

    def body_for(self, root):
        return super().body_for(root) if self.kind == "main" else root

    def root_properties(self):
        check(self.ns == self.main_namespace)
        if self.kind == "main":
            super().root_properties()
        else:
            check(self.name(self.root) == {"header": "hdr", "footer": "ftr"}[self.kind])
            self.attrs(self.root)
            self.container(self.root)

    def formatting_property(self, node, kind):
        if kind == "pPr" and self.name(node) == "sectPr":
            self.section_properties(node)
        else:
            super().formatting_property(node, kind)

    def formatting_leaf(self, node):
        self.leaf(node)
        check(all(name.startswith(self.ns) for name in node.attrib))

    def section_properties(self, node):
        check(self.kind == "main" and self.anchors[node] in self.sections)
        self.container(node)
        self.event("metadata", "section_properties", node)
        for child in node:
            name, anchor = self.name(child), self.anchors[child]
            if anchor in self.section_refs:
                self.event("metadata", "header_footer_reference", child)
            elif anchor in self.section_histories:
                self.event("excluded", "historical_section_properties", child)
            elif name == "titlePg":
                # Its exact current boolean shape was proved from this same source.
                self.event("metadata", "section_title_page", child)
            elif name in LEAVES:
                self.formatting_leaf(child)
            elif name in CONTAINERS:
                self.container(child)
                check(all(a.startswith(self.ns) for a in child.attrib))
                if name in ("footnotePr", "endnotePr"):
                    self.attrs(child)
                seen = set()
                for item in child:
                    key = self.name(item)
                    check(key in CONTAINERS[name] and (name == "cols" or key not in seen))
                    seen.add(key)
                    self.formatting_leaf(item)
            else:
                check(False)
