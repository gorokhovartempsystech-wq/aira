"""Deferred OpenAPI dictionaries for the strict editor JSON protocol."""


def definitions():
    uuid = dict(
        type="string",
        format="uuid",
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    )
    counter = dict(
        type="string",
        pattern=r"^(0|[1-9][0-9]{0,18})$",
        maxLength=19,
        description="Canonical decimal integer 0..9223372036854775807",
    )
    digest = dict(type="string", pattern="^[0-9a-f]{64}$")
    integer = dict(type="integer", minimum=0, maximum=2147483647)
    null = dict(type="null")

    def ref(name):
        return {"$ref": "#/components/schemas/AiraEditor" + name}

    def nullable(schema):
        return dict(anyOf=[schema, null])

    def record(properties, required=None):
        return dict(
            type="object",
            properties=properties,
            required=list(properties) if required is None else required,
            additionalProperties=False,
        )

    def array(items, maximum=1000):
        return dict(type="array", items=items, maxItems=maximum)

    anchor = record(
        dict(
            source_sha256=digest,
            part_name=dict(type="string", minLength=1, maxLength=1024),
            path=dict(
                type="array",
                items=dict(type="integer", minimum=0, maximum=100000),
                minItems=1,
                maxItems=128,
            ),
        )
    )
    caret = record(
        dict(
            anchor=ref("Anchor"),
            offset=integer,
            affinity=dict(type="string", enum=["left", "right"], default="right"),
        ),
        ["anchor", "offset"],
    )
    target = record(
        dict(
            block_index=integer,
            offset=integer,
            affinity=dict(type="string", enum=["left", "right"], default="right"),
        ),
        ["block_index", "offset"],
    )
    selection = record(dict(anchor=ref("Caret"), focus=ref("Caret")))
    selection_target = record(dict(anchor=ref("CaretTarget"), focus=ref("CaretTarget")))
    position = record(dict(anchor=ref("Anchor"), offset=integer))
    text = dict(type="string", maxLength=1000000)
    range_edit = record(
        dict(start=position, end=position, expected_text=text, replacement_text=text)
    )
    insertion = record(
        dict(
            kind=dict(const="insert"),
            anchor=ref("Anchor"),
            expected_text=text,
            texts=array(text) | {"minItems": 1, "default": [""]},
            position=dict(type="string", enum=["before", "after"], default="after"),
        ),
        ["kind", "anchor", "expected_text"],
    )
    deletion = record(dict(kind=dict(const="delete"), anchor=ref("Anchor"), expected_text=text))
    formatting = record(
        dict(
            anchor=ref("Anchor"),
            expected_text=text,
            style_id=nullable(dict(type="string", minLength=1, maxLength=255)),
            list_kind=dict(type="string", enum=["none", "bullet", "numbered"], default="none"),
            list_id=nullable(dict(type="string", pattern="^[1-9][0-9]{0,9}$")),
        ),
        ["anchor", "expected_text"],
    )
    variants = []
    from ._commands import ACTIONS

    for action in ACTIONS:
        value, after = null, null
        required = ["action"]
        if action == "capture":
            value = ref("Selection")
            required.append("value")
        elif action == "insert_table":
            value = record(
                dict(
                    rows=dict(type="integer", minimum=1, maximum=100),
                    columns=dict(type="integer", minimum=1, maximum=32),
                )
            )
            value["description"] = "Empty table at the collapsed body caret; at most 1024 cells."
            required.append("value")
        elif action == "insert_image":
            from ara.docx_package.editor._images import MAX_BASE64

            value = record(
                dict(
                    data_base64=dict(
                        type="string", contentEncoding="base64", minLength=4, maxLength=MAX_BASE64
                    ),
                    alt_text=dict(type="string", maxLength=2000, default=""),
                ),
                ["data_base64"],
            )
            value["description"] = (
                "Static PNG or baseline/progressive JPEG; 4 MiB, 20 million pixels; "
                "collapsed body caret."
            )
            required.append("value")
        elif action in ("insert_text", "paste_text"):
            value = dict(type="string", maxLength=100000 if action == "insert_text" else 1000000)
            required.append("value")
        elif action in ("range_edit", "structure", "format"):
            value = array(
                range_edit
                if action == "range_edit"
                else formatting
                if action == "format"
                else dict(oneOf=[insertion, deletion])
            )
            after = (
                nullable(ref("SelectionTarget")) if action == "format" else ref("SelectionTarget")
            )
            required.append("value")
            if action != "format":
                required.append("after")
        variants.append(record(dict(action=dict(const=action), value=value, after=after), required))
    identity = dict(
        command_id=uuid, expected_command_sequence=counter, expected_session_revision=counter
    )
    summary = record(
        dict(
            document_id=uuid,
            title=dict(type="string"),
            storage_revision=counter,
            current_sha256=digest,
            current_size_bytes=dict(type="integer", minimum=1, maximum=33554432),
            created_at=dict(type="string", format="date-time"),
            updated_at=dict(type="string", format="date-time"),
        )
    )
    latest = record(
        dict(
            command_id=uuid,
            request_sha256=digest,
            action=dict(type="string"),
            expected_command_sequence=counter,
            expected_session_revision=counter,
            result_command_sequence=counter,
            result_session_revision=counter,
            result_position_id=counter,
        )
    )
    active = record(
        dict(
            command_id=uuid,
            action=dict(type="string"),
            request_sha256=digest,
            expected_command_sequence=counter,
            expected_session_revision=counter,
            stage=dict(type="string"),
            operation_id=nullable(uuid),
            save_state=nullable(dict(type="string")),
        )
    )
    meta = record(
        dict(
            kind=dict(const="editor"),
            registry_id=uuid,
            document_id=uuid,
            session_id=uuid,
            command_sequence=counter,
            base_storage_revision=counter,
            base_sha256=digest,
            checkpoint_revision=counter,
            observed_current=ref("Summary"),
            observed_checkpoint_revision=counter,
            observed_checkpoint_phase=dict(type="string"),
            state=dict(type="string"),
            recovery_operation_id=nullable(uuid),
            last_command=nullable(ref("Latest")),
            active_command=nullable(ref("Active")),
            position_id=counter,
            selection=ref("Selection"),
            document=record(
                dict(
                    session_revision=counter,
                    source_sha256=digest,
                    main_part=dict(type="string"),
                    size_bytes=dict(type="integer", minimum=1, maximum=33554432),
                    is_dirty=dict(type="boolean"),
                    undo_depth=integer,
                    redo_depth=integer,
                )
            ),
        )
    )
    recovery = record(
        dict(
            kind=dict(const="recovery"),
            registry_id=uuid,
            open_sequence=counter,
            document=ref("Summary"),
            checkpoint_revision=counter,
            phase=dict(type="string"),
            base_storage_revision=nullable(counter),
            base_sha256=nullable(digest),
            working_sha256=nullable(digest),
            working_size_bytes=nullable(integer),
            selection=nullable(ref("Selection")),
            origin=nullable(
                record(dict(session_id=uuid, session_revision=counter, position_id=counter))
            ),
            pending_status=nullable(dict(type="string")),
            operation_id=nullable(uuid),
        )
    )
    closed = record(
        dict(
            kind=dict(const="closed"),
            registry_id=uuid,
            document_id=uuid,
            session_id=uuid,
            mode=dict(type="string", enum=["checkpoint", "release_local"]),
            checkpoint_revision=nullable(counter),
        )
    )
    opened = record(
        dict(
            kind=dict(const="opened"),
            view=ref("Metadata"),
            accepted_open_sequence=counter,
            next_open_sequence=counter,
        )
    )
    projection = record(
        dict(
            kind=dict(const="editor_projection"),
            view=ref("Metadata"),
            projection=record(
                dict(
                    source_sha256=digest,
                    main_part=dict(type="string"),
                    body_anchor={"$ref": "#/components/schemas/ViewAnchor"},
                    coverage_scope=dict(const="main-body-structural-v1"),
                    has_unprojected_content=dict(type="boolean"),
                    blocks=array(
                        dict(
                            oneOf=[
                                {"$ref": "#/components/schemas/" + n}
                                for n in ("ViewParagraph", "ViewTable", "ViewOpaque")
                            ]
                        ),
                        5000,
                    ),
                    notices=array({"$ref": "#/components/schemas/ViewNotice"}, 5000),
                )
            ),
        )
    )
    result = dict(
        Anchor=anchor,
        Caret=caret,
        CaretTarget=target,
        Selection=selection,
        SelectionTarget=selection_target,
        Summary=summary,
        Latest=latest,
        Active=active,
        Metadata=meta,
        Recovery=recovery,
        Closed=closed,
        Opened=opened,
        Projection=projection,
        OpenRequest=record(
            dict(
                registry_id=uuid,
                client_open_id=uuid,
                expected_open_sequence=counter,
                expected_checkpoint_revision=counter,
                mode=dict(type="string", enum=["current", "recover"]),
            )
        ),
        CommandRequest=record({**identity, "command": dict(oneOf=variants)}),
        ControlRequest=record(identity),
        CloseRequest=record(
            {
                **identity,
                "mode": dict(
                    type="string", enum=["checkpoint", "release_local"], default="checkpoint"
                ),
            },
            list(identity),
        ),
    )
    return {"AiraEditor" + name: schema for name, schema in result.items()}


