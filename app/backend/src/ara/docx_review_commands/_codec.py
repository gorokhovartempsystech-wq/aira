"""Distinct clear intent, sharing the existing durable unhide acknowledgement."""

from hashlib import sha256
from uuid import UUID

from ara.docx_review_preferences import _codec as legacy
from ara.docx_review_preferences._models import Command, require

VERSION = "docx-review-clear/1"


def make_clear(document_id, command_id, expected_revision):
    require(
        type(document_id) is UUID and type(command_id) is UUID and legacy.counter(expected_revision)
    )
    values = dict(operation="clear_hidden")
    raw = legacy.encode(
        dict(
            schema_version=VERSION,
            document_id=str(document_id),
            command_id=str(command_id),
            expected_revision=str(expected_revision),
            kind="unhide",
            **values,
        )
    )
    require(len(raw) <= 16384)
    return Command(
        document_id, command_id, expected_revision, "unhide", values, raw, sha256(raw).hexdigest()
    )


def restore_clear(body):
    require(
        type(body) is dict
        and set(body)
        == {"schema_version", "document_id", "command_id", "expected_revision", "kind", "operation"}
    )
    require(
        body["schema_version"] == VERSION
        and body["kind"] == "unhide"
        and body["operation"] == "clear_hidden"
    )
    return make_clear(
        legacy.uuid(body["document_id"]),
        legacy.uuid(body["command_id"]),
        legacy.decimal(body["expected_revision"]),
    )
