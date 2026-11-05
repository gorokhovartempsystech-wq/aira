"""Actual part identity and direct original definitions, never inferred references."""

import re

from ara.docx_analysis.sections._resolve import MIME, RELS
from ara.docx_analysis.tables._parse import PREFIXES
from ara.docx_package.projection import SourceAnchor

from ._models import NoteDefinition, NotePart, require

KINDS = ("footnote", "endnote")
TYPES = frozenset(("normal", "separator", "continuationSeparator", "continuationNotice"))


def candidates(source):
    types = {MIME + kind + "s+xml": kind for kind in KINDS}
    return {e.name: types[e.content_type] for e in source.entries if e.content_type in types}


def linked_parts(source, parts):
    result = set()
    for kind in KINDS:
        types = {prefix + kind + "s" for prefix in RELS}
        links = [
            r
            for r in source.relationships
            if r.source_part == source.main_part and r.relationship_type in types
        ]
        require(len(links) <= 1, "unresolved_note_relationship")
        if links:
            link = links[0]
            require(
                link.target_mode == "Internal" and parts.get(link.resolved_part) == kind,
                "unresolved_note_relationship",
            )
            result.add(link.resolved_part)
    return result


def read_part(root, part, kind, linked, source_sha256, *, anchor_for=None):
    code = "invalid_note_markup"
    anchor = anchor_for(root, ()) if anchor_for else SourceAnchor(source_sha256, part, ())
    ns = next((p for p in PREFIXES if root.tag == p + kind + "s"), None)
    require(
        ns is not None
        and not root.attrib
        and not (root.text or "").strip()
        and all(not (n.tail or "").strip() for n in root),
        code,
        anchor,
    )
    records, seen = [], set()
    for i, node in enumerate(root):
        child_anchor = (
            anchor_for(node, (i,)) if anchor_for else SourceAnchor(source_sha256, part, (i,))
        )
        identity = node.get(ns + "id", "")
        note_type = node.get(ns + "type", "normal")
        require(
            node.tag == ns + kind
            and ns + "id" in node.attrib
            and set(node.attrib) <= {ns + "id", ns + "type"}
            and re.fullmatch(r"[+-]?[0-9]{1,20}", identity) is not None
            and note_type in TYPES
            and len(node) > 0
            and not (node.text or "").strip()
            and all(not (n.tail or "").strip() for n in node),
            code,
            child_anchor,
        )
        note_id = int(identity)
        require(note_id not in seen, "duplicate_note_id", child_anchor)
        seen.add(note_id)
        records.append(NoteDefinition(note_id, note_type, child_anchor))
    return NotePart(kind, part, anchor, linked, tuple(records))
