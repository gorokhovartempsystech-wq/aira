"""Document-serialized compare-and-swap with durable small acknowledgements."""

from sqlalchemy import func, select

from ara.docx_analysis.presentation import finding_keys
from ara.models import DocxReviewDismissal as Dismissal
from ara.models import DocxReviewPreferences as Preferences
from ara.models import DocxReviewReceipt as Receipt

from . import _codec, _reads
from ._models import MAX_HIDDEN, MAX_REVISION, PreferenceReceipt, fail, require


def set_preferences(
    runtime,
    *,
    document_id,
    command_id,
    expected_revision,
    disabled_types,
    show_questions,
    show_hidden,
):
    command = _codec.make(
        document_id,
        command_id,
        expected_revision,
        "preferences",
        dict(disabled_types=disabled_types, show_questions=show_questions, show_hidden=show_hidden),
    )
    return _apply(runtime, command)


def set_hidden(
    runtime,
    *,
    document_id,
    command_id,
    expected_revision,
    run_id,
    result_sha256,
    finding_id,
    hidden,
):
    require(type(hidden) is bool)
    command = _codec.make(
        document_id,
        command_id,
        expected_revision,
        "hide" if hidden else "unhide",
        dict(run_id=run_id, result_sha256=result_sha256, finding_id=finding_id),
    )
    with _reads.transaction(runtime, document_id) as session:
        previous = _reads.replay(session, command)
        if previous is not None:
            return previous
        if _reads.snapshot(session, document_id).revision != expected_revision:
            fail("preferences_conflict")
        origin = _reads.records(session, document_id, run_id, result_sha256)
    try:
        keys = finding_keys(origin.source, origin.attempt, origin.result)
    except Exception:
        fail("storage_error")
    key = next((item.key for item in keys if item.finding_id == finding_id), None)
    if key is None:
        fail("not_found")
    return _apply(runtime, command, origin=origin, key=key)


def _apply(runtime, command, *, origin=None, key=None):
    with _reads.transaction(runtime, command.document_id, writing=True) as session:
        previous = _reads.replay(session, command)
        if previous is not None:
            return previous
        current = _reads.snapshot(session, command.document_id)
        if current.revision != command.expected_revision:
            fail("preferences_conflict")
        if current.revision == MAX_REVISION:
            fail("preferences_history_exhausted")
        values = command.values
        if origin is not None:
            actual = _reads.records(
                session, command.document_id, values["run_id"], values["result_sha256"]
            )
            require(actual == origin, "storage_error")
        if command.kind == "preferences":
            changed = (current.disabled_types, current.show_questions, current.show_hidden) != (
                values["disabled_types"],
                values["show_questions"],
                values["show_hidden"],
            )
        else:
            require(origin is not None and key is not None, "storage_error")
            changed = (
                (key not in current.hidden_keys)
                if command.kind == "hide"
                else (key in current.hidden_keys)
            )
            if command.kind == "hide" and changed and len(current.hidden_keys) >= MAX_HIDDEN:
                fail("preferences_limit_exceeded")
        revision = current.revision + 1
        now = session.scalar(select(func.clock_timestamp()))
        row = session.get(Preferences, command.document_id)
        if row is None:
            row = Preferences(
                document_id=command.document_id,
                revision=revision,
                disabled_types=list(current.disabled_types),
                show_questions=current.show_questions,
                show_hidden=current.show_hidden,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
        else:
            row.revision = revision
            row.updated_at = max(row.updated_at, row.created_at, now)
        if command.kind == "preferences":
            row.disabled_types = list(values["disabled_types"])
            row.show_questions, row.show_hidden = values["show_questions"], values["show_hidden"]
        # Establish the parent before child rows; no mapper relationship is needed.
        session.flush()
        if command.kind == "hide" and changed:
            session.add(
                Dismissal(
                    document_id=command.document_id,
                    dismissal_key=key,
                    source_run_id=origin.run_id,
                    source_result_sha256=origin.result.result_sha256,
                    source_finding_id=values["finding_id"],
                    hidden_at_revision=revision,
                    created_at=now,
                )
            )
        elif command.kind == "unhide" and changed:
            session.delete(session.get(Dismissal, (command.document_id, key)))
        receipt = PreferenceReceipt(
            command.document_id,
            command.command_id,
            command.kind,
            command.expected_revision,
            revision,
            changed,
        )
        raw, digest = _codec.response(receipt)
        session.add(
            Receipt(
                document_id=command.document_id,
                command_id=command.command_id,
                expected_revision=command.expected_revision,
                revision=revision,
                kind=command.kind,
                command_data=command.data,
                command_sha256=command.sha256,
                response_data=raw,
                response_sha256=digest,
                created_at=now,
            )
        )
        session.flush()
    return receipt
