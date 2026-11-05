"""Presentation filters and exact-source dismissal identities over B2 records."""

import json
import re
from dataclasses import dataclass, field
from hashlib import sha256

from ara.docx_analysis.storage_codec import StorageCodecError, restore_result

TYPES = ("formulation", "duplicate", "contradiction")
MAX_KEYS = 10000
MAX_VIEW = 16 * 1024 * 1024


class PresentationError(ValueError):
    def __init__(self, code="invalid_input"):
        self.code = (
            code
            if code in ("invalid_input", "corrupt_result", "limit_exceeded")
            else "invalid_input"
        )
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class FindingKey:
    finding_id: str
    key: str


@dataclass(frozen=True, slots=True)
class Presentation:
    wire_json: bytes = field(repr=False)
    view_sha256: str
    total_findings: int
    visible_findings: int
    hidden_findings: int
    visible_questions: int
    no_findings: bool
    no_visible_findings: bool


def _require(condition, code="invalid_input"):
    if not condition:
        raise PresentationError(code)


def _encode(value):
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    _require(len(raw) <= MAX_VIEW, "limit_exceeded")
    return raw


def _verified(source, attempt, result):
    try:
        envelope = restore_result(source, attempt, result)
        return json.loads(envelope.wire_json), envelope.result_sha256
    except StorageCodecError as error:
        code = "limit_exceeded" if error.code == "codec_limit_exceeded" else "corrupt_result"
        raise PresentationError(code) from None
    except Exception:
        raise PresentationError("corrupt_result") from None


def _keys(body):
    common = dict(
        domain="docx-dismissal/1",
        document_id=body["source"]["document_id"],
        source_sha256=body["source"]["source_sha256"],
        profile=body["profile"],
        policy_version=body["policy_version"],
        provenance={key: value for key, value in body["provenance"].items() if key != "attempt_id"},
    )
    rules = {item["finding_id"]: item["rule"] for item in body["private_provenance"]}

    def evidence(value):
        # On identical source bytes these exact anchors are stable even when
        # storage revision and thus the visible fragment ID have changed.
        return (
            None
            if value is None
            else {key: item for key, item in value.items() if key != "fragment_id"}
        )

    keys = []
    for finding in body["findings"]:
        semantics = {
            key: value
            for key, value in finding.items()
            if key not in ("finding_id", "primary", "related")
        }
        semantics.update(
            primary=evidence(finding["primary"]),
            related=evidence(finding["related"]),
            rule=rules[finding["finding_id"]],
        )
        digest = sha256(_encode(common | dict(finding=semantics))).hexdigest()
        keys.append(FindingKey(finding["finding_id"], "dh-" + digest))
    return tuple(keys)


def finding_keys(source, attempt, result):
    body, _ = _verified(source, attempt, result)
    return _keys(body)


def _preferences(disabled_types, show_questions, hidden_keys, show_hidden):
    _require(type(disabled_types) in (list, tuple) and type(hidden_keys) in (list, tuple))
    _require(type(show_questions) is bool and type(show_hidden) is bool)
    _require(len(disabled_types) <= len(TYPES) and len(hidden_keys) <= MAX_KEYS, "limit_exceeded")
    _require(all(type(value) is str and value in TYPES for value in disabled_types))
    _require(len(set(disabled_types)) == len(disabled_types))
    _require(
        all(type(value) is str and re.fullmatch(r"dh-[0-9a-f]{64}", value) for value in hidden_keys)
    )
    _require(len(set(hidden_keys)) == len(hidden_keys))
    return set(disabled_types), set(hidden_keys)


def present(
    source,
    attempt,
    result,
    *,
    disabled_types=(),
    show_questions=True,
    hidden_keys=(),
    show_hidden=False,
):
    disabled, hidden = _preferences(disabled_types, show_questions, hidden_keys, show_hidden)
    body, stored_hash = _verified(source, attempt, result)
    hidden_ids = {item.finding_id for item in _keys(body) if item.key in hidden}
    findings = []
    for finding in body["findings"]:
        if finding["type"] in disabled or (finding["finding_id"] in hidden_ids and not show_hidden):
            continue
        findings.append(finding if show_questions else dict(finding, question=None))
    visible_ids = {finding["finding_id"] for finding in findings}
    questions = []
    if show_questions:
        for question in body["questions"]:
            origins = [identity for identity in question["finding_ids"] if identity in visible_ids]
            if origins:
                questions.append(dict(question, visible_finding_ids=origins))
    counts = dict(
        total_findings=body["counts"]["findings"],
        total_questions=body["counts"]["questions"],
        visible_findings=len(findings),
        visible_questions=len(questions),
        hidden_findings=len(hidden_ids),
        filtered_findings=sum(finding["type"] in disabled for finding in body["findings"]),
    )
    view = dict(
        schema_version="docx-review-view/1",
        source=body["source"],
        profile=body["profile"],
        policy_version=body["policy_version"],
        provenance=body["provenance"],
        snapshot_sha256=body["snapshot_sha256"],
        coverage=body["coverage"],
        stored_result_sha256=stored_hash,
        findings=findings,
        questions=questions,
        hidden_finding_ids=sorted(hidden_ids),
        counts=counts,
        preferences=dict(
            disabled_types=sorted(disabled), show_questions=show_questions, show_hidden=show_hidden
        ),
        no_findings=body["no_findings"],
        no_visible_findings=not findings,
        fixture=body["provenance"]["execution_kind"] == "fixture",
    )
    if body["schema_version"] == "docx-review/2":
        view.update(schema_version="docx-review-view/2", document_context=body["document_context"])
    elif body["schema_version"] == "docx-review/3":
        view.update(schema_version="docx-review-view/3", document_context=body["document_context"])
    elif body["schema_version"] == "docx-review/4":
        view.update(schema_version="docx-review-view/4", document_context=body["document_context"])
    elif body["schema_version"] == "docx-review/5":
        view.update(schema_version="docx-review-view/5", document_context=body["document_context"])
    raw = _encode(view)
    return Presentation(
        raw,
        sha256(raw).hexdigest(),
        counts["total_findings"],
        len(findings),
        len(hidden_ids),
        len(questions),
        body["no_findings"],
        not findings,
    )
