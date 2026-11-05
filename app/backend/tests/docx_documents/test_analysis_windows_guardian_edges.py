"""Additional fault-injection and real-Windows fixture integration gates."""

import ctypes as c
import importlib
import json
import runpy
import sys
import threading
from pathlib import Path
from uuid import UUID

import pytest

from ara.docx_analysis_worker.wire import StreamDecoder, WireBinding, encode_message


def part(name):
    return importlib.import_module("ara.docx_analysis_worker.windows." + name)


def reject(call):
    with pytest.raises(part("_errors").WindowsRuntimeError):
        call()


class Clock:
    value = 1_000_000_000

    def now_ns(self):
        return self.value


class Endpoint:
    def __init__(self, api, kind, data=()):
        api.next += 1
        self._handle = part("_handles").OwnedHandle(api, api.next)
        self._kind, self._io_thread, self._close_failed = kind, None, False
        self._mutex = threading.Lock()
        self._operation = None
        self.data, self.written, self.closed = list(data), bytearray(), False

    def handle(self):
        return self._handle.value

    def begin_read(self):
        self._io_thread = threading.get_ident()
        endpoint = self

        class Operation:
            def poll(self):
                if not endpoint.data:
                    return None
                data = endpoint.data.pop(0)
                return part("_pending").IOResult("read", len(data), data, eof=not data)

            def event_handle(self):
                return endpoint.handle()

        return Operation()

    def begin_write(self, data):
        self._io_thread = threading.get_ident()
        endpoint = self

        class Operation:
            def poll(self):
                endpoint.written.extend(data)
                return part("_pending").IOResult("write", len(data), b"")

            def event_handle(self):
                return endpoint.handle()

        return Operation()

    def close(self):
        if self._handle is not None:
            self._handle.close()
            self._handle = None
        self.closed = True
        return True


@pytest.fixture
def fake(monkeypatch):
    helpers = runpy.run_path(
        str(Path(__file__).parents[1] / "acceptance/test_docx_analysis_windows_guardian.py")
    )
    fs_helpers = runpy.run_path(
        str(Path(__file__).parents[1] / "acceptance/test_docx_analysis_windows_primitives.py")
    )
    api, fs, clock = helpers["API"](), fs_helpers["FakeFS"](), Clock()
    monkeypatch.setattr(part("_jobs"), "_load_api", lambda: api)
    monkeypatch.setattr(part("_locks").sys, "platform", "win32")
    monkeypatch.setattr(part("_paths"), "_load_filesystem", lambda: fs)
    monkeypatch.setattr(part("_launch"), "WindowsClock", lambda: clock)
    api.nul = lambda write=False: part("_handles").OwnedHandle(api, 800 + int(write))
    api.clear_inherit = lambda handle: None
    api.windows_directory = lambda: r"C:\Windows"
    api.io = type("Events", (), {"wait_event": lambda *a: False})()

    def wait(handles, timeout=100):
        clock.value += max(1, timeout) * 1_000_000
        if clock.value > 30_000_000_000:
            raise ValueError("test bounded loop")

    api.wait = wait
    owner = part("_locks").acquire_owner(r"C:\synthetic")
    slot = owner.reserve_slot()
    yield api, clock, owner, slot
    part("_spawn")._REGISTRY.clear()
    part("_launch")._REGISTRY.clear()
    owner.abandon()


def binding():
    return WireBinding(UUID(int=1), UUID(int=2))


def test_holder_is_retained_before_io_and_stop_before_start(fake):
    api, _, owner, slot = fake
    launch = part("_launch")
    obj = launch.prepare_fixture_guardian(
        slot, binding(), deadline_ns=20_000_000_000, lease_ns=10_000_000_000
    )
    assert not api.calls
    reject(lambda: launch.prepare_fixture_guardian(slot, binding(), deadline_ns=20, lease_ns=10))
    obj.request_stop()
    reject(obj.start)
    assert obj.finish_close()
    assert not any(call[0] in ("create", "resume", "job") for call in api.calls)
    assert slot.handle() and owner.release_slot(slot)


@pytest.mark.parametrize("which", ["binding", "bool", "mode"])
def test_invalid_holder_configuration_no_io(fake, which):
    api, _, _, slot = fake
    kw = dict(deadline_ns=20, lease_ns=10, mode="success")
    b = binding()
    if which == "binding":
        b = WireBinding("bad", UUID(int=2))
    elif which == "bool":
        kw["lease_ns"] = True
    else:
        kw["mode"] = "arbitrary.exe"
    reject(lambda: part("_launch").prepare_fixture_guardian(slot, b, **kw))
    assert not api.calls and not part("_launch")._REGISTRY


