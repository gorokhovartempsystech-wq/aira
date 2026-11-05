"""B2B restart, early bounds, DTO mutation and stable work per result batch."""

import base64
import json
import subprocess
import sys
from dataclasses import fields, replace
from hashlib import sha256
from uuid import UUID

import pytest

from tests.acceptance.test_docx_analysis_storage_codec import (
    api,
    command,
    execution,
    reject,
    result_bundle,
    source_bundle,
)
from tests.acceptance.test_docx_review_v1 import canonical, issue, reply
from tests.acceptance.test_docx_visible_main import build, source


def test_full_restoration_in_fresh_process_has_no_application_io_or_inference():
    from tests.acceptance.conftest import ROOT

    src, a, r = result_bundle()

    def wire(obj):
        return {
            f.name: (
                {"bytes": base64.b64encode(v).decode()}
                if type(v) is bytes
                else {"uuid": str(v)}
                if type(v) is UUID
                else v
            )
            for f in fields(obj)
            for v in [getattr(obj, f.name)]
        }

    program = """
import base64,json,sys
def audit(event,args):
    if event in ('socket.connect','subprocess.Popen','os.system'):
        raise AssertionError('Unexpected application I/O')
    if event=='open' and isinstance(args[0],str) and not args[0].endswith(('.py','.pyc')):
        raise AssertionError('Unexpected file access')
    if event=='import' and args[0].split('.')[0] in ('onnxruntime','aira_ml','torch','tokenizers'):
        raise AssertionError('Unexpected model import')
sys.addaudithook(audit)
from uuid import UUID
from ara.docx_analysis.storage_codec import SourceBundle,AttemptBundle,ResultBundle,restore_result
p=json.load(sys.stdin)
def record(cls,body):
    return cls(**{k:(base64.b64decode(v['bytes']) if 'bytes' in v else UUID(v['uuid']))
                  if type(v) is dict else v for k,v in body.items()})
result=restore_result(record(SourceBundle,p[0]),record(AttemptBundle,p[1]),record(ResultBundle,p[2]))
print(json.dumps([result.result_sha256,result.findings_count,result.questions_count]))
"""
    completed = subprocess.run(
        [sys.executable, "-c", program],
        cwd=ROOT / "src",
        input=json.dumps([wire(src), wire(a), wire(r)]),
        text=True,
        capture_output=True,
        timeout=20,
        check=True,
    )
    assert json.loads(completed.stdout) == [r.result_sha256, 1, 1]
    assert not completed.stderr


def test_untrusted_field_hooks_are_never_invoked():
    class Bomb:
        def __eq__(self, other):
            raise AssertionError("hook")

        def __len__(self):
            raise AssertionError("hook")

        def __repr__(self):
            raise AssertionError("hook")

    src = source_bundle()
    for key in ("document_id", "source_data", "profile", "execution_kind", "storage_revision"):
        reject("corrupt_record", lambda: api().restore_source(replace(src, **{key: Bomb()})))
    limits = api().CodecLimits()
    object.__setattr__(limits, "review", Bomb())
    reject("invalid_input", lambda: api().restore_source(src, limits=limits))


def test_unknown_and_malformed_profiles_are_distinct():
    src = source_bundle()
    reject("corrupt_record", lambda: api().restore_source(replace(src, profile="bad\x00profile")))
    reject(
        "unsupported_version", lambda: api().restore_source(replace(src, policy_version="other/v1"))
    )


@pytest.mark.parametrize("count", [512, 513])
def test_initial_server_fragment_admission_is_not_generic_b1_capacity(count):
    raw, _ = source("<w:p><w:r><w:t>Short</w:t></w:r></w:p>" * count)
    s = build(raw)

    def call():
        return api().capture_source(raw, s, command=command(s), execution=execution())

    if count == 512:
        assert api().restore_source(call()).snapshot == s
    else:
        reject("codec_limit_exceeded", call)


def test_reduced_manifest_source_text_and_execution_caps():
    src = source_bundle()
    restored = api().restore_source(src)
    n = sum(len(f.text) for f in restored.snapshot.fragments)
    api().restore_source(
        src,
        limits=api().CodecLimits(
            max_text_characters=n,
            max_source_bytes=len(src.source_data),
            max_manifest_bytes=len(src.snapshot_data),
            max_execution_bytes=len(src.execution_spec),
        ),
    )
    for key, size in (
        ("max_text_characters", n),
        ("max_source_bytes", len(src.source_data)),
        ("max_manifest_bytes", len(src.snapshot_data)),
        ("max_execution_bytes", len(src.execution_spec)),
    ):
        reject(
            "codec_limit_exceeded",
            lambda: api().restore_source(src, limits=api().CodecLimits(**{key: size - 1})),
        )


def test_model_spec_and_request_substitution_are_checked_even_with_new_hashes():
    src, a, r = result_bundle()
    body = json.loads(src.execution_spec)
    body["models_version"] = "different"
    data = canonical(body)
    altered = replace(src, execution_spec=data, execution_spec_sha256=sha256(data).hexdigest())
    reject("corrupt_record", lambda: api().restore_result(altered, a, r))
    body = json.loads(a.request_data)
    body["engine_request"]["fragments"][0]["text"] = "xxxx"
    data = canonical(body)
    reject(
        "corrupt_record",
        lambda: api().restore_result(
            src, replace(a, request_data=data, request_sha256=sha256(data).hexdigest()), r
        ),
    )


def test_bad_reply_and_oversize_record_fail_before_source_rebuild(monkeypatch):
    from ara.docx_analysis.storage_codec import _records

    src, a, r = result_bundle()

    def forbidden(*args, **kwargs):
        raise AssertionError("reader must not run")

    monkeypatch.setattr(_records, "build_visible_snapshot", forbidden)
    raw = b"{}"
    reject(
        "codec_limit_exceeded",
        lambda: api().restore_result(
            src,
            a,
            replace(r, result_data=b"x" * (len(a.request_data) + 1)),
            limits=api().CodecLimits(
                review=replace(api().CodecLimits().review, max_wire_bytes=len(a.request_data))
            ),
        ),
    )
    reject(
        "corrupt_record",
        lambda: api().restore_result(src, a, replace(r, reply_data=raw, reply_sha256="b" * 64)),
    )


def test_restore_batch_has_fixed_number_of_catalog_reads(monkeypatch):
    from ara.docx_analysis.visible_main import _build

    src = source_bundle()
    attempt = api().prepare_attempt(src, attempt_id=UUID(int=1))
    snapshot = api().restore_source(src).snapshot
    items = [
        issue(snapshot, id=f"iss-{i:010x}", explanation=f"Synthetic issue {i}") for i in range(100)
    ]
    result = api().capture_result(src, attempt, reply=canonical(reply(snapshot, items)))
    original = _build.read_style_context
    calls = []

    def spy(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(_build, "read_style_context", spy)
    assert api().restore_result(src, attempt, result).findings_count == 100
    assert len(calls) <= 4
    reject(
        "codec_limit_exceeded",
        lambda: api().restore_result(
            src,
            attempt,
            result,
            limits=api().CodecLimits(review=replace(api().CodecLimits().review, max_issues=99)),
        ),
    )
