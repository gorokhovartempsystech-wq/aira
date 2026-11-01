"""Explicit property-history profile; the original main builder remains fixed."""

from uuid import UUID

from ._build import _build_snapshot
from ._models import FinalSnapshot, FinalViewLimits
from ._properties_reader import PROPERTIES_PROFILE, PropertiesReader


def build_properties_snapshot(
    data: bytes,
    *,
    document_id: UUID,
    storage_revision: int,
    source_sha256: str,
    limits: FinalViewLimits | None = None,
) -> FinalSnapshot:
    return _build_snapshot(
        data,
        document_id=document_id,
        storage_revision=storage_revision,
        source_sha256=source_sha256,
        limits=limits,
        profile=PROPERTIES_PROFILE,
        reader_type=PropertiesReader,
    )
