"""SYNTHETIC review example only. No inference, file access or real quality claim."""

import re
from dataclasses import fields
from hashlib import sha256

from ara.docx_analysis.storage_codec import ExecutionSpec, decode_execution
from ara.docx_analysis.storage_codec._json import canonical_counter, canonical_uuid, encoded, parsed
from ara.docx_analysis.storage_codec._models import digest
from ara.docx_analysis.visible_main._models import POLICY, PROFILE

from .wire import WireMessage
from .wire._codec import binding_copy


class ReviewFixtureError(ValueError):
    def __init__(self):
        super().__init__("Invalid review fixture input.")


def fixture_execution():
    return ExecutionSpec(
        execution_kind="fixture",
        engine_version="0.1.0",
        models_version="aira-review-fixture-1",
        model_sha256=sha256(b"aira-review-fixture-model/1").hexdigest(),
        adapter_sha256=sha256(b"aira-review-fixture-adapter/1").hexdigest(),
    )


def _require(value):
    if not value:
        raise ReviewFixtureError()


def _keys(value, names):
    _require(type(value) is dict and set(value) == set(names.split()))


def _request_header(request, expected_execution):
    _require(
        type(request) is WireMessage
        and request.kind == "run"
        and type(request.seq) is int
        and request.seq == 0
    )
    binding = binding_copy(request.binding)
    values = dict(request.values)
    _keys(values, "worker_instance_id claim_fence request_sha256 execution_spec_sha256")
    canonical_uuid(values["worker_instance_id"])
    _require(type(values["claim_fence"]) is int and values["claim_fence"] == 1)
    execution = decode_execution(
        request.execution_spec, expected_sha256=values["execution_spec_sha256"]
    )
    _require(execution == expected_execution)
    body = parsed(request.payload, values["request_sha256"], 8 * 1024 * 1024)
    _keys(
        body,
        "schema_version kind source snapshot_sha256 profile policy_version "
        "provenance engine_request",
    )
    _require(body["kind"] == "review_request")
    _require(digest(body["snapshot_sha256"]))
    provenance = {f.name: getattr(execution, f.name) for f in fields(execution)}
    _require(body["provenance"] == provenance | {"attempt_id": str(binding.attempt_id)})
    source = body["source"]
    _keys(source, "document_id storage_revision source_sha256")
    canonical_uuid(source["document_id"])
    canonical_counter(source["storage_revision"], 1)
    _require(digest(source["source_sha256"]))
    return execution, body


def _fragments(engine, *, keys="fragments disabled_types dismissed"):
    _keys(engine, keys)
    _require(engine["disabled_types"] == [] and engine["dismissed"] == [])
    fragments = engine["fragments"]
    _require(type(fragments) is list and 1 <= len(fragments) <= 512)
    identities, count = set(), 0
    for f in fragments:
        _keys(f, "id text document status type offset")
        _require(type(f["id"]) is str and re.fullmatch(r"vf-[0-9a-f]{64}", f["id"]) is not None)
        _require(f["id"] not in identities)
        identities.add(f["id"])
        _require(type(f["text"]) is str and len(f["text"]) > 0)
        count += len(f["text"])
        _require(count <= 1000000)
        f["text"].encode("utf-8")
        _require(
            f["document"] == "Документ" and f["status"] == "active" and f["type"] == "фрагмент"
        )
        _require(type(f["offset"]) is int and 0 <= f["offset"] < 2**63)
    return fragments


def _example(
    execution,
    first,
    fragment_count,
    *,
    explanation="Учебный пример замечания AIRA. Реальная модель не запускалась.",
):
    quote = first["text"][:64]
    question = "Учебный пример: какое условие стоит уточнить в этом требовании?"
    issue = dict(
        id="iss-" + sha256(first["id"].encode()).hexdigest()[:10],
        type="formulation",
        severity="info",
        light="yellow",
        confidence=0,
        fragment_id=first["id"],
        span=dict(start=0, end=len(quote), quote=quote),
        related=None,
        explanation=explanation,
        rule=None,
        suggestion=None,
        question=question,
    )
    return encoded(
        dict(
            engine=execution.engine_version,
            models=execution.models_version,
            issues=[issue],
            questions=[question],
            checked=dict(fragments=fragment_count, active=fragment_count, skipped_status=0),
            seconds=0.0,
        ),
        4 * 1024 * 1024,
    ).data


def _reply(request):
    execution, body = _request_header(request, fixture_execution())
    _require(body["schema_version"] == "docx-review/1")
    _require(body["profile"] == PROFILE and body["policy_version"] == POLICY)
    fragments = _fragments(body["engine_request"])
    return _example(execution, fragments[0], len(fragments))


def reply_for(request):
    try:
        return _reply(request)
    except Exception:
        raise ReviewFixtureError() from None