@pytest.mark.parametrize("outcome", ["created", "failed", "exception"])
def test_holder_cleanup_never_releases_caller_slot(fake, monkeypatch, outcome):
    api, clock, owner, slot = fake
    api.outcome = outcome
    pairs = []

    def pair(**kw):
        p = type("Pair", (), {"reader": Endpoint(api, "read"), "writer": Endpoint(api, "write")})()
        pairs.append(p)
        return p

    class Event:
        def __init__(self):
            api.next += 1
            self.value = api.next

        def handle(self):
            return self.value

        def set(self):
            pass

        def close(self):
            pass

    m = part("_launch")
    monkeypatch.setattr(m, "create_pipe_pair", pair)
    monkeypatch.setattr(m, "create_event", Event)
    obj = m.prepare_fixture_guardian(
        slot, binding(), deadline_ns=20_000_000_000, lease_ns=10_000_000_000
    )
    if outcome == "created":
        obj.start()
        # Old initial lease must not kill a successfully renewed guardian.
        clock.value = 11_000_000_000
        assert not obj.poll_process().hard_fault
        assert not any(call[0] == "kill_job" for call in api.calls)
        assert not obj.finish_close()
        api.signalled, api.count = True, 0
    else:
        reject(obj.start)
        api.count = 0
    observation = obj.poll_process()
    assert not observation.resources_closed
    assert obj.finish_close() is (outcome != "exception")
    assert slot.handle()
    if outcome != "exception":
        assert all(p.reader.closed and p.writer.closed for p in pairs)
        assert owner.release_slot(slot)
    else:
        assert observation.creation == "unknown"


def test_record_close_error_stays_quarantined(fake):
    api, _, _, _ = fake
    job = part("_jobs").create_job(2)
    rec = part("_spawn").SpawnRecord(api, job)
    rec.create({}, {"stdin": 30}, ("stdin", "stdin", "stdin"))
    api.signalled, api.count, api.fail = True, 0, ("close", 20)
    rec.poll()
    assert not rec.close() and not rec.close()
    assert api.calls.count(("close", 20)) == 1


@pytest.mark.parametrize("fault", ["wait", "query", "kill"])
def test_native_fault_is_sticky_but_does_not_forge_exit(fake, fault):
    api, _, _, _ = fake
    job = part("_jobs").create_job(2)
    rec = part("_spawn").SpawnRecord(api, job)
    rec.create({}, {"stdin": 30}, ("stdin", "stdin", "stdin"))
    api.fail = fault
    if fault == "wait":
        reject(rec.poll)
    elif fault == "query":
        reject(job.active_count)
    else:
        rec.terminate()
    assert rec.fault or job.fault
    assert not rec.exited and rec.exit_code is None
    api.signalled, api.count, api.fail = True, 0, None
    rec.poll()
    assert rec.close()
    assert rec.fault or job.fault


@pytest.mark.parametrize("mutation", ["backwards", "late", "initial", "oversized", "malformed"])
def test_budget_rejects_bad_or_late_control(mutation):
    state = part("_guardian").GuardianBudget(binding(), 20_000_000_000, 10_000_000_000)
    first = encode_message(
        binding(),
        kind="permit",
        seq=0,
        values={"deadline_ns": "20000000000", "lease_ns": "10000000000"},
    )
    if mutation == "initial":
        first = encode_message(
            binding(),
            kind="permit",
            seq=0,
            values={"deadline_ns": "20000000000", "lease_ns": "9000000000"},
        )
    state.feed(first, 1_000_000_000)
    if mutation == "backwards":
        state.check(999_999_999)
    elif mutation == "late":
        state.check(10_000_000_000)
    elif mutation == "oversized":
        state.feed((4097).to_bytes(4, "big"), 2_000_000_000)
    elif mutation == "malformed":
        state.feed(b"\0\0\0\1!", 2_000_000_000)
    assert state.stopped
    assert state.hard is (mutation != "late")


def test_job_failed_close_never_retries_reused_number(fake):
    api, _, _, _ = fake
    job = part("_jobs").create_job(2)
    api.fail = ("close", 10)
    reject(job.close)
    api.fail = None
    reject(job.close)
    assert api.calls.count(("close", 10)) == 1


