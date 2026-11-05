"""Bounded original trees and linear fingerprints after full source verification."""

from dataclasses import dataclass
from hashlib import sha256

from ara.docx_analysis.sections._xml import parse
from ara.docx_package import DocxLimits, open_docx
from ara.docx_package._xml import WORD_NAMESPACES
from ara.docx_package.projection import ProjectionLimits
from ara.docx_package.projection._parse import _BoundedBuilder

from .._context import METADATA, encode

STORIES = frozenset(("body", "hdr", "ftr", "footnote", "endnote"))


def word(node):
    namespace, _, name = node.tag.rpartition("}")
    return name if namespace.removeprefix("{") in WORD_NAMESPACES else ""


def address(anchor):
    return anchor["part_name"], tuple(anchor["path"])


def fingerprint(node, children, *, hole=False):
    value = sha256(
        encode(
            (node.tag, sorted(node.attrib.items()), node.text, node.tail, 0 if hole else len(node))
        )
    )
    if hole:
        value.update(b"body-hole")
    else:
        for child in children:
            value.update(child)
    return value.digest()


@dataclass(repr=False)
class Original:
    main: str
    seal: object
    nodes: dict
    digests: dict
    stories: dict
    ancestry: dict
    styled: dict
    transferable: bool


def read(source, snapshot):
    package, bounds = open_docx(source.source_data), DocxLimits()
    parts = {package.main_part} | {
        p["paragraph_anchor"]["part_name"] for p in snapshot["paragraphs"]
    }
    nodes, digests, stories, ancestry, styled = {}, {}, {}, {}, {}
    sections, transferable, main_frame = [], True, None
    for part in sorted(parts):
        root = parse(
            source.source_data, part, bounds, _BoundedBuilder(ProjectionLimits(100000, 128))
        )
        order, stack = [], [(root, ())]
        while stack:
            node, path = stack.pop()
            key = part, path
            nodes[key] = node
            order.append(key)
            stack.extend((child, path + (i,)) for i, child in reversed(tuple(enumerate(node))))
        frames = {}
        for key in reversed(order):
            node, path = nodes[key], key[1]
            children = [(part, path + (i,)) for i in range(len(node))]
            digests[key] = fingerprint(node, (digests[c] for c in children))
            styled[key] = word(node) == "pPr" or any(styled[c] for c in children)
            if part == package.main_part:
                frames[key] = fingerprint(
                    node, (frames[c] for c in children), hole=word(node) == "body"
                )
        for key in order:
            node, path = nodes[key], key[1]
            parent = (part, path[:-1]) if path else None
            name = word(node)
            stories[key] = key if name in STORIES else stories[parent] if parent else None
            if (
                parent
                and stories[key] is not None
                and name not in STORIES
                and parent != stories[key]
            ):
                ancestry[key] = sha256(
                    encode((ancestry[parent].hex(), digests[parent].hex(), path[-1]))
                ).digest()
            else:
                ancestry[key] = b""
            if part == package.main_part and name == "sectPr":
                sections.append(digests[key].hex())
                transferable = transferable and parent is not None and word(nodes[parent]) == "body"
        if part == package.main_part:
            main_frame = frames[part, ()].hex()
    seal = dict(
        main=package.main_part,
        frame=main_frame,
        parts=sorted(
            (e.name, e.content_type, e.sha256)
            for e in package.entries
            if e.name != package.main_part and e.content_type not in METADATA
        ),
        sections=sections,
    )
    return Original(
        package.main_part, seal, nodes, digests, stories, ancestry, styled, transferable
    )
