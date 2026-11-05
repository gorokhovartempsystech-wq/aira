"""Prepare a local native-worker bundle from already obtained model files.

No downloads, system installs, database changes, or replacement of an existing bundle.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


RUNTIME_FILES = ('__init__.py', 'engine.py', 'lint.py', 'stable_nli.py')


def prepare(models, destination, *, engine_source=None):
    models = Path(models).resolve()
    destination = Path(destination).resolve()
    engine_source = Path(engine_source or Path(__file__).resolve().parents[1] / 'engine/aira_ml')
    manifest = json.loads((models / 'manifest.json').read_text(encoding='utf-8'))
    if not isinstance(manifest.get('files'), dict) or not manifest['files']:
        raise ValueError('Model manifest must list files')
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Choose an empty destination; existing bundles are never replaced')
    checked = []
    for name, entry in manifest['files'].items():
        path = (models / name).resolve()
        if not path.is_relative_to(models) or not path.is_file():
            raise ValueError('Invalid model path')
        if path.stat().st_size != entry['bytes']:
            raise ValueError('Model size mismatch')
        with path.open('rb') as handle:
            actual = hashlib.file_digest(handle, 'sha256').hexdigest()
        if actual != entry['sha256']:
            raise ValueError('Model checksum mismatch')
        checked.append((name, path))
    for name in RUNTIME_FILES:
        if not (engine_source / name).is_file():
            raise ValueError('Required engine runtime file missing: ' + name)
    for name in RUNTIME_FILES:
        target = destination / 'aira_ml' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(engine_source / name, target)
    for name, source in checked:
        target = destination / 'models' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    shutil.copyfile(models / 'manifest.json', destination / 'models/manifest.json')
    return {'models': manifest['version'], 'checked_model_files': len(checked),
            'nli_policy': 'isolated-direction-no-padding', 'runtime_files': list(RUNTIME_FILES)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.models, args.destination), ensure_ascii=False))


if __name__ == '__main__':
    main()
