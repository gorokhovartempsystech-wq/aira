"""Startup progress must retain complete model verification and identical identity."""

import hashlib
import json

import pytest

from ara.docx_analysis_worker.local_model import package_identity


def test_checkpoint_does_not_change_identity_or_accept_tampering(tmp_path):
    models, engine = tmp_path / "models", tmp_path / "engine"
    models.mkdir()
    (engine / "aira_ml").mkdir(parents=True)
    content = b"synthetic-model" * 100000
    model = models / "model.bin"
    model.write_bytes(content)
    (models / "manifest.json").write_text(
        json.dumps(
            {
                "version": "1.0.0",
                "files": {
                    "model.bin": {
                        "bytes": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                    }
                },
            }
        )
    )
    for name in ("engine.py", "lint.py"):
        (engine / "aira_ml" / name).write_text("# synthetic\n")
    calls = []
    normal = package_identity(models, engine)
    assert package_identity(models, engine, checkpoint=lambda: calls.append(1)) == normal
    assert len(calls) >= 3
    model.write_bytes(b"x" + content[1:])
    with pytest.raises(ValueError):
        package_identity(models, engine, checkpoint=lambda: None)


def test_checkpoint_abort_propagates_before_hashing_files(tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    (models / "manifest.json").write_text(
        json.dumps({"version": "1.0.0", "files": {"missing": {}}})
    )

    def abort():
        raise TimeoutError("synthetic startup deadline")

    with pytest.raises(TimeoutError):
        package_identity(models, tmp_path, checkpoint=abort)
