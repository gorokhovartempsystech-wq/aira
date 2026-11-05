"""Revalidate both complete records before deriving any correspondence."""

import json
from collections import defaultdict

from ara.docx_analysis.presentation._view import _keys
from ara.docx_analysis.storage_codec import StorageCodecError, restore_result
from ara.docx_analysis.visible_lists._models import PROFILE as STRUCTURED_PROFILE
from ara.docx_analysis.visible_outline._models import PROFILE as OUTLINE_PROFILE
from ara.docx_analysis.visible_style_lists._models import PROFILE as STYLE_LIST_PROFILE
from ara.docx_analysis.visible_word._models import PROFILE as WORD_PROFILE

from ._context import context, encode, paragraph_matches
from ._models import FindingTransfer, RemapError, RemapLimits, require


def verified(records, limits):
    require(type(records) is tuple and len(records) == 3, "invalid_input")
    result = restore_result(*records)
    body, snapshot = json.loads(result.wire_json), json.loads(records[0].snapshot_data)
    require(
        len(snapshot["paragraphs"]) <= limits.max_paragraphs
        and len(body["findings"]) <= limits.max_findings,
        "limit_exceeded",
    )
    return body, snapshot, {k.finding_id: k.key for k in _keys(body)}


def signature(finding, fragments, mapping, rules):
    values = {
        key: value
        for key, value in finding.items()
        if key not in ("finding_id", "primary", "related")
    }
    values["rule"] = rules[finding["finding_id"]]
    for name in ("primary", "related"):
        evidence = finding[name]
        if evidence is None:
            values[name] = None
            continue
        identity = evidence["fragment_id"]
        if identity not in mapping:
            return None
        path = fragments[identity]["paragraph_anchor"]["path"]

        def relative(anchor):
            require(anchor["path"][: len(path)] == path)
            return dict(part_name=anchor["part_name"], path=anchor["path"][len(path) :])

        slices = [
            {
                key: relative(value)
                if key in ("anchor", "run_anchor", "paragraph_anchor")
                else value
                for key, value in piece.items()
            }
            for piece in evidence["slices"]
        ]
        values[name] = dict(evidence, fragment_id=mapping[identity], slices=slices)
    return encode(values)


def _match(previous, current, limits):
    old, old_snapshot, old_keys = verified(previous, limits)
    new, new_snapshot, new_keys = verified(current, limits)
    require(old["source"]["document_id"] == new["source"]["document_id"], "invalid_input")

    def identity(body):
        return (
            body["profile"],
            body["policy_version"],
            {key: value for key, value in body["provenance"].items() if key != "attempt_id"},
        )

    if identity(old) != identity(new):
        return ()
    if old["source"]["source_sha256"] == new["source"]["source_sha256"]:
        target = {key: fid for fid, key in new_keys.items()}
        pairs = [(fid, target[key]) for fid, key in old_keys.items() if key in target]
    else:
        if old["profile"] in (
            STRUCTURED_PROFILE,
            OUTLINE_PROFILE,
            STYLE_LIST_PROFILE,
            WORD_PROFILE,
        ):
            from .structured import fragment_matches

            mapping = fragment_matches(previous[0], old_snapshot, current[0], new_snapshot)
        else:
            mapping = paragraph_matches(
                context(previous[0], old_snapshot), context(current[0], new_snapshot)
            )
        indexes = []
        for body, snapshot, correspondence in (
            (old, old_snapshot, mapping),
            (
                new,
                new_snapshot,
                {f["fragment_id"]: f["fragment_id"] for f in new_snapshot["fragments"]},
            ),
        ):
            rules = {p["finding_id"]: p["rule"] for p in body["private_provenance"]}
            fragments = {f["fragment_id"]: f for f in snapshot["fragments"]}
            index = defaultdict(list)
            for finding in body["findings"]:
                key = signature(finding, fragments, correspondence, rules)
                if key is not None:
                    index[key].append(finding["finding_id"])
            indexes.append(index)
        left, right = indexes
        pairs = [
            (ids[0], right[key][0])
            for key, ids in left.items()
            if len(ids) == 1 and len(right.get(key, ())) == 1
        ]
    return tuple(FindingTransfer(a, old_keys[a], b, new_keys[b]) for a, b in sorted(pairs))


def match_findings(previous, current, *, limits=None):
    limits = RemapLimits() if limits is None else limits
    require(type(limits) is RemapLimits, "invalid_input")
    limits.__post_init__()
    try:
        return _match(previous, current, limits)
    except RemapError:
        raise
    except StorageCodecError as error:
        raise RemapError(
            "limit_exceeded" if error.code == "codec_limit_exceeded" else "corrupt_result"
        ) from None
    except Exception:
        raise RemapError("corrupt_result") from None
