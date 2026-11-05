"""Pair named inline move containers without interpreting or rewriting their text."""

import re
import unicodedata

from ara.docx_package.projection import SourceAnchor

from ._models import MoveIssue, MoveMember, MovePair, MoveRange
from ._parse import move_name


class Blocked(Exception):
    def __init__(self, code, anchor):
        self.issue = MoveIssue(code, anchor)
        super().__init__(code)


def require(value, anchor, code="invalid_move_markup"):
    if not value:
        raise Blocked(code, anchor)


def attributes(node, name, namespace, anchor):
    start, end = name.endswith("RangeStart"), name.endswith("RangeEnd")
    required = {"id", "name"} if start else {"id"}
    allowed = {"id"} if end else {"id", "author", "date"} | ({"name"} if start else set())
    require(
        set(node.attrib) <= {namespace + key for key in allowed}
        and all(namespace + key in node.attrib for key in required),
        anchor,
    )
    value = node.get(namespace + "id")
    require(re.fullmatch(r"[+-]?[0-9]{1,20}", value) is not None, anchor)
    require(not (node.text or "").strip() and not (node.tail or "").strip(), anchor)
    if start or end:
        require(not len(node), anchor)
    else:
        require(all(not (child.tail or "").strip() for child in node), anchor)
    group = node.get(namespace + "name") if start else None
    if start:
        require(
            1 <= len(group) <= 255 and not any(unicodedata.category(c) == "Cc" for c in group),
            anchor,
        )
    return int(value), group


def markers(root, source, *, part_name=None, container=None, root_path=(), anchor_for=None):
    namespace = root.tag.rpartition("}")[0] + "}"
    body = (
        next(child for child in root if child.tag == namespace + "body")
        if container is None
        else container
    )
    part = source.main_part if part_name is None else part_name
    make_anchor = anchor_for or (lambda node, path: SourceAnchor(source.sha256, part, path))
    prefix = (root,) if body is root else (root, body)
    groups = {}
    stack = [(root, root_path, ())]
    while stack:
        node, path, ancestors = stack.pop()
        name = move_name(node.tag)
        if name is not None:
            anchor = make_anchor(node, path)
            require(
                node.tag == namespace + name
                and len(ancestors) == len(prefix) + 1
                and ancestors[:-1] == prefix
                and ancestors[-1].tag == namespace + "p",
                anchor,
                "unsupported_move_context",
            )
            identity, group = attributes(node, name, namespace, anchor)
            paragraph = make_anchor(ancestors[-1], path[:-1])
            kind = "from" if name.startswith("moveFrom") else "to"
            groups.setdefault(paragraph, []).append((name, kind, identity, group, anchor))
        for index in range(len(node) - 1, -1, -1):
            stack.append((node[index], path + (index,), ancestors + (node,)))
    return groups


def index(root, source, *, part_name=None, container=None, root_path=(), anchor_for=None):
    paragraphs = markers(
        root,
        source,
        part_name=part_name,
        container=container,
        root_path=root_path,
        anchor_for=anchor_for,
    )
    identities, names, ranges = set(), set(), []
    for paragraph, events in paragraphs.items():
        active, members = None, []
        for name, kind, identity, group, anchor in events:
            if name.endswith("RangeStart"):
                require(active is None, anchor, "nested_or_crossed_range")
                require((kind, identity) not in identities, anchor, "duplicate_range_id")
                require((kind, group) not in names, anchor, "duplicate_move_name")
                identities.add((kind, identity))
                names.add((kind, group))
                active = kind, identity, group, anchor
                members = []
            elif name.endswith("RangeEnd"):
                require(
                    active is not None and active[:2] == (kind, identity), anchor, "unmatched_range"
                )
                require(bool(members), anchor, "empty_move_range")
                ranges.append(
                    MoveRange(
                        kind, identity, active[2], active[3], anchor, paragraph, tuple(members)
                    )
                )
                active, members = None, []
            else:
                require(active is not None and active[0] == kind, anchor, "unmatched_move_content")
                members.append(MoveMember(kind, identity, anchor, paragraph))
        if active is not None:
            raise Blocked("unmatched_range", active[3])
    pairs = {}
    for item in ranges:
        pairs.setdefault(item.name, {})[item.kind] = item
    unmatched = [item for pair in pairs.values() if len(pair) != 2 for item in pair.values()]
    if unmatched:
        raise Blocked("unmatched_move", min(unmatched, key=lambda item: item.start.path).start)
    result = [MovePair(name, pair["from"], pair["to"]) for name, pair in pairs.items()]
    return tuple(
        sorted(result, key=lambda pair: min(pair.source.start.path, pair.destination.start.path))
    )
