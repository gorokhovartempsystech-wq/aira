"""Canonical internal manifests; never serialize before validating foreign DTOs."""

import json
from dataclasses import asdict
from hashlib import sha256

from ._models import POLICY, PROFILE


def digest(value):
    return sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def fragment_id(fragment, source_hash, *, profile=PROFILE):
    value = asdict(fragment)
    return "lf-" + digest(
        {
            "domain": "docx-final-fragment/1",
            "profile": profile,
            "policy_version": POLICY,
            "source_sha256": source_hash,
            **{k: value[k] for k in ("story_anchor", "flow_anchor", "paragraph_anchors", "joins")},
        }
    )


def manifest_digest(snapshot):
    value = asdict(snapshot)
    value.pop("snapshot_sha256")
    value["document_id"] = str(snapshot.document_id)
    value["storage_revision"] = str(snapshot.storage_revision)
    return digest(value)


def coverage_key(item):
    return (
        item.part_name,
        0 if item.anchor is None else 1,
        () if item.anchor is None else item.anchor.path,
        item.code,
        item.fragment_id or "",
    )
