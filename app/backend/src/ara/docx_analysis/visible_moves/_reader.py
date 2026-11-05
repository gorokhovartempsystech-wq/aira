"""Only source-proven inline move wrappers extend the retained-content grammar."""

from functools import partial

from ara.docx_analysis import moves
from ara.docx_analysis.visible_main._models import VisibleViewError
from ara.docx_analysis.visible_main._reader import Reader, Refusal


def prepare_reader(data, source, limits):
    # Aggregate main/styles preflight has already run. The move catalog's
    # additional namespace/range/member bounds also precede the reader DOM.
    try:
        catalog = moves.read_move_catalog(
            data,
            source_sha256=source.sha256,
            limits=moves.MoveLimits(
                max_xml_nodes=limits.max_xml_nodes,
                max_xml_depth=limits.max_xml_depth,
                max_xml_characters=limits.max_xml_characters,
            ),
        )
    except moves.MoveCatalogError as exc:
        code = "view_limit_exceeded" if exc.code == "move_limit_exceeded" else exc.code
        raise VisibleViewError(code) from None
    return partial(MoveReader, catalog=catalog)


class MoveReader(Reader):
    def __init__(self, root, source, limits, *, catalog):
        super().__init__(root, source, limits)
        self.catalog = catalog
        self.markers = set()
        self.members = {}
        for pair in self.catalog.pairs:
            for container in (pair.source, pair.destination):
                self.markers.update((container.start, container.end))
                for member in container.members:
                    self.members[member.anchor] = member.kind

    def plans(self):
        if self.catalog.status == "blocked":
            raise Refusal("move_catalog_blocked")
        return super().plans()

    def extended_inline(self, child, paragraph, *, in_link, top):
        # The catalog has already checked exact attributes, matching ranges,
        # direct paragraph context and every relevant tag, including exclusions.
        anchor = self.anchors[child]
        if anchor in self.markers:
            self.event("metadata", "move_range", child)
        elif self.members.get(anchor) == "from":
            self.event("excluded", "moved_source", child)
        elif self.members.get(anchor) == "to":
            self.event("metadata", "moved_destination", child)
            self.inline(child, paragraph, in_link=in_link)
        else:
            raise Refusal()
