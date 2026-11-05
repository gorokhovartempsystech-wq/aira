"""Re-derive stored manifests and envelopes; no database or model access."""

import re
from dataclasses import fields
from hashlib import sha256
from uuid import UUID

from ara.docx_analysis.outline_review import prepare_outline_review, validate_outline_reply
from ara.docx_analysis.review import ReviewProvenance, prepare_review, validate_engine_reply
from ara.docx_analysis.review._models import ReviewError
from ara.docx_analysis.structured_review import (
    prepare_structured_review,
    validate_structured_reply,
)
from ara.docx_analysis.style_list_review import prepare_style_list_review, validate_style_list_reply
from ara.docx_analysis.visibility import StyleContextError
from ara.docx_analysis.visible_lists import ListSnapshot, build_list_snapshot
from ara.docx_analysis.visible_lists._models import PROFILE as LIST_PROFILE
from ara.docx_analysis.visible_main import VisibleViewError, build_visible_snapshot
from ara.docx_analysis.visible_main._models import POLICY, PROFILE
from ara.docx_analysis.visible_outline import OutlineSnapshot, build_outline_snapshot
from ara.docx_analysis.visible_outline._models import PROFILE as OUTLINE_PROFILE
from ara.docx_analysis.visible_style_lists import StyleListSnapshot, build_style_list_snapshot
from ara.docx_analysis.visible_style_lists._models import PROFILE as STYLE_LIST_PROFILE
from ara.docx_analysis.visible_word import WordSnapshot, build_word_snapshot
from ara.docx_analysis.visible_word._models import PROFILE as WORD_PROFILE
from ara.docx_analysis.word_review import prepare_word_review, validate_word_reply
from ara.docx_package import DocxError
from ara.docx_package.projection import ProjectionError

from ._json import (
    decode_command,
    decode_execution,
    encode_command,
    encode_execution,
    encoded,
    hashed,
    raw_bytes,
    valid_command,
    valid_execution,
)
from ._models import (
    AttemptBundle,
    RestoredSource,
    ResultBundle,
    SavedCheckCommand,
    SourceBundle,
    StorageCodecError,
    checked,
    counter,
    require,
    uuid,
)

LOWER_ERRORS = (ReviewError, VisibleViewError, StyleContextError, DocxError, ProjectionError)


def provenance(execution, attempt_id):
    return ReviewProvenance(attempt_id, *(getattr(execution, f.name) for f in fields(execution)))


def bound_command(command, snapshot, code):
    require(command.document_id == snapshot.document_id, code)
    if type(command) is SavedCheckCommand:
        require(
            command.storage_revision == snapshot.storage_revision
            and command.source_sha256 == snapshot.source_sha256,
            code,
        )


def review_functions(snapshot):
    # Fixed exact DTO choices, not a registry supplied by a stored/caller profile.
    # Each preparer revalidates both the DTO and original source before use.
    if type(snapshot) is WordSnapshot:
        return prepare_word_review, validate_word_reply
    if type(snapshot) is StyleListSnapshot:
        return prepare_style_list_review, validate_style_list_reply
    if type(snapshot) is OutlineSnapshot:
        return prepare_outline_review, validate_outline_reply
    if type(snapshot) is ListSnapshot:
        return prepare_structured_review, validate_structured_reply
    return prepare_review, validate_engine_reply


def admission(data, snapshot, execution, limits):
    # B1 validates the caller snapshot against the source before it is inspected.
    prepare, _ = review_functions(snapshot)
    prepare(data, snapshot, provenance=provenance(execution, UUID(int=0)), limits=limits.review)
    _admission_budget(snapshot, limits)


def _admission_budget(snapshot, limits):
    characters = sum(len(f.text) for f in snapshot.fragments)
    if type(snapshot) in (ListSnapshot, OutlineSnapshot, StyleListSnapshot, WordSnapshot):
        characters += sum(len(item.label) + (item.suffix != "nothing") for item in snapshot.lists)
    require(
        len(snapshot.fragments) <= limits.max_fragments
        and characters <= limits.max_text_characters,
        "codec_limit_exceeded",
    )


def _restored_word_request(snapshot, execution, attempt_id, limits):
    # Private continuation only after restore_source rebuilt this snapshot from
    # original bytes and compared the complete stored manifest. Detached callers
    # still enter prepare_word_review and independently rebuild their source.
    from ara.docx_analysis.review._models import checked as checked_review
    from ara.docx_analysis.visible_word._shape import validate
    from ara.docx_analysis.word_review._request import from_verified

    p = provenance(execution, attempt_id)
    review_limits = checked_review(p, limits.review)
    validate(snapshot, review_limits.view)
    return from_verified(snapshot, p, review_limits)


