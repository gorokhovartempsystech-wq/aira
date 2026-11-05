"""Only visible retained markers activate a normal definition in its bound part."""

from ara.docx_analysis.visible_main._reader import Refusal, boolean


class References:
    def __init__(self, catalog):
        self.targets = {
            (part.kind, definition.note_id): (part, definition)
            for part in catalog.parts
            if part.linked
            for definition in part.definitions
        }
        self.used = {}

    def resolve(self, reader, node):
        kind = reader.name(node).removesuffix("Reference")
        identity = int(reader.attr(node, "id"))
        if not -2147483648 <= identity <= 32767:
            raise Refusal("unsupported_note_identifier")
        custom = reader.attr(node, "customMarkFollows")
        if custom is not None and boolean(custom):
            raise Refusal("unsupported_custom_note_mark")
        target = self.targets.get((kind, identity))
        if target is None or target[1].note_type != "normal":
            raise Refusal("unresolved_note_reference")
        part, definition = target
        self.used.setdefault(definition.anchor, target)
        return kind, definition.anchor
