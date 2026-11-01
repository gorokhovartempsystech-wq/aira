"""The detached draft representation must not silently coerce damaged values."""

from datetime import UTC, datetime
from importlib import import_module
from uuid import uuid4

import pytest
from pydantic import ValidationError


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("document_id", "5c311090-c936-4a18-a280-bbdafc1f49f2"),
        ("base_version_id", "5c311090-c936-4a18-a280-bbdafc1f49f2"),
        ("revision", 0),
        ("revision", -1),
        ("revision", True),
        ("revision", 1.0),
        ("revision", "1"),
        ("content_markdown", None),
        ("content_markdown", b"Synthetic bytes"),
        ("content_markdown", 12),
        ("updated_at", datetime(2026, 10, 28)),
        ("updated_at", "2026-10-28T00:00:00+00:00"),
        ("updated_at", None),
    ],
)
def test_snapshot_rejects_invalid_field_types_and_values(field, value):
    snapshot_type = import_module("ara.drafts").DraftSnapshot
    values = {
        "document_id": uuid4(),
        "base_version_id": uuid4(),
        "revision": 1,
        "content_markdown": "Synthetic exact text\r\n",
        "updated_at": datetime(2026, 10, 28, tzinfo=UTC),
    }
    with pytest.raises(ValidationError):
        snapshot_type(**{**values, field: value})
