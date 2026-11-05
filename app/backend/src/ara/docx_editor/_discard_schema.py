"""Content-free complete discard-plan OpenAPI definitions."""


def extra(action):
    from ._http_schema import extra as json_extra

    result = json_extra()
    request, response = (
        ("PrepareDiscard", "DiscardPlan")
        if action == "prepare-discard"
        else ("DiscardPlan", "Discarded")
    )
    for name, part in ((request, "requestBody"), (response, "response")):
        body = {"application/json": {"schema": {"$ref": "#/components/schemas/AiraEditor" + name}}}
        if part == "requestBody":
            result[part] = dict(required=True, content=body)
        else:
            result["responses"]["200"] = dict(
                description="Scoped recovery discard response", content=body
            )
    return result


def definitions(components):
    def record(properties):
        return dict(
            type="object",
            properties=properties,
            required=list(properties),
            additionalProperties=False,
        )

    def ref(name):
        return {"$ref": "#/components/schemas/AiraEditor" + name}

    counter = components["AiraEditorControlRequest"]["properties"]["expected_command_sequence"]
    uuid = components["AiraEditorControlRequest"]["properties"]["command_id"]
    digest = dict(type="string", pattern="^[0-9a-f]{64}$")
    identity = dict(document_id=uuid, request_id=uuid)
    metadata = record(
        dict(
            selection=ref("Selection"),
            origin=record(dict(session_id=uuid, session_revision=counter, position_id=counter)),
            pending=record(dict(operation_id=uuid, request_sha256=digest)),
        )
    )
    handle = record(
        dict(
            document_id=uuid,
            prepared_checkpoint_revision=counter,
            base_storage_revision=counter,
            base_sha256=digest,
            working_sha256=digest,
            working_size_bytes=dict(type="integer", minimum=1, maximum=33554432),
            metadata=metadata,
        )
    )
    return {
        "AiraEditorPrepareDiscard": record(
            dict(expected_checkpoint_revision=counter, request_id=uuid)
        ),
        "AiraEditorDiscardHandle": handle,
        "AiraEditorDiscardPlan": dict(
            oneOf=[
                record(
                    dict(
                        kind=dict(const="working"), **identity, expected_checkpoint_revision=counter
                    )
                ),
                record(dict(kind=dict(const="pending"), **identity, handle=ref("DiscardHandle"))),
            ]
        ),
        "AiraEditorDiscarded": record(
            dict(
                kind=dict(const="discarded"),
                document_id=uuid,
                checkpoint_revision=counter,
                current=ref("Summary"),
                save_confirmation=dict(
                    type="string", enum=["not_checked", "confirmed", "unconfirmed"]
                ),
                current_matches_receipt=dict(anyOf=[dict(type="boolean"), dict(type="null")]),
            )
        ),
    }


def install_schema(app):
    previous = app.openapi

    def openapi():
        schema = previous()
        components = schema["components"]["schemas"]
        components.update(definitions(components))
        return schema

    app.openapi = openapi
