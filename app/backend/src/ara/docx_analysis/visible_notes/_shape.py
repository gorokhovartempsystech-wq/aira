"""Exact extended DTO validation without changing the older profiles' schema table."""

from dataclasses import fields

from ara.docx_analysis.visible_main._build import valid_identity
from ara.docx_analysis.visible_main._canonical import digest
from ara.docx_analysis.visible_main._models import VisibleLimits, VisibleSnapshot, VisibleViewError
from ara.docx_analysis.visible_main._shape import SCHEMAS, Shape, require
from ara.docx_package.projection import SourceAnchor

from ._models import PROFILE, NoteReference, NoteSnapshot


def validate(
    snapshot, limits, *, profile=PROFILE, style_profile="docx-visibility/styles-context-v1"
):
    try:
        require(type(snapshot) is NoteSnapshot)
        shape = Shape(VisibleLimits(), profile=profile, style_profile=style_profile)
        for f in fields(VisibleSnapshot):
            shape.value(
                getattr(snapshot, f.name), SCHEMAS[VisibleSnapshot][f.name], f.name, VisibleSnapshot
            )
        require(
            valid_identity(snapshot.document_id, snapshot.storage_revision, snapshot.source_sha256)
        )
        require(
            type(snapshot.references) is tuple
            and len(snapshot.references) <= shape.limits.max_pieces
        )
        for ref in snapshot.references:
            require(type(ref) is NoteReference)
            require(type(ref.kind) is str and ref.kind in ("footnote", "endnote"))
            for key in ("reference_anchor", "paragraph_anchor", "target_anchor"):
                shape.value(getattr(ref, key), SourceAnchor)
            for key in ("before_fragment_id", "after_fragment_id"):
                value = getattr(ref, key)
                if value is not None:
                    shape.value(value, str, "fragment_id")
        digest(snapshot, limits.max_manifest_bytes, omit_hash=True)
    except VisibleViewError:
        raise
    except (AttributeError, TypeError, ValueError, OverflowError, RecursionError):
        raise VisibleViewError("invalid_snapshot") from None
