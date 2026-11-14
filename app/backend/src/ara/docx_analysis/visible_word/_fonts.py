"""Prove embedded font roles without loading, installing or changing font bytes."""

import re
from collections import defaultdict

from ara.docx_analysis.visibility._grammar import boolean, check

from ._appearance import fonts
from ._roles import BASE, SR, R, role

FONT_TYPES = frozenset(
    ("application/x-font-ttf", "application/vnd.openxmlformats-officedocument.obfuscatedFont")
)
KEY = r"\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}"


def font_table(source, roots):
    part = role(
        source,
        BASE + "fontTable+xml",
        {R + "fontTable", SR + "fontTable"},
        source.main_part,
        outgoing=True,
    )
    if part is None:
        return {}
    entries = {e.name: e for e in source.entries}
    incoming, outgoing = defaultdict(list), defaultdict(list)
    for link in source.relationships:
        incoming[link.resolved_part].append(link)
        outgoing[link.source_part].append(link)
    links = {link.relationship_id: link for link in outgoing[part]}
    used, accounted = set(), {part: ("metadata", "word_fontTable_accounted")}

    def embedding(node, ns):
        rel_ns = "{" + (SR if "purl.oclc.org" in ns else R).rstrip("/") + "}"
        check(set(node.attrib) <= {rel_ns + "id", ns + "fontKey", ns + "subsetted"})
        identity = node.get(rel_ns + "id")
        check(identity in links)
        key = node.get(ns + "fontKey")
        check(key is None or re.fullmatch(KEY, key) is not None)
        if ns + "subsetted" in node.attrib:
            boolean(node.get(ns + "subsetted"))
        link = links[identity]
        check(link.relationship_type in {R + "font", SR + "font"})
        check(link.target_mode == "Internal" and link.resolved_part in entries)
        entry = entries[link.resolved_part]
        check(entry.content_type in FONT_TYPES and entry.size_bytes > 0)
        if entry.content_type.endswith("obfuscatedFont"):
            check(key is not None)
        check(not outgoing[entry.name])
        check(all(item.source_part == part for item in incoming[entry.name]))
        used.add(identity)
        accounted[entry.name] = ("metadata", "embedded_font_resource")

    fonts(roots[part], embedding=embedding)
    # Every edge must have an explicit font slot; unrelated resources stay blocked.
    check(used == links.keys())
    return accounted
