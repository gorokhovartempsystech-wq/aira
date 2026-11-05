"""Strict request shapes and public metadata; no raw worker buffers or secrets."""

import re
from dataclasses import asdict
from datetime import datetime, timezone
from uuid import UUID

from ara.docx_analysis.storage_codec import RetryCheckCommand, SavedCheckCommand, StorageCodecError
from ara.docx_editor._http_transport import invalid

VERSION = "docx-analysis-http/1"
SAVED_FIELDS = (
    "client_request_id",
    "registry_id",
    "session_id",
    "save_command_id",
    "command_sequence",
    "session_revision",
    "storage_revision",
    "source_sha256",
)


def uuid(value):
    if type(value) is not str or len(value) != 36:
        invalid()
    try:
        parsed = UUID(value)
    except ValueError:
        invalid()
    if str(parsed) != value:
        invalid()
    return parsed


def counter(value):
    if type(value) is not str or re.fullmatch(r"0|[1-9][0-9]{0,18}", value) is None:
        invalid()
    number = int(value)
    if number >= 2**63:
        invalid()
    return number


def shape(body, keys):
    if type(body) is not dict or set(body) != set(keys):
        invalid()


def saved(document_id, body):
    shape(body, SAVED_FIELDS)
    try:
        return uuid(body["client_request_id"]), SavedCheckCommand(
            document_id,
            *(uuid(body[name]) for name in ("registry_id", "session_id", "save_command_id")),
            *(
                counter(body[name])
                for name in ("command_sequence", "session_revision", "storage_revision")
            ),
            body["source_sha256"],
        )
    except StorageCodecError:
        invalid()


def retry(document_id, run_id, body):
    shape(body, ("client_request_id",))
    return uuid(body["client_request_id"]), RetryCheckCommand(document_id, run_id)


def run(summary, error_code):
    data = asdict(summary)
    for key, value in data.items():
        if isinstance(value, UUID):
            data[key] = str(value)
        elif isinstance(value, datetime):
            data[key] = value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        elif key in ("storage_revision", "accepted_order"):
            data[key] = str(value)
    data["error_code"] = error_code
    return data


def receipt(document_id, key, view=None, *, stopped=False, fixture=True):
    return dict(
        schema_version=VERSION,
        document_id=str(document_id),
        client_request_id=str(key),
        phase=view.phase if view else "admitting",
        run_id=str(view.run_id) if view and view.run_id else None,
        stop_requested=bool(stopped or (view and view.stop_requested)),
        stop_reason=view.stop_reason if view else None,
        state=run(view.sql_state.summary, view.sql_state.error_code)
        if view and view.sql_state
        else None,
        error_code=view.error_code if view else None,
        fixture=fixture,
    )


def durable_receipt(summary, error_code):
    terminal = summary.status in ("succeeded", "failed", "cancelled", "timed_out")
    return dict(
        schema_version=VERSION,
        document_id=str(summary.document_id),
        client_request_id=str(summary.client_request_id),
        phase="finished" if terminal else "active" if summary.status != "queued" else "queued",
        run_id=str(summary.run_id),
        stop_requested=summary.status in ("cancel_requested", "cancelled"),
        stop_reason=None,
        state=run(summary, error_code),
        error_code=None,
        fixture=summary.execution_kind == "fixture",
    )


def result(summary, error_code, public, stored_hash, revision, digest):
    return dict(
        schema_version=VERSION,
        run=run(summary, error_code),
        result=public,
        stored_result_sha256=stored_hash,
        current_storage_revision=str(revision),
        current_sha256=digest,
        matches_saved_document=(summary.storage_revision, summary.source_sha256)
        == (revision, digest),
        fixture=summary.execution_kind == "fixture",
    )


