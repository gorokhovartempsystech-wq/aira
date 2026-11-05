"""D2 Stop addendum: immutable evidence, deterministic finalization and native smoke."""

import errno
import itertools
import json
from pathlib import Path

import pytest

from tests.acceptance.test_docx_analysis_macos_guardian import (
    exercise,
    exit_event,
    module,
    native,
    owned,
    root,
)
from tests.acceptance.test_docx_analysis_macos_primitives import reject

__all__ = ["native", "root"]


def classify(child, stop=True, hard=False):
    return module("_guardian")._closed_kind(
        exited=child.exited,
        lost=child.lost,
        exit_code=child.exit_code,
        stop_requested=stop,
        hard_fault=hard or child.hard_fault,
        signal_error=child.signal_error,
    )


def test_complete_outcome_table():
    fn = module("_guardian")._closed_kind
    for w, lost, h, r, s in itertools.product((False, True), repeat=5):
        for code in (None, 0, 74, -15, -9, 76):
            result = fn(
                exited=w, lost=lost, exit_code=code, stop_requested=r, hard_fault=h, signal_error=s
            )
            if not w or lost or code is None:
                assert result is None
            elif h:
                assert result == "crashed"
            elif r:
                assert result == "stopped"
            elif s or code != 0:
                assert result == "crashed"
            else:
                assert result == "clean"


@pytest.mark.parametrize(
    "field,value",
    [
        ("exited", 1),
        ("lost", None),
        ("hard_fault", "yes"),
        ("signal_error", 0),
        ("stop_requested", 1),
        ("exit_code", True),
        ("exit_code", 2**31),
        ("exit_code", -(2**31) - 1),
    ],
)
def test_classifier_invalid_inputs(field, value):
    values = dict(
        exited=True,
        lost=False,
        exit_code=0,
        stop_requested=False,
        hard_fault=False,
        signal_error=False,
    )
    values[field] = value
    reject("runtime_unavailable", lambda: module("_guardian")._closed_kind(**values))


@pytest.mark.parametrize(
    "error,name", [(errno.EPERM, "eperm"), (errno.ESRCH, "esrch"), (errno.EINTR, "eintr")]
)
@pytest.mark.parametrize("at_kill", [False, True])
def test_signal_issue_sticky_but_confirmed_stop_not_crash(monkeypatch, error, name, at_kill):
    child, calls = owned(monkeypatch, waits=[(0, 0), (321, 74 << 8)])
    if at_kill:
        child._poll(1, stop=True)

    def fail(pid, sig):
        calls.append(("signal", pid, sig))
        raise OSError(error, "private-sentinel")

    monkeypatch.setattr(module("_ownership").os, "killpg", fail)
    child._poll(2_000_000_001 if at_kill else 1, stop=True)
    assert child.signal_error and child.fault and not child.hard_fault
    assert child.signal_errno == name
    assert classify(child) is None
    child._poll(3_000_000_001, force=True)
    assert child.exited and child.exit_code == 74 and child.fault
    assert classify(child) == "stopped"
    assert classify(child, stop=False) == "crashed"
    assert classify(child, hard=True) == "crashed"
    count = len(calls)
    child._poll(9_000_000_001, force=True)
    assert len(calls) == count
    child.close()


@pytest.mark.parametrize("error", [errno.EINVAL, errno.EIO, None])
def test_unexpected_signal_failure_is_hard(monkeypatch, error):
    child, _ = owned(monkeypatch, waits=[(321, 0)])

    def fail(*args):
        raise OSError(error, "private-sentinel")

    monkeypatch.setattr(module("_ownership").os, "killpg", fail)
    child._poll(1, stop=True)
    assert child.signal_error and child.hard_fault and child.fault
    assert child.signal_errno == "unexpected"
    assert classify(child) == "crashed"
    child.close()


def test_signal_same_turn_wait_and_readonly_evidence(monkeypatch):
    child, calls = owned(monkeypatch, signal_error=errno.EPERM, waits=[(321, 0)])
    child._poll(1, stop=True)
    assert classify(child) == "stopped" and child.fault
    for name in (
        "exited",
        "lost",
        "exit_code",
        "fault",
        "signal_error",
        "hard_fault",
        "signal_errno",
    ):
        with pytest.raises(AttributeError):
            setattr(child, name, False)
    child._poll(2, force=True)
    assert [c[0] for c in calls] == ["signal", "wait"]
    child.close()