def capture_source(data, snapshot, *, command, execution, limits=None):
    limits = checked(limits)
    valid_command(command)
    valid_execution(execution)
    raw_bytes(data, limits.max_source_bytes, "invalid_input")
    admission(data, snapshot, execution, limits)
    bound_command(command, snapshot, "invalid_input")
    manifest = encoded(snapshot, limits.max_manifest_bytes, omit_hash=True)
    require(manifest.sha256 == snapshot.snapshot_sha256)
    cmd = encode_command(command, limits=limits)
    spec = encode_execution(execution, limits=limits)
    return SourceBundle(
        snapshot.document_id,
        snapshot.storage_revision,
        data,
        snapshot.source_sha256,
        snapshot.profile,
        snapshot.policy_version,
        manifest.data,
        manifest.sha256,
        cmd.data,
        cmd.sha256,
        spec.data,
        spec.sha256,
        execution.execution_kind,
    )


def check_source(source, limits):
    require(type(source) is SourceBundle, "corrupt_record")
    require(
        uuid(getattr(source, "document_id", None))
        and counter(getattr(source, "storage_revision", None)),
        "corrupt_record",
    )
    # Bound every buffer before hashing or parsing any one of them.
    bounds = (
        ("source_data", "source_sha256", limits.max_source_bytes),
        ("snapshot_data", "snapshot_sha256", limits.max_manifest_bytes),
        ("command_data", "command_sha256", limits.max_command_bytes),
        ("execution_spec", "execution_spec_sha256", limits.max_execution_bytes),
    )
    for name, _, maximum in bounds:
        raw_bytes(getattr(source, name, None), maximum)
    for name, digest, maximum in bounds:
        hashed(getattr(source, name), getattr(source, digest, None), maximum)
    require(type(getattr(source, "format_version", None)) is int, "corrupt_record")
    require(source.format_version == 1, "unsupported_version")
    for name, allowed in (
        ("profile", (PROFILE, LIST_PROFILE, OUTLINE_PROFILE, STYLE_LIST_PROFILE, WORD_PROFILE)),
        ("policy_version", (POLICY,)),
    ):
        value = getattr(source, name, None)
        require(
            type(value) is str and re.fullmatch(r"[a-z0-9][a-z0-9/_.-]{0,127}", value) is not None,
            "corrupt_record",
        )
        require(value in allowed, "unsupported_version")
    require(
        type(getattr(source, "execution_kind", None)) is str
        and source.execution_kind in ("fixture", "local_model"),
        "corrupt_record",
    )


def lower_corruption(error):
    code = "codec_limit_exceeded" if "limit" in error.code else "corrupt_record"
    raise StorageCodecError(code) from None


def restore_source(source, *, limits=None):
    limits = checked(limits)
    check_source(source, limits)
    command = decode_command(
        source.command_data, expected_sha256=source.command_sha256, limits=limits
    )
    execution = decode_execution(
        source.execution_spec, expected_sha256=source.execution_spec_sha256, limits=limits
    )
    require(execution.execution_kind == source.execution_kind, "corrupt_record")
    try:
        builder = build_list_snapshot if source.profile == LIST_PROFILE else build_visible_snapshot
        if source.profile == OUTLINE_PROFILE:
            builder = build_outline_snapshot
        elif source.profile == STYLE_LIST_PROFILE:
            builder = build_style_list_snapshot
        elif source.profile == WORD_PROFILE:
            builder = build_word_snapshot
        snapshot = builder(
            source.source_data,
            document_id=source.document_id,
            storage_revision=source.storage_revision,
            source_sha256=source.source_sha256,
            limits=limits.review.view,
        )
        manifest = encoded(snapshot, limits.max_manifest_bytes, omit_hash=True)
        require(
            manifest.data == source.snapshot_data and manifest.sha256 == source.snapshot_sha256,
            "corrupt_record",
        )
        if type(snapshot) is WordSnapshot:
            _restored_word_request(snapshot, execution, UUID(int=0), limits)
            _admission_budget(snapshot, limits)
        else:
            admission(source.source_data, snapshot, execution, limits)
    except LOWER_ERRORS as e:
        lower_corruption(e)
    bound_command(command, snapshot, "corrupt_record")
    return RestoredSource(snapshot, command, execution)


