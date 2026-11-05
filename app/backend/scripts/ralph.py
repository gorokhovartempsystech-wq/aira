#!/usr/bin/env python3
"""Run one explicit task through a bounded Codex/check feedback loop.

Only the runner owns task status and the progress journal. Raw subprocess output
stays in ignored .ralph/runs; console output contains categorical results only.
"""

from __future__ import annotations

import argparse
import fcntl
import fnmatch
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

TASK_FILE = Path("ralph/tasks.json")
PROGRESS_FILE = Path("ralph/progress.jsonl")
PROMPT_FILE = Path("ralph/prompt.md")
CHECK_TIMEOUT = 300
MAX_NO_PROGRESS = 2
APPROVAL_POLICY = "on-request"
APPROVALS_REVIEWER = "auto_review"
RESULT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["status", "summary", "completed_criteria", "blockers"],
    "properties": {
        "status": {"type": "string", "enum": ["complete", "continue", "blocked"]},
        "summary": {"type": "string"},
        "completed_criteria": {"type": "array", "items": {"type": "integer"}},
        "blockers": {"type": "array", "items": {"type": "string"}},
    },
}


class RunnerError(Exception):
    def __init__(self, category: str, exit_code: int = 2):
        self.category = category
        self.exit_code = exit_code
        super().__init__(category)


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    timed_out: bool = False


