"""Pure, strict checkpoint metadata; no database or receipt authority."""

from ._codec import decode_metadata, encode_metadata
from ._models import CheckpointError, CheckpointMetadata, CheckpointOrigin, PendingSave

__all__ = [
    "CheckpointError",
    "CheckpointMetadata",
    "CheckpointOrigin",
    "PendingSave",
    "decode_metadata",
    "encode_metadata",
]