def extra(request=None, response="Metadata"):
    result = {"responses": {}}
    schema = (
        {"oneOf": [{"$ref": "#/components/schemas/AiraEditor" + n} for n in ("Metadata", "Closed")]}
        if response == "Control"
        else {"$ref": "#/components/schemas/AiraEditor" + response}
    )
    result["responses"]["200"] = {
        "description": "Scoped editor response",
        "content": {"application/json": {"schema": schema}},
    }
    for code in (404, 409, 410, 413, 415, 422, 500, 503):
        result["responses"][str(code)] = {
            "description": "Sanitized editor error",
            "content": {
                "application/json": {"schema": {"$ref": "#/components/schemas/DraftErrorResponse"}}
            },
        }
    if request:
        result["requestBody"] = {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/AiraEditor" + request}
                }
            },
        }
    return result


def install_schema(app):
    previous = app.openapi

    def openapi():
        schema = previous()
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        from ara.docx_documents.view_schemas import DocxView
        from ara.drafts.http_schemas import DraftErrorResponse

        for name, value in (
            DocxView.model_json_schema(ref_template="#/components/schemas/{model}")
            .get("$defs", {})
            .items()
        ):
            components.setdefault(name, value)
        components.setdefault("DraftErrorResponse", DraftErrorResponse.model_json_schema())
        components.update(definitions())
        return schema

    app.openapi = openapi
