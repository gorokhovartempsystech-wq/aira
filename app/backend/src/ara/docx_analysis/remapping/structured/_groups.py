"""Part-aware literal groups and source-derived structural semantics."""

from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256

from ara.docx_analysis.visible_style_lists._models import PROFILE as STYLE_LIST_PROFILE
from ara.docx_analysis.visible_word._models import PROFILE as WORD_PROFILE

from .._context import encode
from .._models import require
from ._source import address, read, word
from ._style_numbering import provenance


@dataclass(frozen=True, repr=False)
class Group:
    identity: tuple
    story: tuple
    kind: str
    texts: tuple
    fragments: tuple
    key: tuple
    neighbor: str


@dataclass(repr=False)
class Context:
    original: object
    groups: list
    incoming: dict


def context(source, snapshot):
    original = read(source, snapshot)
    fragments, lists, references = defaultdict(list), defaultdict(list), defaultdict(list)
    for fragment in snapshot["fragments"]:
        fragments[address(fragment["paragraph_anchor"])].append(fragment)
    for item in snapshot["lists"]:
        lists[address(item["paragraph_anchor"])].append(item)
    for item in snapshot["references"]:
        references[address(item["paragraph_anchor"])].append(item)
    groups, prefixes, incoming = [], {}, defaultdict(set)
    for paragraph in snapshot["paragraphs"]:
        identity = address(paragraph["paragraph_anchor"])
        node, story = original.nodes[identity], original.stories[identity]
        require(word(node) == "p" and story is not None)
        story_node = original.nodes[story]
        local = fragments[identity]
        positions = {f["fragment_id"]: i for i, f in enumerate(local)}

        def relative(anchor):
            part, path = address(anchor)
            require(part == identity[0] and path[: len(identity[1])] == identity[1])
            return part, path[len(identity[1]) :]

        evidence = []
        for f in local:
            require(address(f["story_anchor"]) == story)
            flow = address(f["flow_anchor"])
            require(flow[0] == identity[0] and identity[1][: len(flow[1])] == flow[1])
            pieces = [
                {
                    k: relative(v) if k in ("anchor", "run_anchor", "paragraph_anchor") else v
                    for k, v in piece.items()
                }
                for piece in f["pieces"]
            ]
            evidence.append(
                (
                    f["text"],
                    pieces,
                    ("story",)
                    if flow == story
                    else (original.digests[flow].hex(), identity[1][len(flow[1]) :]),
                )
            )
        items = []
        for item in lists[identity]:
            properties = (
                provenance(item, relative)
                if snapshot["profile"] in (STYLE_LIST_PROFILE, WORD_PROFILE)
                else dict(properties=relative(item["properties_anchor"]))
            )
            items.append(
                dict(
                    values={
                        k: item[k]
                        for k in ("num_id", "level", "ordinal", "format", "label", "suffix")
                    },
                    **properties,
                    definition=address(item["definition_anchor"]),
                    instance=address(item["instance_anchor"]),
                    override=address(item["start_override_anchor"])
                    if item["start_override_anchor"]
                    else None,
                    fragments=[positions[f] for f in item["fragment_ids"]],
                )
            )
        links = []
        for item in references[identity]:
            target, path = address(item["target_anchor"]), relative(item["reference_anchor"])
            before, after = item["before_fragment_id"], item["after_fragment_id"]
            links.append(
                (
                    item["kind"],
                    target,
                    path,
                    positions[before] if before is not None else None,
                    positions[after] if after is not None else None,
                )
            )
            incoming[target].add((identity, path, item["kind"]))
        raw = original.digests[identity].hex()
        own = sha256(encode((items, links))).hexdigest()
        literal = sha256(encode(evidence)).hexdigest()
        ancestor = original.ancestry[identity].hex()
        header = sha256(encode((story_node.tag, sorted(story_node.attrib.items())))).hexdigest()
        prefix = prefixes.setdefault(story, sha256())
        key = (identity[0], story, header, raw, ancestor, prefix.hexdigest(), literal, own)
        neighbor = sha256(encode((raw, ancestor, literal, own))).hexdigest()
        groups.append(
            Group(
                identity,
                story,
                word(story_node),
                tuple(f["text"] for f in local),
                tuple(f["fragment_id"] for f in local),
                key,
                neighbor,
            )
        )
        if original.styled[identity]:
            prefix.update(original.digests[identity])
    return Context(original, groups, dict(incoming))
