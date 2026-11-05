"""Runner safety checks; no real Codex calls, credentials or network access."""

import importlib.util
import io
import json
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

# Resolve the owned runner without importing any application code.
SPEC = importlib.util.spec_from_file_location(
    "ara_ralph", Path(__file__).parents[2] / "scripts" / "ralph.py"
)
assert SPEC and SPEC.loader
ralph = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ralph
SPEC.loader.exec_module(ralph)


class TaskRunnerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        (self.root / "ralph").mkdir()
        self.common_prompt = "Project rule: preserve the original archive."
        (self.root / ralph.PROMPT_FILE).write_text(self.common_prompt, encoding="utf-8")
        (self.root / "src" / "ara").mkdir(parents=True)
        self.task = {
            "id": "T01-01",
            "title": "Task",
            "prompt": "Implement the endpoint.",
            "acceptance_criteria": ["Endpoint returns HTTP 200", "Input is validated"],
            "check_command": ["bash", "scripts/check.sh"],
            "status": "pending",
            "depends_on": [],
            "allowed_paths": ["src/ara/**", "tests/app/**"],
        }
        self.other = {**self.task, "id": "T01-02", "title": "Other task", "status": "pending"}
        self.write_tasks()
        self.complete_result = {
            "status": "complete",
            "summary": "Done",
            "completed_criteria": [1, 2],
            "blockers": [],
        }
        self.agent_calls = []
        self.check_calls = []

    def write_tasks(self):
        (self.root / ralph.TASK_FILE).write_text(
            json.dumps({"version": 1, "metadata": "preserve me", "tasks": [self.task, self.other]}),
            encoding="utf-8",
        )

    def status(self):
        return ralph.read_tasks(self.root)["tasks"][0]["status"]

    def fake_snapshot(self, root):
        return {
            str(p.relative_to(root)): p.read_bytes().hex()
            for p in root.rglob("*")
            if p.is_file() and ".ralph" not in p.parts
        }

    def fake_process(
        self,
        *,
        agent=None,
        check_exit=0,
        write_change=False,
        agent_exit=0,
        timed_out=False,
        error="",
        agent_stdout="",
        wrong_scope=False,
    ):
        result = self.complete_result if agent is None else agent

        def execute(argv, root, stdout_path, stderr_path, timeout, stdin_text=None):
            stdout_path.write_text("", encoding="utf-8")
            stderr_path.write_text(error, encoding="utf-8")
            if argv[0] == "codex":
                stdout_path.write_text(agent_stdout, encoding="utf-8")
                self.agent_calls.append((argv, stdin_text, timeout))
                path = Path(argv[argv.index("--output-last-message") + 1])
                path.write_text(json.dumps(result), encoding="utf-8")
                if write_change:
                    target = root / "src/ara/app.py"
                    target.write_text(str(len(self.agent_calls)), encoding="utf-8")
                if wrong_scope:
                    (root / "scripts").mkdir(exist_ok=True)
                    (root / "scripts/check.sh").write_text("exit 0\n", encoding="utf-8")
                return ralph.ProcessResult(agent_exit, timed_out)
            self.check_calls.append(argv)
            return ralph.ProcessResult(check_exit)

        return execute

    def run_task(self, fake, iterations=3):
        with (
            mock.patch.object(ralph, "run_process", side_effect=fake),
            mock.patch.object(ralph, "snapshot", side_effect=self.fake_snapshot),
            redirect_stdout(io.StringIO()) as output,
        ):
            code = ralph.run_task(self.root, "T01-01", iterations, 600)
        self.console = output.getvalue()
        return code

    def test_passed_checks_and_complete_result_finish_selected_task(self):
        self.assertEqual(self.run_task(self.fake_process(write_change=True)), 0)
        data = ralph.read_tasks(self.root)
        self.assertEqual(data["tasks"][0]["status"], "completed")
        self.assertEqual(data["tasks"][1], self.other)
        self.assertEqual(data["metadata"], "preserve me")
        entries = [
            json.loads(line) for line in (self.root / ralph.PROGRESS_FILE).read_text().splitlines()
        ]
        self.assertTrue(all(entry["task_id"] == "T01-01" for entry in entries))
        self.assertEqual(entries[-1]["reason"], "criteria_and_checks_passed")
        self.assertEqual(len(self.agent_calls), 1)

    def test_failed_checks_cannot_complete_even_with_agent_claim(self):
        self.assertEqual(self.run_task(self.fake_process(check_exit=7, write_change=True)), 7)
        self.assertEqual(self.status(), "blocked")
        self.assertEqual(len(self.agent_calls), 3)
        self.assertIn("iteration_limit", self.console)

    def test_passed_checks_without_complete_result_are_not_completion(self):
        result = {**self.complete_result, "status": "continue"}
        self.assertEqual(self.run_task(self.fake_process(agent=result)), 2)
        self.assertEqual(self.status(), "blocked")
        self.assertEqual(len(self.agent_calls), 2)
        self.assertIn("repeated_no_progress", self.console)

    def test_all_acceptance_criteria_are_required(self):
        result = {**self.complete_result, "completed_criteria": [1]}
        self.assertEqual(self.run_task(self.fake_process(agent=result), iterations=1), 2)
        self.assertEqual(self.status(), "blocked")

    def test_completion_with_blockers_cannot_complete(self):
        result = {**self.complete_result, "blockers": ["Missing dependency"]}
        self.assertEqual(self.run_task(self.fake_process(agent=result), iterations=1), 2)
        self.assertEqual(self.status(), "blocked")

    def test_agent_blocked_stops_without_running_checks(self):
        result = {**self.complete_result, "status": "blocked", "blockers": ["Permission needed"]}
        self.assertEqual(self.run_task(self.fake_process(agent=result)), 2)
        self.assertEqual(len(self.agent_calls), 1)
        self.assertEqual(self.check_calls, [])

    def test_agent_timeout_stops_without_retry_or_checks(self):
        self.assertEqual(self.run_task(self.fake_process(agent_exit=124, timed_out=True)), 124)
        self.assertEqual(self.status(), "blocked")
        self.assertEqual(len(self.agent_calls), 1)
        self.assertEqual(self.check_calls, [])

    def test_authentication_failure_preserves_exit_without_dumping_log(self):
        self.assertEqual(
            self.run_task(self.fake_process(agent_exit=42, error="401 unauthorized secret-value")),
            42,
        )
        self.assertIn("agent_authentication_failed", self.console)
        self.assertNotIn("secret-value", self.console)
        self.assertEqual(len(self.agent_calls), 1)
        self.assertEqual(self.check_calls, [])

    def test_quota_failure_never_retries_or_changes_auth(self):
        self.assertEqual(
            self.run_task(self.fake_process(agent_exit=1, error="429 quota exceeded")), 1
        )
        self.assertIn("agent_quota_or_rate_limit", self.console)
        self.assertEqual(len(self.agent_calls), 1)

    def test_permission_failure_is_classified(self):
        self.assertEqual(
            self.run_task(self.fake_process(agent_exit=1, error="permission denied")), 1
        )
        self.assertIn("agent_permission_denied", self.console)

    def test_protected_check_script_change_blocks_before_execution(self):
        self.assertEqual(self.run_task(self.fake_process(wrong_scope=True)), 2)
        self.assertEqual(self.check_calls, [])
        self.assertIn("changes_outside_task_scope", self.console)

    def test_invalid_result_cannot_complete(self):
        self.assertEqual(self.run_task(self.fake_process(agent={"status": ["complete"]})), 2)
        self.assertEqual(self.check_calls, [])
        self.assertIn("invalid_agent_result", self.console)

    def test_codex_argv_preserves_model_auth_and_uses_supported_auto_review_preset(self):
        self.run_task(self.fake_process(), iterations=1)
        argv, prompt, timeout = self.agent_calls[0]
        self.assertEqual(argv[:3], ["codex", "exec", "--approve-for-me"])
        self.assertEqual(argv[argv.index("-C") + 1], str(self.root))
        self.assertEqual(argv[-1], "-")
        self.assertIn("--output-schema", argv)
        self.assertNotIn("--model", argv)
        self.assertNotIn("--config", argv)
        self.assertEqual(argv.count("--approve-for-me"), 1)
        self.assertNotIn("--ask-for-approval", argv)
        self.assertNotIn("--sandbox", argv)
        self.assertNotIn("danger-full-access", argv)
        self.assertFalse(any("bypass" in a for a in argv))
        self.assertIn("Implement the endpoint.", prompt)
        self.assertIn(self.common_prompt, prompt)
        self.assertEqual(timeout, 600)

    def test_check_command_is_an_argv_array_not_reinterpreted(self):
        self.task["check_command"] = ["checker", "argument; $(touch unwanted)", "two words"]
        self.write_tasks()
        self.run_task(self.fake_process(), iterations=1)
        self.assertEqual(self.check_calls, [self.task["check_command"]])

    def test_dry_run_does_not_spawn_or_write(self):
        before = self.fake_snapshot(self.root)
        with (
            mock.patch.object(ralph, "run_process") as process,
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(ralph.run_task(self.root, "T01-01", 3, 600, dry_run=True), 0)
        process.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["approval_policy"], "on-request")
        self.assertEqual(json.loads(output.getvalue())["approvals_reviewer"], "auto_review")
        self.assertEqual(json.loads(output.getvalue())["sandbox"], "workspace-write")
        self.assertEqual(before, self.fake_snapshot(self.root))
        self.assertFalse((self.root / ".ralph").exists())

    def test_unknown_task_cannot_run(self):
        with self.assertRaisesRegex(ralph.RunnerError, "task_not_found"):
            ralph.run_task(self.root, "T99", 3, 600)
        self.assertFalse((self.root / ".ralph").exists())

    def test_managed_permission_rejection_stops_even_when_cli_exits_zero(self):
        error = "approval_policy value Never is not allowed by requirements; falling back"
        self.assertEqual(self.run_task(self.fake_process(error=error)), 2)
        self.assertEqual(len(self.agent_calls), 1)
        self.assertEqual(self.check_calls, [])
        self.assertEqual(self.status(), "blocked")
        self.assertIn("agent_managed_permission_rejected", self.console)

    def test_managed_reviewer_rejection_preserves_nonzero_exit_without_retry(self):
        error = "approvals_reviewer auto_review is not permitted by requirements"
        self.assertEqual(self.run_task(self.fake_process(agent_exit=17, error=error)), 17)
        self.assertEqual(len(self.agent_calls), 1)
        self.assertEqual(self.check_calls, [])
        self.assertIn("agent_managed_permission_rejected", self.console)

    def test_nested_cli_error_cannot_hide_managed_policy_rejection(self):
        event = {
            "type": "item.completed",
            "item": {
                "type": "error",
                "message": "approval_policy is disallowed by requirements; falling back",
            },
        }
        fake = self.fake_process(agent_stdout=json.dumps(event) + "\n")
        self.assertEqual(self.run_task(fake), 2)
        self.assertEqual(self.status(), "blocked")
        self.assertEqual(len(self.agent_calls), 1)
        self.assertEqual(self.check_calls, [])
        self.assertIn("agent_managed_permission_rejected", self.console)

    def test_duplicate_task_id_is_rejected(self):
        self.other["id"] = self.task["id"]
        self.write_tasks()
        with self.assertRaisesRegex(ralph.RunnerError, "duplicate_task_id"):
            ralph.read_tasks(self.root)

    def test_incomplete_prerequisite_prevents_task_start(self):
        self.task["depends_on"] = ["T01-02"]
        self.write_tasks()
        with self.assertRaisesRegex(ralph.RunnerError, "dependencies_not_completed"):
            ralph.run_task(self.root, "T01-01", 3, 600)

    def test_completed_task_never_runs_agent_again(self):
        self.task["status"] = "completed"
        self.write_tasks()
        with mock.patch.object(ralph, "run_process") as process, redirect_stdout(io.StringIO()):
            self.assertEqual(ralph.run_task(self.root, "T01-01", 3, 600), 0)
        process.assert_not_called()

    def test_iteration_and_timeout_bounds(self):
        for iterations, timeout in [(0, 600), (4, 600), (3, 0), (3, 3601)]:
            with self.subTest(iterations=iterations, timeout=timeout):
                with self.assertRaisesRegex(ralph.RunnerError, "invalid_run_bounds"):
                    ralph.run_task(self.root, "T01-01", iterations, timeout)

    def test_missing_ownership_cannot_grant_workspace_writes(self):
        self.task.pop("allowed_paths")
        self.write_tasks()
        for dry_run in (False, True):
            with self.subTest(dry_run=dry_run):
                with mock.patch.object(ralph, "run_process") as process:
                    with self.assertRaisesRegex(ralph.RunnerError, "invalid_allowed_paths"):
                        ralph.run_task(self.root, "T01-01", 3, 600, dry_run=dry_run)
                process.assert_not_called()
        self.assertFalse((self.root / ".ralph").exists())
        self.assertEqual(self.status(), "pending")

    def test_empty_ownership_fails_before_model_including_dry_run(self):
        for paths in ([], [""], ["   "]):
            for dry_run in (False, True):
                with self.subTest(paths=paths, dry_run=dry_run):
                    self.task["allowed_paths"] = paths
                    self.write_tasks()
                    with mock.patch.object(ralph, "run_process") as process:
                        with self.assertRaisesRegex(ralph.RunnerError, "invalid_allowed_paths"):
                            ralph.run_task(self.root, "T01-01", 3, 600, dry_run=dry_run)
                    process.assert_not_called()
        self.assertFalse((self.root / ".ralph").exists())
        self.assertEqual(self.status(), "pending")

    def test_missing_common_prompt_fails_before_model_and_writes(self):
        (self.root / ralph.PROMPT_FILE).unlink()
        for dry_run in (False, True):
            with self.subTest(dry_run=dry_run):
                with mock.patch.object(ralph, "run_process") as process:
                    with self.assertRaisesRegex(ralph.RunnerError, "common_prompt_missing"):
                        ralph.run_task(self.root, "T01-01", 3, 600, dry_run=dry_run)
                process.assert_not_called()
        self.assertFalse((self.root / ".ralph").exists())
        self.assertEqual(self.status(), "pending")

    def test_empty_common_prompt_fails_before_model_and_writes(self):
        for content in ("", " \n\t"):
            for dry_run in (False, True):
                with self.subTest(content=content, dry_run=dry_run):
                    (self.root / ralph.PROMPT_FILE).write_text(content, encoding="utf-8")
                    with mock.patch.object(ralph, "run_process") as process:
                        with self.assertRaisesRegex(ralph.RunnerError, "common_prompt_empty"):
                            ralph.run_task(self.root, "T01-01", 3, 600, dry_run=dry_run)
                    process.assert_not_called()
        self.assertFalse((self.root / ".ralph").exists())
        self.assertEqual(self.status(), "pending")

    def test_check_timeout_stops_immediately(self):
        agent = self.fake_process()

        def execute(argv, root, stdout_path, stderr_path, timeout, stdin_text=None):
            if argv[0] == "codex":
                return agent(argv, root, stdout_path, stderr_path, timeout, stdin_text)
            stdout_path.write_text("", encoding="utf-8")
            stderr_path.write_text("", encoding="utf-8")
            return ralph.ProcessResult(124, timed_out=True)

        self.assertEqual(self.run_task(execute), 124)
        self.assertEqual(len(self.agent_calls), 1)
        self.assertEqual(self.status(), "blocked")
        self.assertIn("check_timeout", self.console)

    def test_check_permission_failure_stops_without_retry(self):
        self.assertEqual(
            self.run_task(self.fake_process(check_exit=1, error="permission denied")), 1
        )
        self.assertEqual(len(self.agent_calls), 1)
        self.assertIn("check_permission_denied", self.console)

    def test_nonfatal_path_alias_warning_does_not_mask_process_error(self):
        warning = (
            "WARNING: proceeding, even though we could not create PATH aliases: "
            "Operation not permitted (os error 1)\n"
        )
        self.assertEqual(
            self.run_task(self.fake_process(agent_exit=9, error=warning + "network unavailable")), 9
        )
        self.assertIn("agent_process_failed", self.console)

    def test_invalid_schema_types_are_rejected_without_type_error(self):
        path = self.root / "result.json"
        for field, value in [
            ("status", []),
            ("completed_criteria", [True]),
            ("completed_criteria", [1, 1]),
            ("completed_criteria", [3]),
            ("blockers", "text"),
            ("summary", {}),
        ]:
            with self.subTest(field=field, value=value):
                path.write_text(
                    json.dumps({**self.complete_result, field: value}), encoding="utf-8"
                )
                self.assertIsNone(ralph.read_agent_result(path, 2))


