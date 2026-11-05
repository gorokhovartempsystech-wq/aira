"""Document CAS transactions with source-verified aliases and original receipts."""

from sqlalchemy import delete, func, select

from ara.documents.storage import DocumentError
from ara.docx_review_preferences import _codec, _reads
from ara.docx_review_preferences._models import (
    MAX_HIDDEN,
    MAX_REVISION,
    PreferenceReceipt,
    fail,
    require,
)
from ara.docx_review_resolution._load import load_inputs, recheck_inputs
from ara.docx_review_resolution._models import bounded, checked_limits
from ara.docx_review_resolution._resolve import resolve, text_size
from ara.models import DocxReviewDismissal as Dismissal
from ara.models import DocxReviewPreferences as Preferences
from ara.models import DocxReviewReceipt as Receipt

from ._codec import make_clear


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
    limits=None,
):
    require(type(hidden) is bool)
    command = _codec.make(
        document_id,
        command_id,
        expected_revision,
        "hide" if hidden else "unhide",
        dict(run_id=run_id, result_sha256=result_sha256, finding_id=finding_id),
    )
    limits = checked_limits(limits)
    try:
        with _reads.transaction(runtime, document_id) as session:
            previous = _reads.replay(session, command)
            if previous is not None:
                return previous
            state = _reads.snapshot(session, document_id)
            if state.revision != expected_revision:
                fail("preferences_conflict")
            target = _reads.records(session, document_id, run_id, result_sha256)
            inputs = load_inputs(session, state, target, limits=limits)
        resolution = resolve(inputs)
        key = next(
            (entry.key for entry in resolution.finding_keys if entry.finding_id == finding_id), None
        )
        if key is None:
            fail("not_found")
        if hidden and key not in resolution.hidden_keys:
            if len(state.hidden_keys) >= MAX_HIDDEN:
                fail("preferences_limit_exceeded")
            _prospective(resolution)
        return _write(runtime, command, resolution=resolution, key=key)
    except DocumentError:
        raise
    except Exception:
        fail("storage_error")


def _prospective(resolution):
    active = {decision.run_id for decision in resolution.decisions}
    if resolution.target.run_id in active:
        return
    size = text_size(resolution.target)
    origins = {origin.run_id: origin for origin in (resolution.target, *resolution.origins)}
    work = size + sum(size + text_size(origins[run_id]) for run_id in active)
    bounded(work + 2 * size <= resolution.limits.max_text_characters)


def clear_hidden(runtime, *, document_id, command_id, expected_revision):
    command = make_clear(document_id, command_id, expected_revision)
    return _write(runtime, command, clear=True)


def _parent(session, state, revision, now):
    row = session.get(Preferences, state.document_id)
    if row is None:
        row = Preferences(
            document_id=state.document_id,
            revision=revision,
            disabled_types=list(state.disabled_types),
            show_questions=state.show_questions,
            show_hidden=state.show_hidden,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    else:
        row.revision = revision
        row.updated_at = max(row.updated_at, row.created_at, now)
    session.flush()


def _receipt(session, command, revision, changed, now):
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


def _write(runtime, command, *, resolution=None, key=None, clear=False):
    with _reads.transaction(runtime, command.document_id, writing=True) as session:
        previous = _reads.replay(session, command)
        if previous is not None:
            return previous
        state = _reads.snapshot(session, command.document_id)
        if state.revision != command.expected_revision:
            fail("preferences_conflict")
        if state.revision == MAX_REVISION:
            fail("preferences_history_exhausted")
        removed = ()
        if clear:
            changed = bool(state.hidden_keys)
        else:
            require(resolution is not None and key is not None, "storage_error")
            recheck_inputs(session, resolution)
            aliases = next(
                (
                    a.origin_keys
                    for a in resolution.aliases
                    if a.finding_id == command.values["finding_id"]
                ),
                (),
            )
            changed = not aliases if command.kind == "hide" else bool(aliases)
            if command.kind == "hide" and changed and len(state.hidden_keys) >= MAX_HIDDEN:
                fail("preferences_limit_exceeded")
            if command.kind == "unhide":
                removed = aliases
        revision = state.revision + 1
        now = session.scalar(select(func.clock_timestamp()))
        _parent(session, state, revision, now)
        if clear:
            session.execute(delete(Dismissal).where(Dismissal.document_id == command.document_id))
        elif command.kind == "hide" and changed:
            session.add(
                Dismissal(
                    document_id=command.document_id,
                    dismissal_key=key,
                    source_run_id=resolution.target.run_id,
                    source_result_sha256=resolution.target.result.result_sha256,
                    source_finding_id=command.values["finding_id"],
                    hidden_at_revision=revision,
                    created_at=now,
                )
            )
        elif removed:
            session.execute(
                delete(Dismissal).where(
                    Dismissal.document_id == command.document_id,
                    Dismissal.dismissal_key.in_(removed),
                )
            )
        receipt = _receipt(session, command, revision, changed, now)
    return receipt
