"""Opt-in draft reply extension; all evidence is mapped against original DOCX."""

from ara.docx_analysis.review._json import fingerprint
from ara.docx_analysis.review._models import budget, require, text
from ara.docx_analysis.review._reply import keys
from ara.docx_analysis.visible_main import VisibleSpanRequest

VERSION = "docx-review/6-draft-1"
MARKER = "aira-review-extensions/1"
CHECKS = {"formulation", "duplicate", "contradiction"}


def parse(raw, snapshot, limits):
    keys(raw, "schema_version analysis_coverage standalone_questions")
    require(raw["schema_version"] == MARKER)
    c = raw["analysis_coverage"]
    keys(
        c,
        "state reason planned_checks completed_checks pair_selection "
        "pair_candidates_total pair_candidates_completed",
    )
    require(c["state"] in ("complete", "partial"))
    for k in ("planned_checks", "completed_checks"):
        values = c[k]
        require(type(values) is list and all(type(v) is str and v in CHECKS for v in values))
        require(len(values) == len(set(values)))
    require(bool(c["planned_checks"]) and set(c["completed_checks"]) <= set(c["planned_checks"]))
    require(c["pair_selection"] in ("top_k", "exhaustive", "none"))
    total, done = c["pair_candidates_total"], c["pair_candidates_completed"]
    require(
        (total is None and done is None)
        or (type(total) is int and type(done) is int and 0 <= done <= total <= 100000000)
    )
    if c["pair_selection"] == "none":
        require(total in (None, 0) and done in (None, 0))
    if c["state"] == "complete":
        require(c["reason"] is None and set(c["planned_checks"]) == set(c["completed_checks"]))
        require(total == done)
    else:
        require(c["reason"] in ("deadline", "resource_limit"))
    questions = raw["standalone_questions"]
    require(type(questions) is list)
    budget(len(questions), limits.max_questions)
    fragments = {f.fragment_id: f.text for f in snapshot.fragments}
    requests, prepared = [], []
    for q in questions:
        keys(q, "text reason references")
        text(q["text"], limits.max_metadata_characters)
        text(q["reason"], limits.max_metadata_characters)
        refs = q["references"]
        require(type(refs) is list and 1 <= len(refs) <= 16)
        seen = set()
        for ref in refs:
            keys(ref, "fragment_id start end")
            fid, start, end = ref["fragment_id"], ref["start"], ref["end"]
            require(type(fid) is str and fid in fragments)
            require(
                type(start) is int and type(end) is int and 0 <= start < end <= len(fragments[fid])
            )
            key = (fid, start, end)
            require(key not in seen)
            seen.add(key)
            requests.append(VisibleSpanRequest(fid, start, end, fragments[fid][start:end]))
        prepared.append(q)
    return c, prepared, tuple(requests)


def attach(common, coverage, questions, mapped, snapshot, limits):
    fragments = {f.fragment_id: f.text for f in snapshot.fragments}
    output, seen = [], set()
    i = 0
    for q in questions:
        evidence = []
        for ref in q["references"]:
            span = mapped[i]
            i += 1
            evidence.append(
                dict(
                    fragment_id=span.fragment_id,
                    start=span.start,
                    end=span.end,
                    quote=fragments[span.fragment_id][span.start : span.end],
                    slices=span.slices,
                )
            )
        evidence.sort(key=lambda x: (x["fragment_id"], x["start"], x["end"]))
        item = dict(text=q["text"], reason=q["reason"], evidence=tuple(evidence))
        identity = "sq-" + fingerprint(
            dict(
                domain=VERSION,
                source=common["source"],
                snapshot_sha256=common["snapshot_sha256"],
                request_sha256=common["request_sha256"],
                item=item,
            ),
            limits.max_wire_bytes,
        )
        require(identity not in seen)
        seen.add(identity)
        output.append(dict(question_id=identity, **item))
    budget(len(common["questions"]) + len(output), limits.max_questions)
    common.update(
        schema_version=VERSION, analysis_coverage=coverage, standalone_questions=tuple(output)
    )
    common["counts"]["questions"] += len(output)
    common["no_findings"] = common["no_findings"] and coverage["state"] == "complete" and not output
