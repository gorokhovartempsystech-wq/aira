"""Part identity and independent definition inheritance; never page layout."""

from dataclasses import replace

from ara.docx_analysis.tables._parse import word_name
from ara.docx_package.projection import SourceAnchor

from ._models import SectionBinding, SectionReference, SectionStory, require

MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml."
RELS = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/",
    "http://purl.oclc.org/ooxml/officeDocument/relationships/",
)
VARIANTS = ("default", "first", "even")


def settings_part(source):
    candidates = {e.name for e in source.entries if e.content_type == MIME + "settings+xml"}
    links = [
        r
        for r in source.relationships
        if r.source_part == source.main_part
        and r.relationship_type in {p + "settings" for p in RELS}
    ]
    if not candidates and not links:
        return None
    require(
        len(candidates) == len(links) == 1
        and links[0].target_mode == "Internal"
        and links[0].resolved_part in candidates,
        "unresolved_section_settings",
    )
    return links[0].resolved_part


def boolean(node, ns, code, anchor):
    value = node.get(ns + "val", "true")
    require(
        not len(node)
        and not (node.text or "").strip()
        and not (node.tail or "").strip()
        and set(node.attrib) <= {ns + "val"}
        and value in {"true", "false", "on", "off", "1", "0"},
        code,
        anchor,
    )
    return value in {"true", "on", "1"}


def settings_flag(root, source, part, ns, *, anchor_for=None):
    if root is None:
        return False
    code = "unresolved_section_settings"
    root_anchor = anchor_for(root, ()) if anchor_for else SourceAnchor(source.sha256, part, ())
    require(
        root.tag == ns + "settings"
        and not (root.text or "").strip()
        and all(not (n.tail or "").strip() for n in root),
        code,
        root_anchor,
    )
    seen, result = False, False
    stack = [(root, (), None)]
    while stack:
        node, path, parent = stack.pop()
        if word_name(node.tag) == "evenAndOddHeaders":
            anchor = (
                anchor_for(node, path) if anchor_for else SourceAnchor(source.sha256, part, path)
            )
            require(
                not seen and parent is root and node.tag == ns + "evenAndOddHeaders", code, anchor
            )
            result = boolean(node, ns, code, anchor)
            seen = True
        stack.extend((n, path + (i,), node) for i, n in reversed(list(enumerate(node))))
    return result


class References:
    def __init__(self, source, ns):
        self.ns = ns
        self.rns = "{" + (RELS[1] if "purl.oclc.org" in ns else RELS[0])[:-1] + "}"
        self.links = {
            r.relationship_id: r for r in source.relationships if r.source_part == source.main_part
        }
        self.types = {e.name: e.content_type for e in source.entries}

    def read(self, node, kind, anchor):
        code = "invalid_section_markup"
        require(
            not len(node)
            and not (node.text or "").strip()
            and not (node.tail or "").strip()
            and set(node.attrib) == {self.ns + "type", self.rns + "id"},
            code,
            anchor,
        )
        variant = node.get(self.ns + "type")
        require(variant in VARIANTS, code, anchor)
        rel = self.links.get(node.get(self.rns + "id"))
        require(
            rel is not None
            and rel.target_mode == "Internal"
            and rel.relationship_type in {p + kind for p in RELS}
            and self.types.get(rel.resolved_part) == MIME + kind + "+xml",
            "unresolved_section_reference",
            anchor,
        )
        return SectionReference(kind, variant, anchor, rel.resolved_part)


def inherit(sections, even_and_odd, source):
    definitions, result, stories = {}, [], {}
    for section in sections:
        for ref in section.references:
            definitions[(ref.kind, ref.variant)] = (ref, section.index)
        bindings = []
        for kind in ("header", "footer"):
            for variant in VARIANTS:
                if (variant == "first" and not section.first_page) or (
                    variant == "even" and not even_and_odd
                ):
                    continue
                origin = definitions.get((kind, variant))
                ref, index = origin if origin else (None, None)
                part = ref.part_name if ref else None
                bindings.append(
                    SectionBinding(kind, variant, part, ref.anchor if ref else None, index)
                )
                if ref:
                    stories[part] = SectionStory(kind, part, SourceAnchor(source.sha256, part, ()))
        result.append(replace(section, bindings=tuple(bindings)))
    return tuple(result), tuple(stories[name] for name in sorted(stories))