@pytest.mark.parametrize("kind", ["success", "nonzero", "stop", "flood", "early"])
def test_guardian_loop_composes_actual_wait_and_status(fake, monkeypatch, kind):
    api, clock, _, _ = fake
    m = part("_guardian")
    monkeypatch.setattr(m, "WindowsClock", lambda: clock)
    permit = encode_message(
        binding(),
        kind="permit",
        seq=0,
        values={"deadline_ns": "20000000000", "lease_ns": "10000000000"},
    )
    inherited = {
        n: Endpoint(api, k, [permit] if n == "control" else [])
        for n, k in {
            "control": "read",
            "status": "write",
            "armed": "write",
            "request": "read",
            "events": "write",
        }.items()
    }
    for n, h in {"slot": 501, "ordinary": 502, "hard": 503, "stdin": 504, "stdout": 505}.items():
        inherited[n] = part("_handles").OwnedHandle(api, h)
    made = []

    def pair(**kw):
        index = len(made)
        data = (
            [b"AIRA-N1P", b""]
            if index == 0
            else ([b"x" * 65536, b"x", b""] if kind == "flood" else [b""])
            if index == 2
            else []
        )
        value = type(
            "Pair", (), {"reader": Endpoint(api, "read", data), "writer": Endpoint(api, "write")}
        )()
        made.append(value)
        return value

    monkeypatch.setattr(m, "create_pipe_pair", pair)

    def exited(process):
        if (
            kind == "early"
            or made
            and bytes(inherited["armed"].written) == b"AIRA-N1A"
            or any(c[0] == "kill_job" for c in api.calls)
        ):
            api.count = 0
            return 76 if kind == "nonzero" else 0
        return None

    api.process_exit = exited
    api.io.wait_event = lambda h, t: (
        kind == "stop" and any(call[0] == "create" for call in api.calls) and h == 502
    )
    assert m.run(api, inherited, binding(), 20_000_000_000, 10_000_000_000, "success") == 0
    decoder = StreamDecoder(binding(), lane="status")
    messages = decoder.feed(bytes(inherited["status"].written))
    decoder.finish()
    expected = "clean" if kind == "success" else "stopped" if kind == "stop" else "crashed"
    assert messages[0].values["exit_kind"] == expected
    assert messages[0].values["cleanup_confirmed"] is True
    assert api.calls.count(("resume", 21)) <= 1
    if kind in ("early", "stop", "flood"):
        assert not inherited["armed"].written


