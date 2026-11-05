"""C1E3 frozen acceptance. Native creation semantics require Windows separately."""

import copy
import ctypes as c
import importlib
import threading
import weakref

import pytest


def part(name):
    return importlib.import_module("ara.docx_analysis_worker.windows." + name)


def reject(call, code="runtime_unavailable"):
    with pytest.raises(part("_errors").WindowsRuntimeError) as exc:
        call()
    assert exc.value.code == code


class API:
    def __init__(self):
        self.calls = []
        self.limit, self.count = 2, 1
        self.member, self.previous, self.signalled, self.code = True, 1, False, 0
        self.outcome, self.fail = "created", None
        self.enter, self.leave = None, None
        self.next = 100

    def close(self, value):
        self.calls.append(("close", value))
        if self.fail == ("close", value):
            raise OSError("private sentinel")

    def new_job(self, limit):
        self.calls.append(("job", limit))
        self.limit = limit
        return 10

    def job_limits(self, value):
        return 0x2008, self.limit if self.fail != "limits" else 99

    def job_count(self, value):
        if self.fail == "query":
            raise OSError("private sentinel")
        return self.count

    def terminate_job(self, value):
        self.calls.append(("kill_job", value))
        if self.fail == "kill":
            raise OSError("private sentinel")

    def duplicate_rights(self, value, rights=None):
        self.next += 1
        self.calls.append(("duplicate", value, rights, self.next))
        return part("_handles").OwnedHandle(self, self.next)

    def launch(self, record, config, job, handles, stdio):
        self.calls.append(("create", job, tuple(handles), tuple(stdio)))
        if self.enter:
            self.enter.set()
            assert self.leave.wait(2)
        if self.outcome == "exception":
            raise OSError("private sentinel")
        record.capture(self.outcome != "failed", 20, 21 if self.outcome != "partial" else 0)

    def in_job(self, process, job):
        self.calls.append(("membership", process, job))
        if self.fail == "membership":
            raise OSError("private sentinel")
        return self.member

    def resume(self, thread):
        self.calls.append(("resume", thread))
        return self.previous

    def terminate_process(self, process):
        self.calls.append(("kill_process", process))

    def process_exit(self, process):
        self.calls.append(("wait", process))
        if self.fail == "wait":
            raise OSError("private sentinel")
        return self.code if self.signalled else None


@pytest.fixture
def runtime(monkeypatch):
    jobs, spawn = part("_jobs"), part("_spawn")
    api = API()
    monkeypatch.setattr(jobs, "_load_api", lambda: api)
    yield api, jobs, spawn
    # Test-only isolation of deliberately quarantined synthetic capabilities.
    spawn._REGISTRY.clear()


def record(runtime):
    api, jobs, spawn = runtime
    job = jobs.create_job(2)
    return api, job, spawn.SpawnRecord(api, job)


def create(rec):
    rec.create(
        {"fixture": True},
        {"stdin": 30, "stdout": 31, "ordinary": 32},
        ("stdin", "stdout", "stdout"),
    )


def test_abi_layouts():
    m = part("_process_abi")
    for name, size in {
        "STARTUPINFOW": 104,
        "STARTUPINFOEXW": 112,
        "PROCESS_INFORMATION": 24,
        "BASIC_LIMIT_INFORMATION": 64,
        "IO_COUNTERS": 48,
        "EXTENDED_LIMIT_INFORMATION": 144,
        "BASIC_ACCOUNTING_INFORMATION": 48,
    }.items():
        assert c.sizeof(getattr(m, name)) == size
    assert m.STARTUPINFOEXW.lpAttributeList.offset == 104
    assert m.BASIC_ACCOUNTING_INFORMATION.ActiveProcesses.offset == 40
    assert m.PROCESS_INFORMATION.dwProcessId.offset == 16


@pytest.mark.parametrize("kind", ["prepared", "armed", "gate"])
def test_tokens_exact_split_and_eof(kind):
    m = part("_bootstrap")
    reader = m.TokenReader(kind, eof_required=kind != "gate")
    for byte in m.TOKENS[kind]:
        reader.feed(bytes([byte]))
    assert reader.ready is (kind == "gate")
    if kind != "gate":
        reader.finish()
        assert reader.ready
    else:
        reject(reader.finish)
        assert not reader.ready


@pytest.mark.parametrize("payload", [b"!", b"AIRA-N1P!", b"", b"AIRA-N1"])
def test_token_poison(payload):
    r = part("_bootstrap").TokenReader("prepared")
    reject(lambda: (r.feed(payload), r.finish()))
    assert not r.ready
    reject(lambda: r.feed(b"AIRA-N1P"))


@pytest.mark.parametrize("value", [0, 3, True, "2", None])
def test_job_limit_validation(runtime, value):
    api, jobs, _ = runtime
    reject(lambda: jobs.create_job(value), "validation_error")
    assert not api.calls


def test_job_limits_and_kill_once(runtime):
    api, jobs, _ = runtime
    job = jobs.create_job(2)
    assert api.calls == [("job", 2)]
    job.terminate()
    job.terminate()
    assert api.calls.count(("kill_job", 10)) == 1
    with pytest.raises(TypeError):
        copy.copy(job)
    job.close()
    job.close()
    assert api.calls.count(("close", 10)) == 1
    reject(job.active_count, "invalid_handle")


