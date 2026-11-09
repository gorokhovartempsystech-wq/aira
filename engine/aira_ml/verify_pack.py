"""Validate an already-downloaded local pack before starting inference."""
import argparse
import hashlib
import json
from pathlib import Path


def verify(directory):
    root = Path(directory).resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    required = {f"{model}/{name}" for model in ("embedder", "pair", "nli")
                for name in ("model.int8.onnx", "tokenizer.json")}
    if not required.issubset(manifest["files"]):
        raise ValueError("Manifest omits required model files")
    for name, expected in manifest["files"].items():
        target = (root / name).resolve()
        if not target.is_relative_to(root) or Path(name).is_absolute():
            raise ValueError("Manifest path escapes model directory")
        if target.stat().st_size != expected["bytes"]:
            raise ValueError(f"Incorrect size: {name}")
        with target.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != expected["sha256"]:
            raise ValueError(f"Incorrect SHA256: {name}")
    return manifest["version"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    args = parser.parse_args()
    print(f"Verified model pack: {verify(args.directory)}")
