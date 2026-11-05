"""Exact paragraph trees, conservative ancestry context and noncrossing anchors."""

import json
from collections import Counter
from dataclasses import dataclass, field
from hashlib import sha256

from ara.docx_package import DocxLimits, open_docx
from ara.docx_package.projection import ProjectionLimits
from ara.docx_package.projection._parse import parse_main

from ._models import require

METADATA = {
    "application/vnd.openxmlformats-package.core-properties+xml",
    "application/vnd.openxmlformats-officedocument.custom-properties+xml",
    "application/vnd.openxmlformats-officedocument.extended-properties+xml",
}


def encode(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode()


def tree(node):
    digest, stack = sha256(), [node]
    while stack:
        child = stack.pop()
        # Expanded names avoid dependence on global namespace registration.
        # Keeping whitespace is conservative; hidden/revision content is retained.
        digest.update(
            encode((child.tag, sorted(child.attrib.items()), child.text, child.tail, len(child)))
        )
        stack.extend(reversed(child))
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class Paragraph:
    fragment_id: str | None
    text: str = field(repr=False)
    tree_sha256: str
    prefix_sha256: str

    @property
    def key(self):
        return self.text, self.tree_sha256, self.prefix_sha256


def context(source, snapshot):
    package = open_docx(source.source_data)
    root = parse_main(source.source_data, package, DocxLimits(), ProjectionLimits(100000, 128))
    ns = root.tag.rpartition("}")[0] + "}"
    body = next(n for n in root if n.tag == ns + "body")
    direct = set(body)
    nodes, stack = {}, [(root, ())]
    while stack:
        node, path = stack.pop()
        nodes[path] = node
        stack.extend((child, path + (i,)) for i, child in enumerate(node))
    fragments = {tuple(f["paragraph_anchor"]["path"]): f for f in snapshot["fragments"]}
    texts = {tuple(p["paragraph_anchor"]["path"]): [] for p in snapshot["paragraphs"]}
    for run in snapshot["runs"]:
        if run["visibility"]["hidden"]:
            continue
        chars = texts[tuple(run["paragraph_anchor"]["path"])]
        for atom in nodes[tuple(run["run_anchor"]["path"])]:
            if atom.tag == ns + "t":
                chars.append(atom.text or "")
            elif atom.tag == ns + "tab":
                chars.append("\t")
            elif atom.tag in (ns + "br", ns + "cr"):
                chars.append("\n")
    seal = dict(
        main_part=package.main_part,
        root=(root.tag, sorted(root.attrib.items())),
        body=(body.tag, sorted(body.attrib.items())),
        parts=sorted(
            (e.name, e.content_type, e.sha256)
            for e in package.entries
            if e.name != package.main_part and e.content_type not in METADATA
        ),
        sections=[tree(n) for n in body if n.tag == ns + "sectPr"],
    )
    rows, prefix = [], sha256()
    for item in snapshot["paragraphs"]:
        path = tuple(item["paragraph_anchor"]["path"])
        node, fragment = nodes[path], fragments.get(path)
        require(node.tag == ns + "p" and node in direct)
        text = "".join(texts[path])
        require(fragment is None or fragment["text"] == text)
        digest = tree(node)
        rows.append(
            Paragraph(
                fragment["fragment_id"] if fragment else None, text, digest, prefix.hexdigest()
            )
        )
        # Do not guess heading levels from display names. Earlier styled content
        # is context too, so changes to any previous pPr paragraph veto transfer.
        if any(child.tag == ns + "pPr" for child in node):
            prefix.update(digest.encode("ascii"))
    return seal, rows


def paragraph_matches(previous, current):
    left_seal, left = previous
    right_seal, right = current
    if left_seal != right_seal:
        return {}
    left_counts, right_counts = Counter(p.text for p in left), Counter(p.text for p in right)
    right_index = {
        p.key: j for j, p in enumerate(right) if p.text.strip() and right_counts[p.text] == 1
    }
    pairs = [
        (i, right_index[p.key])
        for i, p in enumerate(left)
        if p.fragment_id and left_counts[p.text] == 1 and p.key in right_index
    ]
    # Reject every member of every inversion; choosing one LIS would arbitrarily
    # bless one of two moved groups as stable.
    suffix = [len(right)] * (len(pairs) + 1)
    for index in range(len(pairs) - 1, -1, -1):
        suffix[index] = min(suffix[index + 1], pairs[index][1])

    def neighbor(rows, i):
        if i < 0:
            return ("start",)
        if i == len(rows):
            return ("end",)
        return "text", sha256(rows[i].text.encode()).hexdigest()

    output, prefix = {}, -1
    for index, (i, j) in enumerate(pairs):
        monotone = prefix < j < suffix[index + 1]
        prefix = max(prefix, j)
        if monotone and all(
            neighbor(left, i + shift) == neighbor(right, j + shift) for shift in (-1, 1)
        ):
            output[left[i].fragment_id] = right[j].fragment_id
    return output
