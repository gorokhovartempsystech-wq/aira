"""Bound the exact extension without widening any previous DTO schema table."""

from dataclasses import fields

from ara.docx_analysis.visible_main._canonical import digest
from ara.docx_analysis.visible_main._models import VisibleLimits, VisibleViewError
from ara.docx_analysis.visible_main._shape import Shape, require
from ara.docx_analysis.visible_notes import NoteSnapshot
from ara.docx_analysis.visible_notes._shape import validate as validate_note
from ara.docx_analysis.visible_outline._labels import units
from ara.docx_package.projection import SourceAnchor

from ._contexts import STYLE_PROFILE
from ._models import PROFILE, StyleListItem, StyleListSnapshot


def validate(
    snapshot,
    limits,
    *,
    snapshot_type=StyleListSnapshot,
    profile=PROFILE,
    style_profile=STYLE_PROFILE,
    shape_type=Shape,
):
    try:
        require(type(snapshot) is snapshot_type)
        base = NoteSnapshot(**{f.name: getattr(snapshot, f.name) for f in fields(NoteSnapshot)})
        validate_note(
            base, limits, profile=profile, style_profile=style_profile, shape_type=shape_type
        )
        hard = VisibleLimits()
        shape = shape_type(hard, profile=profile, style_profile=style_profile)
        require(type(snapshot.lists) is tuple and len(snapshot.lists) <= hard.max_paragraphs)
        characters, references, chains = len(snapshot.analysis_text), 0, 0
        for item in snapshot.lists:
            require(type(item) is StyleListItem)
            for key in (
                "paragraph_anchor",
                "properties_anchor",
                "definition_anchor",
                "instance_anchor",
            ):
                shape.value(getattr(item, key), SourceAnchor)
            if item.start_override_anchor is not None:
                shape.value(item.start_override_anchor, SourceAnchor)
            require(
                type(item.numbering_source) is str and item.numbering_source in ("direct", "style")
            )
            require(
                type(item.style_chain) is tuple
                and len(item.style_chain) <= hard.styles.max_chain_depth
            )
            chains += len(item.style_chain)
            require(chains <= hard.max_xml_nodes)
            for anchor in item.style_chain:
                shape.value(anchor, SourceAnchor)
            require(len(set(item.style_chain)) == len(item.style_chain))
            for anchor in (item.style_reference_anchor, item.level_style_anchor):
                if anchor is not None:
                    shape.value(anchor, SourceAnchor)
            if item.numbering_source == "direct":
                require(
                    not item.style_chain
                    and item.style_reference_anchor is None
                    and item.level_style_anchor is None
                )
            else:
                require(bool(item.style_chain) and item.level_style_anchor is not None)
            require(type(item.num_id) is int and 1 <= item.num_id <= 2147483647)
            require(type(item.level) is int and 0 <= item.level <= 8)
            require(type(item.ordinal) is int and 0 <= item.ordinal <= 2147483647)
            require(
                type(item.format) is str
                and item.format in ("decimal", "bullet", "upperRoman", "lowerRoman")
            )
            require(type(item.label) is str and len(item.label) <= 31 and units(item.label) <= 31)
            require(type(item.suffix) is str and item.suffix in ("tab", "space", "nothing"))
            characters += len(item.label) + (item.suffix != "nothing")
            require(characters <= hard.max_text_characters)
            require(type(item.fragment_ids) is tuple)
            references += len(item.fragment_ids)
            require(references <= len(snapshot.fragments))
            for fragment in item.fragment_ids:
                shape.value(fragment, str, "fragment_id")
        digest(snapshot, limits.max_manifest_bytes, omit_hash=True)
    except VisibleViewError:
        raise
    except (AttributeError, TypeError, ValueError, OverflowError, RecursionError):
        raise VisibleViewError("invalid_snapshot") from None
