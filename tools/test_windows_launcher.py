"""Regression for Windows registry MIME associations blocking WebView modules."""
import importlib.machinery
import importlib.util
import mimetypes
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles
from starlette.testclient import TestClient

PATH = Path(__file__).resolve().parents[1] / 'app/frontend/packaging/windows/aira_launcher.pyw'
loader = importlib.machinery.SourceFileLoader('aira_windows_launcher', str(PATH))
spec = importlib.util.spec_from_loader(loader.name, loader)
launcher = importlib.util.module_from_spec(spec)
loader.exec_module(launcher)


class StaticScripts(unittest.TestCase):
    def test_registry_text_plain_is_overridden_for_both_script_extensions(self):
        mimetypes.init()
        with patch.dict(mimetypes.types_map, {'.mjs': 'text/plain', '.js': 'text/plain'}), patch('mimetypes.init'):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for name in ('main.mjs', 'host.mjs', 'legacy.js'):
                    (root / name).write_text('export const loaded = true;', encoding='utf-8')
                app = Starlette(routes=[Mount('/assets', StaticFiles(directory=root))])
                with TestClient(app) as client:
                    self.assertTrue(client.get('/assets/main.mjs').headers['content-type'].startswith('text/plain'))
                    launcher.configure_static_types()
                    for name in ('main.mjs', 'host.mjs', 'legacy.js'):
                        response = client.get('/assets/' + name)
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.headers['content-type'].split(';')[0], 'text/javascript')
                        self.assertEqual(response.text, 'export const loaded = true;')


if __name__ == '__main__':
    unittest.main()
