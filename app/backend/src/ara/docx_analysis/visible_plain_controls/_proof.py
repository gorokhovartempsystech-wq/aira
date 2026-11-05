"""Conservative uniform-current-format proof after ordinary plans/table validation."""

from ara.docx_analysis.visible_main._reader import Refusal

MARKERS = {"bookmarkStart", "bookmarkEnd", "commentRangeStart", "commentRangeEnd"}
ATOMS = {"t", "tab", "br", "cr", "commentReference"}


def require(value, code="unsupported_plain_control_content"):
    if not value:
        raise Refusal(code)


class Proof:
    def __init__(self, reader):
        self.r = reader
        self.signature = None

    def role(self, node):
        parent = self.r.logical_parents.get(node)
        while parent is not None and self.r.name(parent) in (
            "sdtContent",
            "sdt",
            "ins",
            "hyperlink",
        ):
            parent = self.r.logical_parents.get(parent)
        if parent is self.r.body or (parent is not None and self.r.name(parent) == "tc"):
            return "block"
        name = self.r.name(parent) if parent is not None else ""
        require(name in ("p", "tr"), "unsupported_plain_control_context")
        return "inline" if name == "p" else "cell"

    def run(self, node):
        # Normal plans already proved syntax and property history ownership. The same
        # current selector/properties within one paragraph give one formatting basis.
        properties = next((n for n in node if self.r.name(n) == "rPr"), None)
        signature = tuple(
            sorted(
                (n.tag, tuple(sorted(n.attrib.items())))
                for n in (() if properties is None else properties)
                if self.r.name(n) != "rPrChange"
            )
        )
        if self.signature is None:
            self.signature = signature
        require(signature == self.signature, "unsupported_plain_control_formatting")
        for child in node:
            name = self.r.name(child)
            if name == "rPr":
                continue
            require(name in ATOMS)
            if name == "br":
                require(self.r.attr(child, "type") in (None, "textWrapping"))

    def inline(self, node, *, paragraph=False):
        for child in node:
            name = self.r.name(child)
            if paragraph and name == "pPr":
                continue
            if name == "r":
                self.run(child)
            elif name == "ins":
                self.inline(child)
            elif name == "del" or name in MARKERS:
                # Existing plans already validated the retained wrapper/marker.
                continue
            else:
                raise Refusal("unsupported_plain_control_content")

    def block(self, content):
        require(len(content) <= 1 and all(self.r.name(n) == "p" for n in content))
        if len(content):
            self.inline(content[0], paragraph=True)

    def validate(self, node, content):
        role = self.role(node)
        if content is not None:
            if role == "inline":
                self.inline(content)
            elif role == "block":
                self.block(content)
            else:
                require(len(content) <= 1 and all(self.r.name(n) == "tc" for n in content))
                if len(content):
                    cell = content[0]
                    if cell not in self.r.control_context.deleted_cells:
                        blocks = tuple(n for n in cell if self.r.name(n) != "tcPr")
                        self.block(blocks)
        self.r.event("metadata", "plain_control_format_proven", node)
