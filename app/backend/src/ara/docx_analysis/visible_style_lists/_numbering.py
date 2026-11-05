"""Prove exact package links with the fixed abstract-style numbering grammar."""

from ara.docx_analysis.sections._xml import build_tree
from ara.docx_analysis.visibility._grammar import Unsupported, check
from ara.docx_analysis.visible_unlisted._numbering import RELATIONS, parts

from ._grammar import Grammar


def verified(data, source, bounds, namespace):
    found = parts(source)
    links = [
        r
        for r in source.relationships
        if r.relationship_type in RELATIONS or r.resolved_part in found
    ]
    try:
        check(len(found) <= 1 and len(links) <= 1)
        expected = (
            "http://purl.oclc.org/ooxml/officeDocument/relationships/numbering"
            if "purl.oclc.org" in namespace
            else "http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering"
        )
        for r in links:
            check(
                r.source_part == source.main_part
                and r.relationship_type == expected
                and r.target_mode == "Internal"
                and r.resolved_part in found
            )
        check(not any(r.source_part in found for r in source.relationships))
        result = None
        for part in found:
            root = build_tree(data, part, bounds)
            check(root.tag == namespace + "numbering")
            Grammar(root, source.sha256, part).prove()
            result = (part, root)
        return result, False
    except Unsupported:
        return None, True