def read_tasks(root: Path) -> dict[str, Any]:
    try:
        document = json.loads((root / TASK_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RunnerError("invalid_task_file") from exc
    if not isinstance(document, dict) or not isinstance(document.get("tasks"), list):
        raise RunnerError("invalid_task_file")
    seen: set[str] = set()
    for task in document["tasks"]:
        if not isinstance(task, dict):
            raise RunnerError("invalid_task_file")
        task_id = task.get("id")
        if not isinstance(task_id, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", task_id
        ):
            raise RunnerError("invalid_task_id")
        if task_id in seen:
            raise RunnerError("duplicate_task_id")
        seen.add(task_id)
        if not isinstance(task.get("status"), str) or task["status"] not in {
            "pending",
            "in_progress",
            "completed",
            "blocked",
        }:
            raise RunnerError("invalid_task_status")
    return document


def select_task(document: dict[str, Any], task_id: str) -> dict[str, Any]:
    selected = next((task for task in document["tasks"] if task["id"] == task_id), None)
    if selected is None:
        raise RunnerError("task_not_found")
    for key in ("title", "prompt"):
        if not isinstance(selected.get(key), str) or not selected[key].strip():
            raise RunnerError("invalid_task_definition")
    criteria = selected.get("acceptance_criteria")
    if (
        not isinstance(criteria, list)
        or not criteria
        or not all(isinstance(c, str) and c.strip() for c in criteria)
    ):
        raise RunnerError("invalid_acceptance_criteria")
    argv = selected.get("check_command")
    if (
        not isinstance(argv, list)
        or not argv
        or not all(isinstance(a, str) and a and "\0" not in a for a in argv)
    ):
        raise RunnerError("invalid_check_command")
    dependencies = selected.get("depends_on", [])
    if not isinstance(dependencies, list) or not all(isinstance(d, str) for d in dependencies):
        raise RunnerError("invalid_dependencies")
    states = {task["id"]: task["status"] for task in document["tasks"]}
    if any(d == task_id or states.get(d) != "completed" for d in dependencies):
        raise RunnerError("dependencies_not_completed")
    paths = selected.get("allowed_paths")
    if (
        not isinstance(paths, list)
        or not paths
        or not all(
            isinstance(p, str) and p.strip() and not p.startswith("/") and ".." not in Path(p).parts
            for p in paths
        )
    ):
        raise RunnerError("invalid_allowed_paths")
    return selected


def read_common_prompt(root: Path) -> str:
    try:
        prompt = (root / PROMPT_FILE).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RunnerError("common_prompt_missing") from exc
    except (OSError, UnicodeError) as exc:
        raise RunnerError("common_prompt_unreadable") from exc
    if not prompt.strip():
        raise RunnerError("common_prompt_empty")
    return prompt


def set_task_status(root: Path, task_id: str, status: str) -> None:
    document = read_tasks(root)
    task = next(t for t in document["tasks"] if t["id"] == task_id)
    task["status"] = status
    target = root / TASK_FILE
    fd, temporary = tempfile.mkstemp(prefix=".tasks-", suffix=".json", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def record_progress(
    root: Path,
    task_id: str,
    run: Path,
    attempt: int,
    status: str,
    reason: str,
    agent_exit: int | None = None,
    check_exit: int | None = None,
) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task_id": task_id,
        "run": str(run.relative_to(root)),
        "attempt": attempt,
        "status": status,
        "reason": reason,
        "agent_exit": agent_exit,
        "check_exit": check_exit,
    }
    with (root / PROGRESS_FILE).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


@contextmanager
def runner_lock(root: Path) -> Iterator[None]:
    directory = root / ".ralph"
    directory.mkdir(exist_ok=True, mode=0o700)
    with (directory / "runner.lock").open("a") as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RunnerError("runner_already_active") from exc
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def stop_process_group(process: subprocess.Popen[str]) -> None:
    """Stop descendants too, including when the group leader has already exited."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def run_process(
    argv: list[str],
    root: Path,
    stdout_path: Path,
    stderr_path: Path,
    timeout: int,
    stdin_text: str | None = None,
) -> ProcessResult:
    with (
        stdout_path.open("w", encoding="utf-8") as output,
        stderr_path.open("w", encoding="utf-8") as errors,
    ):
        try:
            process = subprocess.Popen(
                argv,
                cwd=root,
                stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                stdout=output,
                stderr=errors,
                text=True,
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            raise RunnerError("executable_not_found", 127) from exc
        except PermissionError as exc:
            raise RunnerError("executable_permission_denied", 126) from exc
        try:
            process.communicate(input=stdin_text, timeout=timeout)
        except subprocess.TimeoutExpired:
            stop_process_group(process)
            return ProcessResult(124, timed_out=True)
        except BaseException:
            stop_process_group(process)
            raise
        return ProcessResult(process.returncode)


def snapshot(root: Path) -> dict[str, str]:
    """Snapshot Git-visible files, never follow symlinks or scan the ignored archive."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=root,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RunnerError("git_snapshot_failed") from exc
    if result.returncode:
        raise RunnerError("git_snapshot_failed")
    state: dict[str, str] = {}
    for raw_name in result.stdout.split(b"\0"):
        if not raw_name:
            continue
        name = os.fsdecode(raw_name)
        if name.startswith(".ralph/"):
            continue
        path = root / name
        if path.is_symlink():
            state[name] = "symlink:" + os.readlink(path)
        elif path.is_file():
            # A symlink in a parent component must not redirect reads outside root.
            if not path.resolve().is_relative_to(root):
                raise RunnerError("snapshot_path_outside_workspace")
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            state[name] = str(path.stat().st_mode & 0o777) + ":" + digest.hexdigest()
        elif path.exists():
            raise RunnerError("unsupported_snapshot_entry")
    return state


def changed_paths(before: dict[str, str], after: dict[str, str]) -> set[str]:
    return {name for name in before.keys() | after.keys() if before.get(name) != after.get(name)}


def within_scope(paths: set[str], patterns: list[str]) -> bool:
    if not patterns:
        return not paths  # Missing ownership is never permission to edit the repository.
    protected = {
        str(TASK_FILE),
        str(PROGRESS_FILE),
        str(PROMPT_FILE),
        "scripts/ralph.py",
        "scripts/check.sh",
        "AGENTS.md",
    }
    return all(
        name not in protected and any(fnmatch.fnmatchcase(name, p) for p in patterns)
        for name in paths
    )


def read_agent_result(path: Path, criteria_count: int) -> dict[str, Any] | None:
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(result, dict) or set(result) != set(RESULT_SCHEMA["required"]):
        return None
    if (
        not isinstance(result["status"], str)
        or result["status"] not in {"complete", "continue", "blocked"}
        or not isinstance(result["summary"], str)
    ):
        return None
    indices, blockers = result["completed_criteria"], result["blockers"]
    if not isinstance(indices, list) or not all(
        type(i) is int and 1 <= i <= criteria_count for i in indices
    ):
        return None
    if len(set(indices)) != len(indices):
        return None
    if not isinstance(blockers, list) or not all(isinstance(b, str) for b in blockers):
        return None
    return result


def failure_category(stderr_path: Path, stdout_path: Path) -> str:
    """Inspect local error logs without exposing their contents to the console."""
    messages: list[str] = []
    with stderr_path.open(encoding="utf-8", errors="replace") as stream:
        messages.extend(
            line
            for line in stream
            if not line.startswith(
                "WARNING: proceeding, even though we could not create PATH aliases:"
            )
        )
    with stdout_path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("type") in {
                "error",
                "turn.failed",
                "warning",
                "config.warning",
                "config_warning",
            }:
                messages.append(json.dumps(event))
            elif isinstance(event, dict) and event.get("type") == "item.completed":
                item = event.get("item")
                if isinstance(item, dict) and item.get("type") in {"error", "warning"}:
                    messages.append(json.dumps(item))
    text = "\n".join(messages).lower()
    if re.search(
        r"approval_policy|approval policy|approvals_reviewer|approvals reviewer", text
    ) and re.search(r"not allowed|not permitted|disallowed|falling back|fallback", text):
        return "agent_managed_permission_rejected"
    if re.search(
        r"\b(401|unauthorized|unauthenticated|authentication|invalid_api_key)\b"
        r"|not logged in|login required",
        text,
    ):
        return "agent_authentication_failed"
    if re.search(r"\b(429|quota|rate.limit|usage.limit)\b|credits? exhausted|usage cap", text):
        return "agent_quota_or_rate_limit"
    if re.search(
        r"\b403\b|permission denied|operation not permitted|approval required"
        r"|approval denied|sandbox.*denied",
        text,
    ):
        return "agent_permission_denied"
    return "agent_process_failed"


def make_prompt(
    task: dict[str, Any], attempt: int, previous: str | None, common_prompt: str
) -> str:
    criteria = "\n".join(f"{i}. {item}" for i, item in enumerate(task["acceptance_criteria"], 1))
    feedback = (
        f"Previous attempt: {previous}. Read the prior attempt logs in .ralph/runs if useful."
        if previous
        else "First attempt."
    )
    return f"""Implement exactly the selected task {task["id"]}: {task["title"]}.
Read AGENTS.md and the referenced project instructions first. Other people may be
working here; preserve existing changes. Work only in these allowed paths:
{json.dumps(task.get("allowed_paths", []))}
Do not change task definitions, acceptance criteria, runner, check scripts,
progress journal, dependencies, original artifact archives or Git metadata.
Do not commit, push, publish, install software/dependencies, change authentication
or model/provider, access new external services, or read/display secrets.
Do not read the user's settings/auth files or dump environment variables.
For already authorized task operations blocked by the sandbox, use the supported
approval flow. Never bypass sandbox or managed requirements. If approval is denied
or unavailable, or an undeclared dependency, new external service or user choice
is required, stop with status blocked and explain the blocker in the structured result.

Common project instructions from ralph/prompt.md:
{common_prompt}

Task:
{task["prompt"]}

Acceptance criteria (one-based indices for completed_criteria):
{criteria}

Validation argv (runner independently executes this):
{json.dumps(task["check_command"])}

Attempt {attempt}. {feedback}
Return only the JSON object requested by the output schema. status complete
requires all criteria to be fulfilled; list only actually completed criterion
indices. status continue means useful work remains within this task. Do not
claim completion from tests alone if a criterion is not met. blockers must be
empty for complete. The runner alone updates task status and progress.
"""


def normalize_exit(returncode: int) -> int:
    return returncode if returncode > 0 else 128 - returncode


def run_task(
    root: Path, task_id: str, max_iterations: int, agent_timeout: int, dry_run: bool = False
) -> int:
    root = root.resolve()
    if not 1 <= max_iterations <= 3 or not 1 <= agent_timeout <= 3600:
        raise RunnerError("invalid_run_bounds")
    task = select_task(read_tasks(root), task_id)
    common_prompt = read_common_prompt(root)
    if dry_run:
        print(
            json.dumps(
                {
                    "task": task_id,
                    "current_status": task["status"],
                    "max_iterations": max_iterations,
                    "agent_timeout_seconds": agent_timeout,
                    "check_timeout_seconds": CHECK_TIMEOUT,
                    "check_command": task["check_command"],
                    "sandbox": "workspace-write",
                    "approval_policy": APPROVAL_POLICY,
                    "approvals_reviewer": APPROVALS_REVIEWER,
                    "allowed_paths": task.get("allowed_paths", []),
                    "dry_run": True,
                },
                ensure_ascii=False,
            )
        )
        return 0
    if task["status"] == "completed":
        print(f"{task_id}: already_completed; no agent started")
        return 0
    with runner_lock(root):
        # Re-read after obtaining the exclusive lock, preserving other tasks.
        task = select_task(read_tasks(root), task_id)
        if task["status"] == "completed":
            print(f"{task_id}: already_completed; no agent started")
            return 0
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        run = root / ".ralph" / "runs" / f"{task_id}-{run_id}"
        run.mkdir(parents=True, mode=0o700)
        schema_path = run / "result-schema.json"
        schema_path.write_text(json.dumps(RESULT_SCHEMA, indent=2) + "\n", encoding="utf-8")
        set_task_status(root, task_id, "in_progress")
        record_progress(root, task_id, run, 0, "in_progress", "started")
        no_progress = 0
        previous: str | None = None
        attempt = 0

        def finish(
            reason: str,
            exit_code: int,
            agent_exit: int | None = None,
            check_exit: int | None = None,
            completed: bool = False,
        ) -> int:
            status = "completed" if completed else "blocked"
            set_task_status(root, task_id, status)
            record_progress(root, task_id, run, attempt, status, reason, agent_exit, check_exit)
            print(f"{task_id}: {status} ({reason}); logs: {run.relative_to(root)}")
            return exit_code

        try:
            for attempt in range(1, max_iterations + 1):
                attempt_path = run / f"attempt-{attempt}"
                attempt_path.mkdir(mode=0o700)
                result_path = attempt_path / "result.json"
                stdout_path, stderr_path = (
                    attempt_path / "agent.jsonl",
                    attempt_path / "agent.stderr.log",
                )
                prompt = make_prompt(task, attempt, previous, common_prompt)
                (attempt_path / "prompt.txt").write_text(prompt, encoding="utf-8")
                before = snapshot(root)
                argv = [
                    "codex",
                    "exec",
                    # This supported preset sets on-request, auto_review and workspace-write.
                    # --sandbox on the same command conflicts with the preset in CLI 0.154.0.
                    "--approve-for-me",
                    "-C",
                    str(root),
                    "--json",
                    "--color",
                    "never",
                    "--output-schema",
                    str(schema_path),
                    "--output-last-message",
                    str(result_path),
                    "-",
                ]
                agent = run_process(argv, root, stdout_path, stderr_path, agent_timeout, prompt)
                if agent.timed_out:
                    return finish("agent_timeout", 124, agent.returncode)
                category = failure_category(stderr_path, stdout_path)
                if category == "agent_managed_permission_rejected":
                    return finish(
                        category,
                        normalize_exit(agent.returncode) if agent.returncode else 2,
                        agent.returncode,
                    )
                if agent.returncode:
                    return finish(
                        category,
                        normalize_exit(agent.returncode),
                        agent.returncode,
                    )
                after = snapshot(root)
                changed = changed_paths(before, after)
                if not within_scope(changed, task.get("allowed_paths", [])):
                    return finish("changes_outside_task_scope", 2, agent.returncode)
                result = read_agent_result(result_path, len(task["acceptance_criteria"]))
                if result is None:
                    return finish("invalid_agent_result", 2, agent.returncode)
                if result["status"] == "blocked":
                    return finish("agent_reported_blocker", 2, agent.returncode)
                check = run_process(
                    task["check_command"],
                    root,
                    attempt_path / "check.stdout.log",
                    attempt_path / "check.stderr.log",
                    CHECK_TIMEOUT,
                )
                if check.timed_out:
                    return finish("check_timeout", 124, agent.returncode, check.returncode)
                if check.returncode:
                    category = failure_category(
                        attempt_path / "check.stderr.log", attempt_path / "check.stdout.log"
                    )
                    if category != "agent_process_failed":
                        return finish(
                            category.replace("agent_", "check_", 1),
                            normalize_exit(check.returncode),
                            agent.returncode,
                            check.returncode,
                        )
                complete = (
                    result["status"] == "complete"
                    and not result["blockers"]
                    and set(result["completed_criteria"])
                    == set(range(1, len(task["acceptance_criteria"]) + 1))
                )
                if check.returncode == 0 and complete:
                    return finish(
                        "criteria_and_checks_passed",
                        0,
                        agent.returncode,
                        check.returncode,
                        completed=True,
                    )
                previous = (
                    "checks_failed" if check.returncode else "agent_has_not_completed_all_criteria"
                )
                no_progress = no_progress + 1 if not changed else 0
                record_progress(
                    root,
                    task_id,
                    run,
                    attempt,
                    "in_progress",
                    previous,
                    agent.returncode,
                    check.returncode,
                )
                if no_progress >= MAX_NO_PROGRESS:
                    return finish(
                        "repeated_no_progress",
                        normalize_exit(check.returncode) if check.returncode else 2,
                        agent.returncode,
                        check.returncode,
                    )
                if attempt == max_iterations:
                    return finish(
                        "iteration_limit",
                        normalize_exit(check.returncode) if check.returncode else 2,
                        agent.returncode,
                        check.returncode,
                    )
        except KeyboardInterrupt:
            return finish("interrupted", 130)
        except RunnerError as exc:
            return finish(exc.category, exc.exit_code)
        except OSError:
            return finish("filesystem_error", 2)
    raise RunnerError("unexpected_loop_exit")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True, help="Run exactly this task ID")
    parser.add_argument("--max-iterations", type=int, default=3, choices=range(1, 4))
    parser.add_argument(
        "--agent-timeout", type=int, default=600, help="Seconds per agent process (1..3600)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print plan without executing tools or writing files"
    )
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent.parent
    try:
        return run_task(root, args.task, args.max_iterations, args.agent_timeout, args.dry_run)
    except RunnerError as exc:
        print(f"Ralph stopped: {exc.category}", file=sys.stderr)
        return exc.exit_code
    except OSError:
        print("Ralph stopped: filesystem_error", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