def prepare_attempt(source, *, attempt_id, limits=None):
    limits = checked(limits)
    require(uuid(attempt_id))
    restored = restore_source(source, limits=limits)
    if type(restored.snapshot) is WordSnapshot:
        request = _restored_word_request(restored.snapshot, restored.execution, attempt_id, limits)
    else:
        prepare, _ = review_functions(restored.snapshot)
        request = prepare(
            source.source_data,
            restored.snapshot,
            provenance=provenance(restored.execution, attempt_id),
            limits=limits.review,
        )
    return AttemptBundle(attempt_id, request.wire_json, request.request_sha256)


def check_attempt(attempt, limits):
    require(
        type(attempt) is AttemptBundle and uuid(getattr(attempt, "attempt_id", None)),
        "corrupt_record",
    )
    hashed(
        getattr(attempt, "request_data", None),
        getattr(attempt, "request_sha256", None),
        limits.review.max_wire_bytes,
    )


def capture_result(source, attempt, *, reply, limits=None):
    limits = checked(limits)
    raw_bytes(reply, limits.review.max_reply_bytes, "invalid_input")
    check_attempt(attempt, limits)
    restored = restore_source(source, limits=limits)
    p = provenance(restored.execution, attempt.attempt_id)
    if type(restored.snapshot) is WordSnapshot:
        from ara.docx_analysis.word_review._request import from_verified
        from ara.docx_analysis.word_review._restored import capture_restored

        # restore_source just rebuilt and verified this exact source and all
        # budgets. Keep that proof local; do not reparse it in this continuation.
        request = from_verified(restored.snapshot, p, limits.review)
        require(
            request.wire_json == attempt.request_data
            and request.request_sha256 == attempt.request_sha256,
            "corrupt_record",
        )
        result = capture_restored(
            source.source_data,
            restored.snapshot,
            provenance=p,
            attempt=attempt,
            reply=reply,
            limits=limits.review,
        )
    else:
        prepare, validate = review_functions(restored.snapshot)
        request = prepare(source.source_data, restored.snapshot, provenance=p, limits=limits.review)
        require(
            request.wire_json == attempt.request_data
            and request.request_sha256 == attempt.request_sha256,
            "corrupt_record",
        )
        result = validate(
            source.source_data,
            restored.snapshot,
            provenance=p,
            request=request,
            reply=reply,
            limits=limits.review,
        )
    return ResultBundle(
        reply,
        sha256(reply).hexdigest(),
        result.wire_json,
        result.result_sha256,
        result.findings_count,
        result.questions_count,
        result.no_findings,
    )


def restore_result(source, attempt, result, *, limits=None):
    from ._verification import restore_with_proof

    return restore_with_proof(_restore_result, source, attempt, result, limits=limits)


def _restore_result(source, attempt, result, *, limits=None):
    limits = checked(limits)
    require(type(result) is ResultBundle, "corrupt_record")
    check_source(source, limits)
    check_attempt(attempt, limits)
    for name, maxval in (
        ("reply_data", limits.review.max_reply_bytes),
        ("result_data", limits.review.max_wire_bytes),
    ):
        raw_bytes(getattr(result, name, None), maxval)
    hashed(result.reply_data, getattr(result, "reply_sha256", None), limits.review.max_reply_bytes)
    hashed(result.result_data, getattr(result, "result_sha256", None), limits.review.max_wire_bytes)
    require(
        type(getattr(result, "findings_count", None)) is int
        and 0 <= result.findings_count <= 10000
        and type(getattr(result, "questions_count", None)) is int
        and 0 <= result.questions_count <= 10000
        and type(getattr(result, "no_findings", None)) is bool,
        "corrupt_record",
    )
    require(
        result.findings_count <= limits.review.max_issues
        and result.questions_count <= limits.review.max_questions,
        "codec_limit_exceeded",
    )
    try:
        expected = capture_result(source, attempt, reply=result.reply_data, limits=limits)
    except LOWER_ERRORS as e:
        lower_corruption(e)
    require(
        all(getattr(result, f.name) == getattr(expected, f.name) for f in fields(ResultBundle)),
        "corrupt_record",
    )
    # Return a B1 envelope, never the supplied storage DTO.
    from ara.docx_analysis.review import ReviewEnvelope

    return ReviewEnvelope(
        expected.result_data,
        expected.result_sha256,
        expected.findings_count,
        expected.questions_count,
        expected.no_findings,
    )
