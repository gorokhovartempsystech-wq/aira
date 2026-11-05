"""Atomic semantic validation and exact source evidence for one engine reply."""

from hashlib import sha256

from ara.docx_analysis.visible_main import VisibleViewError, map_visible_spans

from ._json import decode, encode, fingerprint
from ._models import ReviewEnvelope, ReviewError, budget, checked, require
from ._reply import parse_reply
from ._request import base, check_prepared, from_verified


def evidence(mapped, quote):
    return dict(
        fragment_id=mapped.fragment_id,
        start=mapped.start,
        end=mapped.end,
        quote=quote,
        slices=mapped.slices,
    )


def validate_engine_reply(data, snapshot, *, provenance, request, reply, limits=None):
    return validate_reply(
        data,
        snapshot,
        provenance=provenance,
        request=request,
        reply=reply,
        limits=limits,
        mapper=map_visible_spans,
        request_factory=from_verified,
        base_factory=base,
    )


def validate_reply(
    data, snapshot, *, provenance, request, reply, limits, mapper, request_factory, base_factory
):
    """Private shared algorithm; public wrappers pin their source and wire profiles."""
    limits = checked(provenance, limits)
    check_prepared(request, limits)
    raw = decode(reply, limits)
    require(type(raw) is dict)
    extension = raw.get("extensions")
    if "extensions" in raw:
        require(
            base_factory(snapshot, provenance, "review_result")["schema_version"] == "docx-review/5"
        )
        from ara.docx_analysis.word_review._extensions import parse

        coverage, independent, extra_requests = parse(extension, snapshot, limits)
        raw = {k: v for k, v in raw.items() if k != "extensions"}
    else:
        extra_requests = ()
    issues, requests = parse_reply(raw, provenance, limits)
    issue_request_count = len(requests)
    requests += extra_requests
    try:
        mapped = mapper(data, snapshot, requests=requests, limits=limits.view)
    except VisibleViewError as exc:
        if exc.code in ("invalid_span", "unknown_fragment"):
            raise ReviewError("invalid_reply") from None
        raise
    expected = request_factory(snapshot, provenance, limits)
    require(request == expected, "invalid_input")
    count = len(snapshot.fragments)
    require(raw["checked"] == dict(fragments=count, active=count, skipped_status=0))
    fragment_index = {f.fragment_id: f for f in snapshot.fragments}
    common = base_factory(snapshot, provenance, "review_result")
    semantic = {k: common[k] for k in ("source", "snapshot_sha256", "profile", "policy_version")}
    semantic.update(
        {
            k: common["provenance"][k]
            for k in ("engine_version", "models_version", "model_sha256", "adapter_sha256")
        }
    )
    findings, private, question_origins, seen = [], [], {}, set()
    i = evidence_bytes = 0
    for issue in issues:
        primary = evidence(mapped[i], issue["span"]["quote"])
        i += 1
        related = None
        if issue["related"] is not None:
            r = issue["related"]
            require(fragment_index[r["fragment_id"]].text == r["quote"])
            related = evidence(mapped[i], r["quote"])
            i += 1
        # Evidence is emitted once per finding. Its cumulative encoded size is
        # a lower bound of the final wire, so reject before hashing thousands
        # of impossible-to-publish findings with long source part names.
        evidence_bytes += len(encode(primary, limits.max_wire_bytes))
        if related is not None:
            evidence_bytes += len(encode(related, limits.max_wire_bytes))
        budget(evidence_bytes, limits.max_wire_bytes)
        finding = dict(
            type=issue["type"],
            severity=issue["severity"],
            assessment=issue["light"],
            explanation=issue["explanation"],
            primary=primary,
            related=related,
            question=issue["question"],
        )
        key = semantic | finding | dict(domain="docx-review-finding/1", rule=issue["rule"])
        identity = "df-" + fingerprint(key, limits.max_wire_bytes)
        require(identity not in seen)
        seen.add(identity)
        findings.append(dict(finding_id=identity, **finding))
        private.append(
            dict(
                finding_id=identity,
                upstream_id=issue["id"],
                confidence=issue["confidence"],
                rule=issue["rule"],
                suggestion=issue["suggestion"],
            )
        )
        if issue["question"]:
            question_origins.setdefault(issue["question"], []).append(identity)
    questions = []
    for question, origins in sorted(question_origins.items()):
        ids = tuple(sorted(origins))
        key = dict(
            domain="docx-review-question/1",
            source=common["source"],
            snapshot_sha256=snapshot.snapshot_sha256,
            text=question,
            finding_ids=ids,
        )
        questions.append(
            dict(
                question_id="dq-" + fingerprint(key, limits.max_wire_bytes),
                text=question,
                finding_ids=ids,
            )
        )
    no_findings = provenance.execution_kind == "local_model" and not findings and not questions
    common.update(
        request_sha256=expected.request_sha256,
        findings=tuple(findings),
        questions=tuple(questions),
        coverage=snapshot.coverage,
        counts=dict(fragments=count, findings=len(findings), questions=len(questions)),
        no_findings=no_findings,
        private_provenance=tuple(private),
    )
    if extension is not None:
        from ara.docx_analysis.word_review._extensions import attach

        attach(common, coverage, independent, mapped[issue_request_count:], snapshot, limits)
    wire = encode(common, limits.max_wire_bytes)
    return ReviewEnvelope(
        wire,
        sha256(wire).hexdigest(),
        len(findings),
        common["counts"]["questions"],
        common["no_findings"],
    )
