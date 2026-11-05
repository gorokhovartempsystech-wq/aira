"""Importing draft storage must not perform configuration or external I/O."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_draft_imports_are_inert():
    code = """
import builtins, importlib, io, socket, subprocess
from pathlib import Path
import psycopg, sqlalchemy
import ara.config, ara.db, ara.models
names = ['ara.drafts'] + [
    '.'.join(p.with_suffix('').parts[1:])
    for p in sorted(Path('src/ara/drafts').rglob('*.py')) if p.name != '__init__.py'
]
def forbidden(*args, **kwargs):
    raise AssertionError('Unexpected external I/O during draft import')
for target, name in (
    (builtins, 'open'), (io, 'open'), (Path, 'open'), (Path, 'read_text'),
    (socket, 'socket'), (socket, 'create_connection'),
    (subprocess, 'Popen'), (subprocess, 'run'),
    (psycopg, 'connect'), (sqlalchemy, 'create_engine'),
    (ara.config, 'load_settings'), (ara.db, 'create_database_engine'),
):
    setattr(target, name, forbidden)
for name in names:
    importlib.import_module(name)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