def test_launch_config_environment_and_alias_rejection():
    m = part("_adopt")
    handles = {k: n + 10 for n, k in enumerate(m.G_ROLES)}
    raw = json.dumps(m.config("G", binding(), 20, 10, "success", handles))
    assert m.parse(raw, "G")[0] == binding()
    handles["slot"] = handles["control"]
    reject(lambda: m.parse(json.dumps(m.config("G", binding(), 20, 10, "success", handles)), "G"))
    api = type("OS", (), {"windows_directory": lambda s: r"C:\Windows"})()
    exe, argv, cwd, environment = m.launch_config("G", binding(), 20, 10, "success", {}, api)
    assert set(environment) == {"SystemRoot", "WINDIR"}
    assert argv[1:3] == ["-I", "-B"] and Path(exe).is_absolute() and Path(cwd).is_absolute()


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows guardian process gate pending")
@pytest.mark.parametrize(
    "mode",
    [
        "success",
        "nonzero",
        "tail",
        "error",
        "exit_259",
        "exit_ntstatus",
        "wait",
        "native_hang",
        "result_hang",
        "diagnostic_flood",
        "prepared_extra",
        "guardian_death",
    ],
)
def test_native_guardian_exchange_and_stop(tmp_path, mode):
    import base64
    import hashlib

    m = part("_launch")
    api = part("_process_abi").ProcessAPI()
    root = str(tmp_path / "private synthetic fixture")
    create = api.kernel.CreateDirectoryW
    create.argtypes = [c.c_wchar_p, c.c_void_p]
    create.restype = c.c_int32
    with part("_security").descriptor(api.io.base, api.io.user(), directory=True) as sa:
        assert create(root, c.byref(sa))
    owner = part("_locks").acquire_owner(root)
    slot, clock = owner.reserve_slot(), part("_clock").WindowsClock()
    now = clock.now_ns()
    deadline, lease = now + 15_000_000_000, now + 12_000_000_000
    obj = m.prepare_fixture_guardian(
        slot,
        binding(),
        deadline_ns=deadline,
        lease_ns=lease,
        mode="native_hang" if mode == "guardian_death" else mode,
    )
    lanes = []
    try:
        obj.start()
        lane_type = part("_guardian").Lane
        ch = obj.channels
        control, request, events, status, armed = [
            lane_type(getattr(ch, n)) for n in ("control", "request", "events", "status", "armed")
        ]
        lanes = [control, request, events, status, armed]
        control.queue(
            encode_message(
                binding(),
                kind="permit",
                seq=0,
                values={"deadline_ns": str(deadline), "lease_ns": str(lease)},
            )
        )
        token = part("_bootstrap").TokenReader("armed")
        spec, payload = b"fixture-spec", b"synthetic-request"
        digest = hashlib.sha256(spec).hexdigest()
        event_decoder, status_decoder = (
            StreamDecoder(binding(), lane="events", expected_execution_spec_sha256=digest),
            StreamDecoder(binding(), lane="status"),
        )
        closed, seen, sent = [], [], False
        killed = False
        while clock.now_ns() < deadline:
            control.step()
            a = armed.step()
            if a is not None:
                token.finish() if a.eof else token.feed(a.data)
            if token.ready and not sent:
                request.queue(
                    encode_message(
                        binding(),
                        kind="run",
                        seq=0,
                        values={
                            "worker_instance_id": str(UUID(int=3)),
                            "claim_fence": 1,
                            "request_sha256": hashlib.sha256(payload).hexdigest(),
                            "execution_spec_sha256": digest,
                            "request_b64": base64.b64encode(payload).decode(),
                            "execution_spec_b64": base64.b64encode(spec).decode(),
                        },
                    )
                )
                sent = True
            if sent:
                request.step()
                if request.idle:
                    request.close()
            e, s = events.step(), status.step()
            if e is not None and not e.eof:
                try:
                    seen.extend(event_decoder.feed(e.data))
                except Exception:
                    assert mode == "tail"
            if s is not None and not s.eof:
                closed.extend(status_decoder.feed(s.data))
            if mode in ("wait", "native_hang", "result_hang") and any(
                x.kind == "stage" for x in seen
            ):
                obj.request_stop()
            if mode == "guardian_death" and not killed and any(x.kind == "stage" for x in seen):
                api.terminate_process(obj._record._process.value)
                killed = True
            obs = obj.poll_process()
            if obs.process_exited and events.eof and status.eof:
                break
            part("_guardian").wait_turn(api, lanes)
        assert obs.process_exited and obs.job_empty
        if mode == "guardian_death":
            assert killed and not closed and obs.hard_fault
            return
        assert closed
        expected = (
            "clean"
            if mode in ("success", "tail")
            else "stopped"
            if mode in ("wait", "native_hang", "result_hang")
            else "crashed"
        )
        assert closed[0].values["exit_kind"] == expected
        if mode == "success":
            event_decoder.finish()
            assert seen[-1].payload == b"fixture-response"
        if mode == "exit_259":
            assert closed[0].values["exit_code"] == 259
        if mode == "exit_ntstatus":
            assert closed[0].values["exit_code"] == -1073741819
    finally:
        obj.request_stop(hard=True)
        cutoff = clock.now_ns() + 7_000_000_000
        while clock.now_ns() < cutoff:
            for lane in lanes:
                lane.close()
            if obj.finish_close():
                break
            api.wait([], 50)
        assert obj.finish_close(), "native cleanup unconfirmed"
        assert owner.release_slot(slot)
        owner.close()


@pytest.mark.skipif(
    sys.platform != "win32", reason="native Windows100 attempt HANDLE/thread gate pending"
)
def test_native_hundred_fixture_attempts_no_parent_handle_or_thread_growth(tmp_path):
    api = part("_process_abi").ProcessAPI()
    count = api.kernel.GetProcessHandleCount
    count.argtypes, count.restype = [c.c_void_p, c.POINTER(c.c_uint32)], c.c_int32

    def handles():
        result = c.c_uint32()
        assert count(api.kernel.GetCurrentProcess(), c.byref(result))
        return result.value

    # Warm up interpreter imports before the native resource baseline.
    warm = tmp_path / "warm"
    warm.mkdir()
    test_native_guardian_exchange_and_stop(warm, "success")
    initial_handles, initial_threads = handles(), len(threading.enumerate())
    for index in range(100):
        directory = tmp_path / str(index)
        directory.mkdir()
        test_native_guardian_exchange_and_stop(directory, "success")
    assert handles() == initial_handles
    assert len(threading.enumerate()) == initial_threads