def schema(operation):
    """Inline OpenAPI avoids changing the editor's existing schema installer."""
    uid = dict(type="string", format="uuid", pattern=r"^[0-9a-f-]{36}$")
    count = dict(
        type="string", pattern=r"^(0|[1-9][0-9]{0,18})$", description="Decimal integer below 2^63"
    )
    digest = dict(type="string", pattern="^[0-9a-f]{64}$")
    string = dict(type="string")
    boolean = dict(type="boolean")
    timestamp = dict(type="string", format="date-time")

    def nullable(value):
        return dict(anyOf=[value, dict(type="null")])

    def record(properties):
        return dict(
            type="object",
            properties=properties,
            required=list(properties),
            additionalProperties=False,
        )

    summary = record(
        dict(
            run_id=uid,
            document_id=uid,
            storage_revision=count,
            accepted_order=count,
            source_sha256=digest,
            snapshot_sha256=digest,
            profile=string,
            policy_version=string,
            execution_spec_sha256=digest,
            client_request_id=uid,
            start_kind=dict(enum=["saved", "retry"]),
            retry_of_run_id=nullable(uid),
            status=dict(
                enum=[
                    "queued",
                    "running",
                    "cancel_requested",
                    "succeeded",
                    "failed",
                    "cancelled",
                    "timed_out",
                ]
            ),
            stage=string,
            execution_kind=dict(enum=["fixture", "local_model"]),
            created_at=timestamp,
            deadline_at=timestamp,
            finished_at=nullable(timestamp),
            error_code=nullable(string),
        )
    )
    receipt_shape = record(
        dict(
            schema_version=dict(const=VERSION),
            document_id=uid,
            client_request_id=uid,
            phase=dict(
                enum=["admitting", "queued", "active", "settling", "finished", "not_admitted"]
            ),
            run_id=nullable(uid),
            stop_requested=boolean,
            stop_reason=nullable(string),
            state=nullable(summary),
            error_code=nullable(string),
            fixture=boolean,
        )
    )
    result_shape = record(
        dict(
            schema_version=dict(const=VERSION),
            run=summary,
            result=dict(
                type="object",
                properties=dict(
                    schema_version=dict(
                        enum=[
                            "docx-review/1",
                            "docx-review/2",
                            "docx-review/3",
                            "docx-review/4",
                            "docx-review/5",
                        ]
                    )
                ),
                required=["schema_version"],
                description=(
                    "Source-verified docx-review/1, docx-review/2, docx-review/3, "
                    "docx-review/4 or docx-review/5 envelope "
                    "without private_provenance; full nested shapes follow "
                    "the standalone contracts."
                ),
            ),
            stored_result_sha256=digest,
            current_storage_revision=count,
            current_sha256=digest,
            matches_saved_document=boolean,
            fixture=boolean,
        )
    )
    post = operation in ("start", "retry", "stop")
    response = (
        result_shape
        if operation == "result"
        else record(dict(schema_version=dict(const=VERSION), run=summary))
        if operation == "run"
        else receipt_shape
    )
    result = dict(
        description=(
            "Explicit local development scope. 202 acknowledges an intent, "
            "not a committed enqueue. Poll Location; Stop intent is not "
            "a cancelled result. All responses are no-store."
        ),
        responses={
            "202" if post else "200": dict(
                description="Admission receipt" if post else "Verified metadata/result",
                content={"application/json": dict(schema=response)},
            ),
            **{
                str(code): dict(description=description)
                for code, description in (
                    (404, "Scoped item not found"),
                    (409, "Conflict or result not ready"),
                    (413, "Body limit"),
                    (415, "Unsupported media"),
                    (422, "Invalid strict request"),
                    (500, "Invalid stored result"),
                    (503, "Busy or unavailable"),
                )
            },
        },
    )
    if post:
        props = (
            {"client_request_id": uid}
            if operation == "retry"
            else {}
            if operation == "stop"
            else {
                name: digest
                if name == "source_sha256"
                else count
                if name in ("command_sequence", "session_revision", "storage_revision")
                else uid
                for name in SAVED_FIELDS
            }
        )
        result["requestBody"] = dict(
            required=True, content={"application/json": dict(schema=record(props))}
        )
    return result
