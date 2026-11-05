"""Explicit source-address callbacks; old grammars never import the view package."""

from ara.docx_analysis.compatibility_view import ViewNode
from ara.docx_analysis.notes._definitions import read_part
from ara.docx_analysis.sections._context import Context
from ara.docx_analysis.sections._resolve import settings_flag
from ara.docx_analysis.table_styles._proof import Proof
from ara.docx_analysis.visibility._grammar import Grammar
from ara.docx_package.projection import SourceAnchor

from ._models import Blocked


def original_anchor(node, path, sha, part):
    if (
        type(node) is not ViewNode
        or type(node.anchor) is not SourceAnchor
        or node.anchor.source_sha256 != sha
        or node.anchor.part_name != part
    ):
        raise Blocked("invalid_compatibility_anchor")
    return node.anchor


class SourceAnchors:
    def anchor_for(self, node, path, sha, part):
        return original_anchor(node, path, sha, part)


class SourceGrammar(SourceAnchors, Grammar):
    pass


class SourceProof(SourceAnchors, Proof):
    pass


class SourceSections(SourceAnchors, Context):
    pass


def selected_settings(root, source, part, ns):
    return settings_flag(
        root,
        source,
        part,
        ns,
        anchor_for=lambda node, path: original_anchor(node, path, source.sha256, part),
    )


def selected_notes(root, part, kind, linked, sha):
    return read_part(
        root,
        part,
        kind,
        linked,
        sha,
        anchor_for=lambda node, path: original_anchor(node, path, sha, part),
    )
