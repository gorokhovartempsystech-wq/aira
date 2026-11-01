"""Strict request and binary response descriptions, built without I/O."""

MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def extra(operation):
    from ._http_schema import extra as json_extra

    request = {
        "saved": "ControlRequest",
        "working": "WorkingDownloadRequest",
        "recovery": "RecoveryDownloadRequest",
    }[operation]
    result = json_extra(request)
    headers = {
        "ETag": {"schema": {"type": "string"}},
        "X-ARA-Copy-Kind": {"schema": {"const": operation}},
    }
    names = {
        "saved": ["X-ARA-Storage-Revision"],
        "working": ["X-ARA-Command-Sequence", "X-ARA-Session-Revision"],
        "recovery": ["X-ARA-Checkpoint-Revision"],
    }[operation]
    headers.update({name: {"schema": {"type": "string", "pattern": "^[0-9]+$"}} for name in names})
    result["responses"]["200"] = dict(
        description="Exact DOCX snapshot, no-store",
        content={MIME: {"schema": {"type": "string", "format": "binary"}}},
        headers=headers,
    )
    return result


def install_schema(app):
    previous = app.openapi

    def openapi():
        schema = previous()
        components = schema["components"]["schemas"]
        counter = {
            "type": "string",
            "pattern": "^(0|[1-9][0-9]{0,18})$",
            "maxLength": 19,
            "description": "Canonical decimal integer 0..9223372036854775807",
        }
        for kind, names in (
            ("Working", ("expected_command_sequence", "expected_session_revision")),
            ("Recovery", ("expected_checkpoint_revision",)),
        ):
            properties = {name: counter for name in names}
            properties["expected_sha256"] = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
            components["AiraEditor" + kind + "DownloadRequest"] = dict(
                type="object",
                properties=properties,
                required=list(properties),
                additionalProperties=False,
            )
        return schema

    app.openapi = openapi
