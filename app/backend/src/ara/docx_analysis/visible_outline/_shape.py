"""Bound the exact extension without widening any previous DTO schema table."""

from dataclasses import fields

from ara.docx_analysis.visible_main._canonical import digest
from ara.docx_analysis.visible_main._models import VisibleLimits, VisibleViewError
from ara.docx_analysis.visible_main._shape import Shape, require
from ara.docx_analysis.visible_notes import NoteSnapshot
from ara.docx_analysis.visible_notes._shape import validate as validate_note
from ara.docx_analysis.visible_unlisted._contexts import STYLE_PROFILE
from ara.docx_package.projection import SourceAnchor

from ._labels import units
from ._models import PROFILE, ListItem, OutlineSnapshot


def validate(snapshot, limits):
    try:
        require(type(snapshot) is OutlineSnapshot)
        base = NoteSnapshot(**{f.name: getattr(snapshot, f.name) for f in fields(NoteSnapshot)})
        validate_note(base, limits, profile=PROFILE, style_profile=STYLE_PROFILE)
        hard = VisibleLimits()
        shape = Shape(hard, profile=PROFILE, style_profile=STYLE_PROFILE)
        require(type(snapshot.lists) is tuple and len(snapshot.lists) <= hard.max_paragraphs)
        characters, references = len(snapshot.analysis_text), 0
        for item in snapshot.lists:
            require(type(item) is ListItem)
            for key in (
                "paragraph_anchor",
                "properties_anchor",
                "definition_anchor",
                "instance_anchor",
            ):
                shape.value(getattr(item, key), SourceAnchor)
            if item.start_override_anchor is not None:
                shape.value(item.start_override_anchor, SourceAnchor)
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
