"""Portable regression for a dead server, startup deadline and recovery code."""
import importlib.util
import sys
import unittest
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend/src'))
sys.path.insert(0, str(ROOT / 'app/frontend'))
path = ROOT / 'app/frontend/packaging/windows/aira_startup.py'
spec = importlib.util.spec_from_file_location('aira_startup', path)
startup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(startup)


class Startup(unittest.TestCase):
    def test_close_never_destroys_webview_before_js_evaluation_returns(self):
        entered, release, destroyed, closed = (threading.Event() for _ in range(4))
        answers, errors = [], []
        def evaluate(script, callback):
            callback(True)
            entered.set()
            release.wait(2)
        thread = startup.request_window_close(SimpleNamespace(evaluate_js=evaluate, destroy=destroyed.set),
                                              closed, answers.append, errors.append)
        try:
            self.assertTrue(entered.wait(1))
            self.assertFalse(destroyed.is_set())
        finally:
            release.set()
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertTrue(destroyed.is_set())
        self.assertEqual(answers, [True])
        self.assertEqual(errors, [])

    def test_save_refusal_and_non_boolean_answers_never_destroy_window(self):
        for value in [False, None, {}, 'truthy']:
            with self.subTest(value=value):
                destroyed, answers, errors = [], [], []
                window = SimpleNamespace(evaluate_js=lambda script, callback: callback(value),
                                         destroy=lambda: destroyed.append(True))
                thread = startup.request_window_close(window, threading.Event(), answers.append, errors.append)
                thread.join(2)
                self.assertFalse(thread.is_alive())
                self.assertEqual((destroyed, answers, errors), ([], [False], []))

    def test_pending_save_keeps_window_alive_until_async_approval(self):
        entered, closed = threading.Event(), threading.Event()
        callbacks, destroyed, answers, errors = [], [], [], []
        def evaluate(script, callback):
            callbacks.append(callback)
            entered.set()
        thread = startup.request_window_close(SimpleNamespace(evaluate_js=evaluate, destroy=lambda: destroyed.append(True)),
                                              closed, answers.append, errors.append)
        try:
            self.assertTrue(entered.wait(1))
            self.assertEqual(destroyed, [])
            callbacks[0](True)
            thread.join(2)
        finally:
            closed.set()
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual((destroyed, answers, errors), ([True], [True], []))

    def test_closed_window_releases_pending_close_request(self):
        entered, closed = threading.Event(), threading.Event()
        def evaluate(script, callback): entered.set()
        unexpected = []
        thread = startup.request_window_close(SimpleNamespace(evaluate_js=evaluate, destroy=lambda: unexpected.append(True)),
                                              closed, unexpected.append, unexpected.append)
        self.assertTrue(entered.wait(1))
        closed.set()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(unexpected, [])

    def test_failed_evaluation_keeps_window_open(self):
        errors, unexpected = [], []
        def evaluate(script, callback): raise RuntimeError('synthetic dispatch failed')
        thread = startup.request_window_close(SimpleNamespace(evaluate_js=evaluate, destroy=lambda: unexpected.append(True)),
                                              threading.Event(), unexpected.append, errors.append)
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(unexpected, [])
        self.assertEqual(len(errors), 1)

    def test_native_close_failure_is_reported(self):
        errors, answers = [], []
        def destroy(): raise RuntimeError('synthetic close failed')
        thread = startup.request_window_close(SimpleNamespace(evaluate_js=lambda script, callback: callback(True), destroy=destroy),
                                              threading.Event(), answers.append, errors.append)
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(answers, [True])
        self.assertEqual(len(errors), 1)

    def test_launcher_database_url_is_accepted_by_strict_supervisor(self):
        from ara.config import DatabaseSettings
        from ara.docx_analysis_worker.supervisor.database import create_engines
        engines = create_engines(DatabaseSettings(startup.database_url(47432)))
        try:
            self.assertEqual(dict(engines.control.url.query), {'connect_timeout':'5'})
            self.assertEqual(engines.control.url.host, '127.0.0.1')
            self.assertEqual(engines.control.url.port, 47432)
        finally:
            engines.dispose()

    def test_real_uvicorn_lifespan_failure_retains_recovery_reason(self):
        import uvicorn
        from fastapi import FastAPI
        import aira_host
        from ara.config import DatabaseSettings
        captured = []
        supervisor = SimpleNamespace(start=lambda: None,
            view=lambda: SimpleNamespace(phase='recovery_required', error_code='recovery_required'),
            shutdown=lambda **kwargs: True, _user_id=aira_host.USER, _project_id=aira_host.PROJECT,
            _settings=DatabaseSettings('postgresql+psycopg://synthetic@127.0.0.1/synthetic'))
        with tempfile.TemporaryDirectory() as directory, patch('ara.docx_analysis_worker.supervisor.local_model.create_local_model_supervisor', return_value=supervisor), patch('ara.app.create_app', side_effect=lambda **kwargs: FastAPI()):
            app = aira_host.build_app(database_url='postgresql+psycopg://synthetic@127.0.0.1/synthetic',
                runtime_root=Path(directory)/'analysis', port=49233, initialize=False,
                on_startup_error=lambda error: captured.append(startup.startup_error(error)))
            server = uvicorn.Server(uvicorn.Config(app,log_config=None,access_log=False))
            def serve():
                try: server.run()
                except BaseException as error:
                    if not captured: captured.append(startup.startup_error(error))
            thread = threading.Thread(target=serve); thread.start(); thread.join(5)
            self.assertFalse(thread.is_alive())
            with self.assertRaises(startup.StartupError) as caught:
                startup.wait_started(server, thread, lambda: captured[0], lambda *args: None)
            self.assertEqual(caught.exception.code,'recovery_required')

    def test_system_exit_becomes_visible_error_not_silent_boot_thread_exit(self):
        server = SimpleNamespace(started=False, should_exit=False)
        dead = SimpleNamespace(is_alive=lambda: False)
        with self.assertRaises(startup.StartupError) as caught:
            startup.wait_started(server, dead, lambda: SystemExit(3), lambda *args: None)
        self.assertEqual(caught.exception.code, 'startup_failed')

    def test_recovery_error_survives_uvicorn_system_exit(self):
        error = RuntimeError('synthetic')
        error.code = 'recovery_required'
        original = startup.startup_error(error)
        self.assertEqual(original.code, 'recovery_required')
        self.assertIs(startup.startup_error(original), original)

    def test_live_server_that_never_starts_has_bounded_wait(self):
        now = [0.0]
        server = SimpleNamespace(started=False, should_exit=False)
        def sleep(seconds): now[0] += seconds
        with self.assertRaises(startup.StartupError) as caught:
            startup.wait_started(server, SimpleNamespace(is_alive=lambda: True), lambda: None,
                                 lambda *args: None, clock=lambda: now[0], sleep=sleep, timeout=1)
        self.assertEqual(caught.exception.code, 'startup_timeout')
        self.assertTrue(server.should_exit)
        self.assertLess(now[0], 1.2)

    def test_slow_package_progress_times_out_without_claiming_model_loaded(self):
        now = [0.0]; messages = []
        report = startup.Progress(messages.append, clock=lambda: now[0])
        report('model_package')
        self.assertIn('целостность', messages[-1])
        now[0] = 120
        with self.assertRaises(startup.StartupError): report()

    def test_finished_server_does_not_wait(self):
        startup.wait_started(SimpleNamespace(started=True), None, lambda: None, lambda *a: None,
                             sleep=lambda _: self.fail('Ready server must not wait'))

    def test_deadline_already_expired_when_server_thread_starts_requests_stop(self):
        server = SimpleNamespace(started=False, should_exit=False)
        def expired(*args):
            raise startup.StartupError('synthetic deadline', 'startup_timeout')
        with self.assertRaises(startup.StartupError):
            startup.wait_started(server, None, lambda: None, expired)
        self.assertTrue(server.should_exit)


if __name__ == '__main__': unittest.main()