def test_limit_readback_failure_closes(runtime):
    api, jobs, _ = runtime
    api.fail = "limits"
    reject(lambda: jobs.create_job(1))
    assert ("close", 10) in api.calls


def test_created_retained_before_resume_and_rights(runtime):
    api, job, rec = record(runtime)
    create(rec)
    assert rec.creation == "created" and not rec.exited
    assert not any(call[0] == "resume" for call in api.calls)
    assert ("duplicate", 32, 0x100000, 103) in api.calls
    assert 10 not in next(call[2] for call in api.calls if call[0] == "create")
    rec.resume(lambda: True)
    assert api.calls.count(("resume", 21)) == 1
    reject(lambda: rec.resume(lambda: True), "invalid_handle")
    api.signalled, api.count, api.code = True, 0, 259
    rec.poll()
    assert rec.exited and rec.exit_code == 259
    assert rec.close()
    job.close()


@pytest.mark.parametrize("outcome", ["failed", "exception", "partial"])
def test_failed_versus_unknown(runtime, outcome):
    api, job, rec = record(runtime)
    api.outcome, api.count = outcome, 0
    reject(lambda: create(rec))
    assert rec.creation == ("failed" if outcome == "failed" else "unknown")
    assert not any(call[0] == "resume" for call in api.calls)
    rec.terminate()
    assert rec.close() is (outcome == "failed")
    if outcome != "failed":
        with pytest.raises(part("_errors").WindowsRuntimeError):
            part("_spawn").SpawnRecord(api, job)


@pytest.mark.parametrize("member", [False, "error"])
def test_unverified_membership_exact_handle_cleanup(runtime, member):
    api, job, rec = record(runtime)
    api.member, api.fail = member is not False, "membership" if member == "error" else None
    reject(lambda: create(rec))
    rec.terminate()
    rec.terminate()
    assert api.calls.count(("kill_job", 10)) == 1
    assert api.calls.count(("kill_process", 20)) == 1
    assert not any(call[0] == "resume" for call in api.calls)
    api.signalled, api.count, api.fail = True, 0, None
    rec.poll()
    assert rec.close()


@pytest.mark.parametrize("previous", [0, 2, 0xFFFFFFFF])
def test_bad_resume_never_retries(runtime, previous):
    api, _, rec = record(runtime)
    create(rec)
    api.previous = previous
    reject(lambda: rec.resume(lambda: True))
    rec.terminate()
    reject(lambda: rec.resume(lambda: True), "invalid_handle")
    assert api.calls.count(("resume", 21)) == 1
    assert not any(call[0] == "kill_process" for call in api.calls)


def test_stop_before_resume_does_not_execute(runtime):
    api, _, rec = record(runtime)
    create(rec)
    reject(lambda: rec.resume(lambda: False))
    assert not any(call[0] == "resume" for call in api.calls)


def test_record_retained_and_no_close_during_create(runtime):
    api, _, rec = record(runtime)
    api.enter, api.leave = threading.Event(), threading.Event()
    done = []

    def owner():
        create(rec)
        rec.resume(lambda: False)  # no engine execution on cancelled start

    def run():
        try:
            owner()
        except part("_errors").WindowsRuntimeError:
            done.append(True)

    thread = threading.Thread(target=run)
    thread.start()
    assert api.enter.wait(2)
    assert rec.in_flight
    reject(rec.close, "invalid_handle")
    assert not any(call[0] in ("close", "kill_job", "kill_process") for call in api.calls)
    ref = weakref.ref(rec)
    assert ref() is not None
    api.leave.set()
    thread.join(2)
    assert done and not thread.is_alive()
    assert not any(call[0] == "resume" for call in api.calls)


@pytest.mark.parametrize("code,expected", [(0, 0), (259, 259), (0xC0000005, -1073741819)])
def test_exit_is_only_observed_after_signal(runtime, code, expected):
    api, _, rec = record(runtime)
    create(rec)
    api.code, api.count = code, 0
    rec.poll()
    assert not rec.exited and rec.exit_code is None and not rec.close()
    api.signalled = True
    rec.poll()
    assert rec.exited and rec.exit_code == expected and rec.close()


def test_guardian_budget_no_late_renewal():
    from uuid import UUID

    from ara.docx_analysis_worker.wire import WireBinding, encode_message

    binding = WireBinding(UUID(int=1), UUID(int=2))
    state = part("_guardian").GuardianBudget(binding, 20_000_000_000, 10_000_000_000)
    first = encode_message(
        binding,
        kind="permit",
        seq=0,
        values={"deadline_ns": "20000000000", "lease_ns": "10000000000"},
    )
    state.feed(first, 1_000_000_000)
    assert state.initial
    late = encode_message(
        binding,
        kind="permit",
        seq=1,
        values={"deadline_ns": "20000000000", "lease_ns": "15000000000"},
    )
    state.feed(late, 10_000_000_000)
    assert state.stopped and state.lease == 10_000_000_000


@pytest.mark.skipif(__import__("sys").platform != "win32", reason="native Windows Job gate pending")
def test_native_job_limit_and_reduced_rights():
    from ara.docx_analysis_worker.windows._events import create_event

    api = part("_process_abi").ProcessAPI()
    job = part("_jobs").create_job(1)
    event = create_event()
    dup = api.duplicate_rights(event.handle(), 0x100000)
    try:
        assert job.active_count() == 0
        reject(lambda: api.io.set_event(dup.value))
    finally:
        dup.close()
        event.close()
        job.close()
