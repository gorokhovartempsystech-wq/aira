"""Small canonical commands/acks; corrupt stored records never become successful replays."""

import json
import re
from hashlib import sha256
from uuid import UUID

from ara.documents.storage import DocumentError

from ._models import MAX_REVISION, TYPES, Command, PreferenceReceipt, fail, require


def counter(value):
    return type(value) is int and 0 <= value <= MAX_REVISION


def digest(value, prefix=""):
    return type(value) is str and re.fullmatch(prefix + r"[0-9a-f]{64}", value) is not None


def preferences(disabled_types, show_questions, show_hidden):
    require(type(disabled_types) in (tuple, list) and len(disabled_types) <= 3)
    require(all(type(v) is str and v in TYPES for v in disabled_types))
    require(len(set(disabled_types)) == len(disabled_types))
    require(type(show_questions) is bool and type(show_hidden) is bool)
    return dict(
        disabled_types=tuple(sorted(disabled_types)),
        show_questions=show_questions,
        show_hidden=show_hidden,
    )


def encode(body):
    return json.dumps(
        body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def make(document_id, command_id, expected_revision, kind, values):
    require(type(document_id) is UUID and type(command_id) is UUID and counter(expected_revision))
    if kind == "preferences":
        values = preferences(**values)
    else:
        require(kind in ("hide", "unhide"))
        require(type(values["run_id"]) is UUID)
        require(digest(values["result_sha256"]) and digest(values["finding_id"], "df-"))
        values = dict(values)
    body = dict(
        schema_version="docx-review-command/1",
        document_id=str(document_id),
        command_id=str(command_id),
        expected_revision=str(expected_revision),
        kind=kind,
    )
    body.update(
        {key: str(value) if type(value) is UUID else value for key, value in values.items()}
    )
    raw = encode(body)
    require(len(raw) <= 16384)
    return Command(
        document_id, command_id, expected_revision, kind, values, raw, sha256(raw).hexdigest()
    )


def response(receipt):
    raw = encode(
        dict(
            schema_version="docx-review-receipt/1",
            document_id=str(receipt.document_id),
            command_id=str(receipt.command_id),
            kind=receipt.kind,
            expected_revision=str(receipt.expected_revision),
            revision=str(receipt.revision),
            changed=receipt.changed,
        )
    )
    require(len(raw) <= 2048, "storage_error")
    return raw, sha256(raw).hexdigest()


def uuid(value):
    require(type(value) is str and len(value) == 36)
    parsed = UUID(value)
    require(str(parsed) == value)
    return parsed


def decimal(value):
    require(type(value) is str and re.fullmatch(r"0|[1-9][0-9]{0,18}", value) is not None)
    parsed = int(value)
    require(counter(parsed))
    return parsed


def parsed(raw, expected, maximum):
    require(type(raw) is bytes and 0 < len(raw) <= maximum)
    require(digest(expected) and sha256(raw).hexdigest() == expected)

    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result)
            result[key] = value
        return result

    def constant(value):
        fail("validation_error")

    value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    require(type(value) is dict)
    return value


def restored_command(body):
    if body.get("schema_version") == "docx-review-clear/1":
        from ara.docx_review_commands._codec import restore_clear

        return restore_clear(body)
    base = {"schema_version", "document_id", "command_id", "expected_revision", "kind"}
    kind = body.get("kind")
    require(type(kind) is str and kind in ("preferences", "hide", "unhide"))
    extra = (
        {"disabled_types", "show_questions", "show_hidden"}
        if kind == "preferences"
        else {"run_id", "result_sha256", "finding_id"}
    )
    require(set(body) == base | extra and body["schema_version"] == "docx-review-command/1")
    values = {key: body[key] for key in extra}
    if kind != "preferences":
        values["run_id"] = uuid(values["run_id"])
    return make(
        uuid(body["document_id"]),
        uuid(body["command_id"]),
        decimal(body["expected_revision"]),
        kind,
        values,
    )


def read_receipt(row, command):
    try:
        saved = restored_command(parsed(row.command_data, row.command_sha256, 16384))
        require(saved.data == row.command_data)
        require(
            (saved.document_id, saved.command_id, saved.expected_revision, saved.kind)
            == (row.document_id, row.command_id, row.expected_revision, row.kind)
        )
        require(counter(row.revision) and row.revision == row.expected_revision + 1)
        body = parsed(row.response_data, row.response_sha256, 2048)
        require(type(body.get("changed")) is bool)
        receipt = PreferenceReceipt(
            row.document_id,
            row.command_id,
            row.kind,
            row.expected_revision,
            row.revision,
            body["changed"],
        )
        raw, digest_value = response(receipt)
        require(raw == row.response_data and digest_value == row.response_sha256)
    except (DocumentError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        fail("storage_error")
    if row.command_data != command.data or row.command_sha256 != command.sha256:
        fail("idempotency_conflict")
    return receipt
