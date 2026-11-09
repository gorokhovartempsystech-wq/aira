from types import SimpleNamespace as NS

from ara.docx_analysis_worker.supervisor._attempt import result
from ara.docx_analysis_worker.supervisor.platform import NativeObservation


def entry(reason=None):
    view = NS(last_ns=100, phase="open", stop_requested=False)
    dispatcher = NS(step=lambda: NS(control=view))
    return NS(
        physical=False,
        candidate=None,
        reason=reason,
        intent=None,
        budget=NS(last_ns=0, deadline_ns=1000),
        native_lease=500,
        dispatcher=dispatcher,
    )


def observe(e, payload=None):
    value = NativeObservation("analyzing", None, True, payload, 90 if payload else None)
    result(None, "observe", e, NS(error=None, value=value))


def test_exit_before_last_pipe_bytes_does_not_discard_result():
    e = entry()
    observe(e)
    assert e.physical and not e.need_close
    observe(e, b"verified reply")
    assert e.candidate == b"verified reply" and e.need_close


def test_stop_does_not_wait_for_late_result():
    e = entry("user")
    observe(e, b"late result")
    assert e.need_close and e.candidate is None


def test_queued_renewal_keeps_its_bound_after_exit_observation():
    from ara.docx_analysis_worker.supervisor._attempt import native

    e = entry()
    attempt = object()
    e.native, e.closed, e.renew_bound = attempt, False, 800
    jobs = []
    calls = []

    def renew(worker, bound):
        calls.append((worker, bound))
        return True

    coordinator = NS(
        s=NS(_platform=NS(renew=renew)),
        sample=lambda: 100,
        busy=lambda entry, lane: lane == "lifecycle",
        submit=lambda lane, tag, job, entry: jobs.append(job),
    )
    native(coordinator, e)
    observe(e)
    assert e.renew_bound is None
    job, = jobs
    result(coordinator, "renew", e, NS(error=None, value=job()))
    assert calls == [(attempt, 800)]
    assert e.native_lease == 800
