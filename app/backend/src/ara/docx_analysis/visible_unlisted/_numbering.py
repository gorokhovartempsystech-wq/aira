"""Bound original definitions before DOM; prove identity and absence of style bindings."""

from ara.docx_analysis.compatibility._xml import candidates
from ara.docx_analysis.sections._xml import build_tree, parse
from ara.docx_analysis.visibility._grammar import Unsupported, check
from ara.docx_analysis.visible_inline_images._parse import Drawings

from ._grammar import Grammar

MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"
RELATIONS = {
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering",
    "http://purl.oclc.org/ooxml/officeDocument/relationships/numbering",
}


def parts(source):
    return {e.name for e in source.entries if e.content_type == MIME}


def preflight(data, source, bounds, limits):
    counter = Drawings(limits)
    for part in sorted(set(candidates(source)) | parts(source)):
        parse(data, part, bounds, counter)


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


def unused(data, source, bounds, namespace):
    result, failed = verified(data, source, bounds, namespace)
    return (set() if result is None else {result[0]}), failed