def test_wait_error_is_not_a_signal_issue(monkeypatch):
    child, _ = owned(
        monkeypatch, events=[[exit_event()]], waits=[OSError(errno.EINTR, "private-sentinel")]
    )
    child._poll(1, stop=True)
    assert child.lost and child.hard_fault and not child.signal_error
    assert classify(child) is None
    child.close()


# Test-only standalone entry; request/reply bytes and secrets never enter the script.
WRAPPER = r"""
import errno, json, os, sys
from pathlib import Path
sys.path.insert(0, SOURCE_ROOT)
from ara.docx_analysis_worker.macos import _guardian as g, _ownership as o
from ara.docx_analysis_worker.macos._bootstrap import TokenReader as OriginalToken
from ara.docx_analysis_worker.wire import WireBinding, encode_message
from uuid import UUID
args=sys.argv[1:]
control=int(args[5])
facts={'signals':0,'zero_waits':0,'terminals':0}
state={'phase':False,'injected':False}
real_read=os.read
real_wait=os.waitpid
stop=encode_message(WireBinding(UUID(args[0]),UUID(args[1])),kind='stop',seq=1,
                    values={'reason':'user'})
def read(fd,size):
    if fd==control and state['phase'] and not state['injected']:
        state['injected']=True
        return stop
    return real_read(fd,size)
g.os.read=read
class Token(OriginalToken):
    def feed(self,data):
        if CASE=='prefix':
            super().feed(data[:4]);state['phase']=True
        elif CASE=='bad':
            state['phase']=True;super().feed(b'X')
        else:
            super().feed(data)
    def finish(self):
        super().finish()
        if CASE=='prepared':state['phase']=True
g.TokenReader=Token
if CASE=='before':
    real_spawn=g.subprocess.Popen
    def spawn(*a,**k):
        result=real_spawn(*a,**k);state['phase']=True;return result
    g.subprocess.Popen=spawn
if CASE=='signal':
    o.OwnedChild._observe=lambda self:False
    def signal_group(pid,number):
        facts['signals']+=1
        raise OSError(errno.EPERM,'synthetic')
    def wait(pid,flags):
        if facts['zero_waits']<2:
            facts['zero_waits']+=1;return 0,0
        result=real_wait(pid,flags)
        if result[0]:facts['terminals']+=1
        return result
    o.os.killpg=signal_group
    o.os.waitpid=wait
result=g.main(args)
Path(REPORT_PATH).write_text(json.dumps(facts))
sys.exit(result)
"""


@pytest.mark.parametrize("case", ["signal", "before", "prefix", "prepared", "bad"])
def test_real_guardian_finalization_with_scripted_boundaries(native, root, monkeypatch, case):
    entry, report = root.parent / "probe.py", root.parent / "metadata.json"
    script = (
        "SOURCE_ROOT="
        + repr(str(Path(__file__).resolve().parents[2] / "src"))
        + "\nREPORT_PATH="
        + repr(str(report))
        + "\nCASE="
        + repr(case)
        + "\n"
        + WRAPPER
    )
    entry.write_text(script)
    monkeypatch.setattr(module("_launch"), "ENTRY", entry)
    if case == "signal":
        _, _, status, code = exercise(root, "wait", "stop")
        facts = json.loads(report.read_text())
        assert facts == dict(signals=1, zero_waits=2, terminals=1)
    else:
        armed, _, status, code = exercise(root)
        assert armed == b""
    assert code == 0 and status.values["cleanup_confirmed"]
    assert status.values["exit_kind"] == ("crashed" if case == "bad" else "stopped")


def test_native_stop_repeated_twenty_times(native, root):
    for _ in range(20):
        _, _, status, code = exercise(root, "wait", "stop")
        assert code == 0 and status.values["exit_kind"] == "stopped"
        assert status.values["cleanup_confirmed"]
