"""Closed bounded structural input; actual XML authority remains with the parent."""

from ..review_fixture import _keys, _require


def anchor(value, source_sha256):
    _keys(value, "source_sha256 part_name path")
    _require(value["source_sha256"] == source_sha256)
    part, path = value["part_name"], value["path"]
    _require(type(part) is str and 1 <= len(part) <= 65535 and "\\" not in part)
    _require(all(p not in ("", ".", "..") for p in part.split("/")))
    part.encode("utf-8")
    _require(type(path) is list and len(path) <= 128)
    _require(all(type(n) is int and 0 <= n <= 99999 for n in path))
    return part, tuple(path)


def descendant(child, parent):
    return (
        child[0] == parent[0]
        and len(child[1]) > len(parent[1])
        and child[1][: len(parent[1])] == parent[1]
    )


def _read(value, fragments, source_sha256, *, outline, style_lists=False):
    _keys(value, "lists note_references")
    lists, notes = value["lists"], value["note_references"]
    _require(type(lists) is list and len(lists) <= 10000)
    _require(type(notes) is list and len(notes) <= 100000)
    index = {f["id"]: f for f in fragments}
    paragraphs, associated = set(), set()
    cost = sum(len(f["text"]) for f in fragments)
    selected, chains = None, 0
    for item in lists:
        _keys(
            item,
            "paragraph_anchor properties_anchor definition_anchor instance_anchor "
            "start_override_anchor num_id level ordinal format label suffix fragment_ids"
            + (
                " numbering_source style_reference_anchor style_chain level_style_anchor"
                if style_lists
                else ""
            ),
        )
        paragraph = anchor(item["paragraph_anchor"], source_sha256)
        properties = anchor(item["properties_anchor"], source_sha256)
        definition = anchor(item["definition_anchor"], source_sha256)
        instance = anchor(item["instance_anchor"], source_sha256)
        _require(paragraph not in paragraphs)
        if style_lists:
            from ._style_bindings import read_binding

            chains += read_binding(item, source_sha256, paragraph, properties, definition)
            _require(chains <= 100000)
        else:
            _require(descendant(properties, paragraph))
        paragraphs.add(paragraph)
        _require(definition[0] == instance[0])
        if item["start_override_anchor"] is not None:
            override = anchor(item["start_override_anchor"], source_sha256)
            _require(override[0] == instance[0])
        for key, low, high in (
            ("num_id", 1, 2147483647),
            ("level", 0, 8 if outline else 0),
            ("ordinal", 0, 2147483647),
        ):
            _require(type(item[key]) is int and low <= item[key] <= high)
        formats = (
            ("decimal", "bullet", "upperRoman", "lowerRoman") if outline else ("decimal", "bullet")
        )
        _require(type(item["format"]) is str and item["format"] in formats)
        _require(type(item["suffix"]) is str and item["suffix"] in ("tab", "space", "nothing"))
        label = item["label"]
        _require(type(label) is str and len(label) <= (31 if outline else 4096))
        label.encode("utf-8")
        if outline:
            _require(sum(2 if ord(c) > 0xFFFF else 1 for c in label) <= 31)
        cost += len(label) + (item["suffix"] != "nothing")
        _require(cost <= 1000000)
        ids = item["fragment_ids"]
        _require(type(ids) is list and len(ids) <= len(fragments))
        for identity in ids:
            _require(type(identity) is str and identity in index and identity not in associated)
            associated.add(identity)
        if selected is None and ids:
            selected = index[ids[0]], label
    references = set()
    for note in notes:
        _keys(
            note,
            "kind reference_anchor paragraph_anchor target_anchor before_fragment_id "
            "after_fragment_id",
        )
        _require(type(note["kind"]) is str and note["kind"] in ("footnote", "endnote"))
        reference = anchor(note["reference_anchor"], source_sha256)
        paragraph = anchor(note["paragraph_anchor"], source_sha256)
        anchor(note["target_anchor"], source_sha256)
        key = note["kind"], reference
        _require(descendant(reference, paragraph) and key not in references)
        references.add(key)
        for name in ("before_fragment_id", "after_fragment_id"):
            identity = note[name]
            _require(identity is None or (type(identity) is str and identity in index))
    return selected, len(lists), len(notes)


def read(value, fragments, source_sha256):
    return _read(value, fragments, source_sha256, outline=False)


def read_outline(value, fragments, source_sha256):
    return _read(value, fragments, source_sha256, outline=True)


def read_style_lists(value, fragments, source_sha256):
    return _read(value, fragments, source_sha256, outline=True, style_lists=True)