class SubprocessTests(unittest.TestCase):
    def test_subprocess_passes_argv_without_a_shell_and_stdin_without_argument_interpolation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = mock.Mock()
            fake.returncode = 0
            with mock.patch.object(ralph.subprocess, "Popen", return_value=fake) as popen:
                result = ralph.run_process(
                    ["fake", "literal; $(id)"], root, root / "out", root / "err", 5, "stdin prompt"
                )
            args, kwargs = popen.call_args
            self.assertEqual(args[0], ["fake", "literal; $(id)"])
            self.assertFalse(kwargs.get("shell", False))
            self.assertEqual(kwargs["cwd"], root)
            self.assertTrue(kwargs["start_new_session"])
            fake.communicate.assert_called_once_with(input="stdin prompt", timeout=5)
            self.assertEqual(result.returncode, 0)

    def test_real_fake_child_timeout_terminates_process_group(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            heartbeat = root / "heartbeat"
            child_code = (
                "import pathlib,time; p=pathlib.Path("
                + repr(str(heartbeat))
                + "); "
                + "exec('while True:\\n p.write_text(str(time.monotonic()))\\n time.sleep(0.05)')"
            )
            parent_code = (
                "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',"
                + repr(child_code)
                + "]); time.sleep(20)"
            )
            started = time.monotonic()
            result = ralph.run_process(
                [sys.executable, "-c", parent_code], root, root / "out", root / "err", 1
            )
            self.assertTrue(result.timed_out)
            self.assertEqual(result.returncode, 124)
            self.assertLess(time.monotonic() - started, 8)
            self.assertTrue(heartbeat.exists())
            value = heartbeat.read_text()
            time.sleep(0.15)
            self.assertEqual(heartbeat.read_text(), value)

    def test_missing_executable_has_meaningful_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ralph.RunnerError) as error:
                ralph.run_process(
                    [str(root / "does-not-exist")], root, root / "out", root / "err", 1
                )
            self.assertEqual(error.exception.exit_code, 127)


if __name__ == "__main__":
    unittest.main()
