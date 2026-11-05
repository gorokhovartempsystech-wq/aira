"""A review may reuse proof locally, never across trust/lifetime boundaries."""

from dataclasses import replace
from importlib import import_module

import pytest
from test_docx_word_integration import bundle

from ara.docx_analysis import storage_codec as codec
from ara.docx_analysis.storage_codec import _records


def scope(records):
    return import_module("ara.docx_analysis.storage_codec._verification").verification_scope(
        records
    )


def test_exact_records_verified_once_and_scope_exit_revalidates(monkeypatch):
    records = bundle()
    calls = []
    original = _records.capture_result

    def capture(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(_records, "capture_result", capture)
    with scope((records,)):
        first = codec.restore_result(*records)
        assert codec.restore_result(*records) == first
        assert len(calls) == 1
        codec.restore_result(*records, limits=codec.CodecLimits())
        assert len(calls) == 2
        altered = (*records[:2], replace(records[2], findings_count=999))
        with pytest.raises(codec.StorageCodecError):
            codec.restore_result(*altered)
        with scope((records,)):
            codec.restore_result(*records)
        assert len(calls) == 4
    codec.restore_result(*records)
    assert len(calls) == 5


def test_failure_and_exception_exit_do_not_retain_proof(monkeypatch):
    records = bundle()
    original = _records.capture_result
    calls = []

    def fail(*args, **kwargs):
        calls.append(1)
        raise codec.StorageCodecError("corrupt_record")

    monkeypatch.setattr(_records, "capture_result", fail)
    with pytest.raises(RuntimeError), scope((records,)):
        for _ in range(2):
            with pytest.raises(codec.StorageCodecError):
                codec.restore_result(*records)
        raise RuntimeError("synthetic")
    assert len(calls) == 2
    monkeypatch.setattr(_records, "capture_result", original)
    assert codec.restore_result(*records).wire_json == records[2].result_data


def test_copied_context_thread_and_expired_scope_cannot_reuse(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context

    records = bundle()
    calls = []
    original = _records.capture_result

    def capture(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(_records, "capture_result", capture)
    with scope((records,)):
        codec.restore_result(*records)
        copied = copy_context()
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(copied.run, codec.restore_result, *records).result()
        assert len(calls) == 2
    copied.run(codec.restore_result, *records)
    copied.run(codec.restore_result, *records)
    assert len(calls) == 4


def test_source_corruption_and_stricter_limits_never_use_default_proof():
    records = bundle()
    with scope((records,)):
        codec.restore_result(*records)
        with pytest.raises(codec.StorageCodecError):
            codec.restore_result(*records, limits=codec.CodecLimits(max_source_bytes=1))
        corrupt = replace(records[0], source_data=records[0].source_data + b"broken")
        with pytest.raises(codec.StorageCodecError):
            codec.restore_result(corrupt, *records[1:])
