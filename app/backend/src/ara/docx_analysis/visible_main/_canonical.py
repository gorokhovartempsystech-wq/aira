"""Streaming canonical JSON over trusted, schema-validated records only."""

import json
from dataclasses import fields, is_dataclass
from hashlib import sha256
from uuid import UUID

from ._models import POLICY, PROFILE, budget


def tokens(value, *, omit_hash=False):
    if is_dataclass(value):
        yield "{"
        names = sorted(
            f.name for f in fields(value) if not (omit_hash and f.name == "snapshot_sha256")
        )
        for i, name in enumerate(names):
            if i:
                yield ","
            yield json.dumps(name)
            yield ":"
            child = getattr(value, name)
            yield from tokens(str(child) if name == "storage_revision" else child)
        yield "}"
    elif type(value) is dict:
        yield "{"
        for i, name in enumerate(sorted(value)):
            if i:
                yield ","
            yield json.dumps(name)
            yield ":"
            yield from tokens(value[name])
        yield "}"
    elif type(value) is tuple:
        yield "["
        for i, child in enumerate(value):
            if i:
                yield ","
            yield from tokens(child)
        yield "]"
    else:
        yield json.dumps(
            str(value) if type(value) is UUID else value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )


def digest(value, maximum, *, omit_hash=False):
    size = 0
    hasher = sha256()
    for token in tokens(value, omit_hash=omit_hash):
        raw = token.encode("utf-8")
        size += len(raw)
        budget(size, maximum)
        hasher.update(raw)
    return hasher.hexdigest()


def fragment_id(body, paragraph, source_sha256, maximum, *, profile=PROFILE, flow=None):
    return "vf-" + digest(
        dict(
            domain="docx-visible-fragment/1",
            profile=profile,
            policy_version=POLICY,
            source_sha256=source_sha256,
            story_anchor=body,
            flow_anchor=body if flow is None else flow,
            paragraph_anchor=paragraph,
        ),
        maximum,
    )


def coverage_key(c):
    return (
        c.part_name,
        0 if c.anchor is None else 1,
        () if c.anchor is None else c.anchor.path,
        c.code,
        c.fragment_id or "",
    )
