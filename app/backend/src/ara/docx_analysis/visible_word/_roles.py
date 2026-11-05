"""Closed package roles; a matching MIME never authorizes an unrelated edge."""

from ara.docx_analysis.compatibility._xml import candidates
from ara.docx_analysis.visibility._grammar import check
from ara.docx_analysis.visible_unlisted._numbering import MIME as NUMBERING

BASE = "application/vnd.openxmlformats-officedocument.wordprocessingml."
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
SR = "http://purl.oclc.org/ooxml/officeDocument/relationships/"
EFFECTS = "application/vnd.ms-word.stylesWithEffects+xml"
EFFECTS_REL = "http://schemas.microsoft.com/office/2007/relationships/stylesWithEffects"
CUSTOM_PROPS = "application/vnd.openxmlformats-officedocument.customXmlProperties+xml"
THEME = "application/vnd.openxmlformats-officedocument.theme+xml"
THUMBNAIL = "http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail"
AUX_XML = frozenset(
    (BASE + "fontTable+xml", BASE + "webSettings+xml", EFFECTS, THEME, CUSTOM_PROPS)
)
CUSTOM_RELS = {r + n for r in (R, SR) for n in ("customXml", "customXmlProps")}


def xml_parts(source):
    return tuple(
        sorted(
            set(candidates(source))
            | {e.name for e in source.entries if e.content_type in AUX_XML | {NUMBERING}}
            | {
                r.resolved_part
                for r in source.relationships
                if r.relationship_type in CUSTOM_RELS and r.target_mode == "Internal"
            }
        )
    )


def role(source, mime, relations, owner, *, outgoing=False):
    found = {e.name for e in source.entries if e.content_type == mime}
    links = [
        r
        for r in source.relationships
        if r.relationship_type in relations or r.resolved_part in found
    ]
    if not found and not links:
        return None
    check(len(found) == 1 and len(links) == 1)
    part = next(iter(found))
    link = links[0]
    check(
        link.source_part == owner
        and link.relationship_type in relations
        and link.target_mode == "Internal"
        and link.resolved_part == part
    )
    check(outgoing or not any(r.source_part == part for r in source.relationships))
    return part


def standard(source, suffix, mime):
    return role(source, mime, {R + suffix, SR + suffix}, source.main_part)
