"""Build and read protected model bundles; plaintext weights are never staged."""

import hashlib
import json
import os
import tempfile
from pathlib import Path, PurePosixPath

from . import MAX_MODEL_BYTES, ModelProtectionError, open_model, seal_model
from .access_wire import decode, hex_text, label, require, shape


def _path(root, name):
    require(type(name) is str and name.isascii() and "\\" not in name)
    relative = PurePosixPath(name)
    require(not relative.is_absolute() and relative.as_posix() == name)
    require(all(p not in {"", ".", ".."} for p in relative.parts))
    result = root.joinpath(*relative.parts)
    require(result.resolve().is_relative_to(root.resolve()) and not result.is_symlink())
    return result


def _read(path, record):
    shape(record, "bytes sha256")
    size = record["bytes"]
    require(type(size) is int and 0 < size <= MAX_MODEL_BYTES + 2048)
    hex_text(record["sha256"])
    require(path.is_file() and path.stat().st_size == size)
    with path.open("rb") as stream:
        data = stream.read(size + 1)
    require(len(data) == size and hashlib.sha256(data).hexdigest() == record["sha256"])
    return data


def configuration(root):
    root = Path(root)
    path = root / "manifest.json"
    if not path.exists():
        return None
    require(path.stat().st_size <= 8192)
    raw = path.read_bytes()
    manifest = decode(raw)
    protection = manifest.get("protection")
    if protection is None:
        return None
    shape(protection, "format release_id models")
    require(protection["format"] == "aira-model/1")
    label(protection["release_id"])
    label(manifest["version"])
    files, models = manifest["files"], protection["models"]
    require(type(files) is dict and type(models) is dict and 1 <= len(models) <= 16)
    require(len(set(models.values())) == len(models))
    for name, relative in models.items():
        label(name)
        require(relative == name + "/model.int8.onnx.aira" and relative in files)
    require(
        not any(name.endswith((".onnx", ".ort", ".bin", ".data", ".safetensors")) for name in files)
    )
    return protection["release_id"], hashlib.sha256(raw).hexdigest()


def pack(source, output, key, *, release_id):
    """A new destination only; copies just verified, declared tokenizer assets."""
    source, output = Path(source), Path(output)
    label(release_id)
    require(type(key) is bytes and len(key) == 32)
    require((source / "manifest.json").stat().st_size <= 8192)
    manifest = decode((source / "manifest.json").read_bytes())
    require("protection" not in manifest and type(manifest["files"]) is dict)
    require(not output.exists() and not output.is_symlink())
    files, models = {}, {}
    with tempfile.TemporaryDirectory(prefix="aira-protected-", dir=output.parent) as temp:
        staging = Path(temp) / "models"
        staging.mkdir(mode=0o755)
        for name, record in manifest["files"].items():
            data = _read(_path(source, name), record)
            relative = name
            if name.endswith(".onnx"):
                model_id = PurePosixPath(name).parent.name
                label(model_id)
                require(name == model_id + "/model.int8.onnx")
                data = seal_model(data, key, model_id=model_id, version=manifest["version"])
                relative = name + ".aira"
                models[model_id] = relative
            else:
                require(PurePosixPath(name).suffix in {".json", ".txt"})
            target = _path(staging, relative)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
            target.write_bytes(data)
            target.chmod(0o644)
            files[relative] = dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        require(bool(models))
        manifest["files"] = files
        manifest["protection"] = dict(format="aira-model/1", release_id=release_id, models=models)
        (staging / "manifest.json").write_text(
            json.dumps(manifest, sort_keys=True, indent=2) + "\n"
        )
        configuration(staging)
        os.rename(staging, output)
    return configuration(output)


class ModelReader:
    def __init__(self, root, key):
        self.root = Path(root)
        require(configuration(self.root) is not None)
        require(type(key) is bytes and len(key) == 32)
        self._key = key
        self.manifest = decode((self.root / "manifest.json").read_bytes())

    def __call__(self, original):
        original = Path(original)
        identity = original.parent.name
        require(
            original.name == "model.int8.onnx"
            and original.parent.parent.resolve() == self.root.resolve()
        )
        relative = self.manifest["protection"]["models"].get(identity)
        require(relative is not None)
        data = _read(_path(self.root, relative), self.manifest["files"][relative])
        try:
            return open_model(data, self._key, model_id=identity, version=self.manifest["version"])
        except ModelProtectionError:
            raise ModelProtectionError() from None
