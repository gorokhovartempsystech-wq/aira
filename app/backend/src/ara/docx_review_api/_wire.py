"""Strict wire commands and public review metadata, without stored dismissal keys."""

import re
from dataclasses import asdict

from ara.docx_analysis_api import _wire as analysis
from ara.docx_editor._http_transport import invalid

VERSION = "docx-review-http/1"


def clear_command(body):
    analysis.shape(body, ("command_id", "expected_revision"))
    return dict(
        command_id=analysis.uuid(body["command_id"]),
        expected_revision=analysis.counter(body["expected_revision"]),
    )


def command(body, *, visibility=False):
    fields = (
        ("result_sha256", "hidden")
        if visibility
        else ("disabled_types", "show_questions", "show_hidden")
    )
    analysis.shape(body, ("command_id", "expected_revision", *fields))
    return dict(
        command_id=analysis.uuid(body["command_id"]),
        expected_revision=analysis.counter(body["expected_revision"]),
        **{key: body[key] for key in fields},
    )


def finding(value):
    if type(value) is not str or re.fullmatch(r"df-[0-9a-f]{64}", value) is None:
        invalid()
    return value


def preferences(state):
    return dict(
        document_id=str(state.document_id),
        revision=str(state.revision),
        disabled_types=list(state.disabled_types),
        show_questions=state.show_questions,
        show_hidden=state.show_hidden,
    )


def receipt(value):
    data = asdict(value)
    for key in ("document_id", "command_id", "expected_revision", "revision"):
        data[key] = str(data[key])
    return dict(schema_version=VERSION, receipt=data)


def schema(operation):
    uid = dict(type="string", format="uuid")
    count = dict(
        type="string", pattern=r"^(0|[1-9][0-9]{0,18})$", description="Decimal integer below 2^63"
    )
    digest = dict(type="string", pattern="^[0-9a-f]{64}$")
    boolean = dict(type="boolean")
    filters = dict(
        disabled_types=dict(
            type="array",
            items=dict(enum=["contradiction", "duplicate", "formulation"]),
            uniqueItems=True,
            maxItems=3,
        ),
        show_questions=boolean,
        show_hidden=boolean,
    )

    def record(properties):
        return dict(
            type="object",
            properties=properties,
            required=list(properties),
            additionalProperties=False,
        )

    preference_shape = record(dict(document_id=uid, revision=count, **filters))
    receipt_shape = record(
        dict(
            document_id=uid,
            command_id=uid,
            kind=dict(enum=["preferences", "hide", "unhide"]),
            expected_revision=count,
            revision=count,
            changed=boolean,
        )
    )
    post = operation in ("preferences", "visibility", "clear")
    if operation == "review":
        run_shape = analysis.schema("run")["responses"]["200"]["content"]["application/json"][
            "schema"
        ]["properties"]["run"]
        payload = dict(
            run=run_shape,
            preferences=preference_shape,
            view=dict(
                type="object",
                properties=dict(
                    schema_version=dict(
                        enum=[
                            "docx-review-view/1",
                            "docx-review-view/2",
                            "docx-review-view/3",
                            "docx-review-view/4",
                            "docx-review-view/5",
                        ]
                    )
                ),
                required=["schema_version"],
                description=(
                    "Verified docx-review-view/1, docx-review-view/2, docx-review-view/3, "
                    "docx-review-view/4 or docx-review-view/5 "
                    "presentation; full nested shapes follow the standalone contracts."
                ),
            ),
            view_sha256=digest,
            current_storage_revision=count,
            current_sha256=digest,
            matches_saved_document=boolean,
            fixture=boolean,
        )
    else:
        payload = dict(receipt=receipt_shape) if post else dict(preferences=preference_shape)
    output = dict(
        description=(
            "Explicit local development scope; no-store. Confirmed commands return their "
            "original acknowledgement on replay without reapplying preferences. "
            "A review belongs to a pinned source; compare editor RAM freshness separately."
        ),
        responses={
            "200": dict(
                description="Confirmed command receipt or source-verified review state",
                content={
                    "application/json": dict(
                        schema=record(dict(schema_version=dict(const=VERSION), **payload))
                    )
                },
            ),
            **{
                str(status): dict(description=description)
                for status, description in (
                    (404, "Scoped item not found"),
                    (409, "Preferences conflict or result not ready"),
                    (413, "Technical limit exceeded"),
                    (415, "Unsupported media"),
                    (422, "Invalid strict command"),
                    (500, "Invalid stored state"),
                    (503, "Busy or storage/schema unavailable"),
                )
            },
        },
    )
    if post:
        if operation == "clear":
            values = {}
        else:
            values = (
                dict(result_sha256=digest, hidden=boolean) if operation == "visibility" else filters
            )
        output["requestBody"] = dict(
            required=True,
            content={
                "application/json": dict(
                    schema=record(dict(command_id=uid, expected_revision=count, **values))
                )
            },
        )
    return output
