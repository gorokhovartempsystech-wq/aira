"""Freshly restored Word sources need one rebuild, retaining every boundary check."""

from dataclasses import replace
from uuid import uuid4

import pytest
from test_docx_word_integration import bundle

from ara.docx_analysis import storage_codec as codec
from ara.docx_analysis.storage_codec import _records
from ara.docx_analysis.visible_word import _api


@pytest.mark.parametrize("operation", ["restore", "attempt"])
def test_single_source_rebuild_for_each_restoration(monkeypatch, operation):
    source, _, _ = bundle()
    original = _api.build_word_snapshot
    calls = []

    def build(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(_api, "build_word_snapshot", build)
    monkeypatch.setattr(_records, "build_word_snapshot", build)
    if operation == "restore":
        codec.restore_source(source)
    else:
        codec.prepare_attempt(source, attempt_id=uuid4())
    assert len(calls) == 1


def test_restore_keeps_source_manifest_and_character_budgets():
    source, _, _ = bundle()
    with pytest.raises(codec.StorageCodecError):
        codec.restore_source(replace(source, snapshot_sha256="0" * 64))
    with pytest.raises(codec.StorageCodecError):
        codec.restore_source(source, limits=codec.CodecLimits(max_text_characters=1))
    with pytest.raises(codec.StorageCodecError):
        codec.prepare_attempt(
            source, attempt_id=uuid4(), limits=codec.CodecLimits(max_source_bytes=1)
        )
