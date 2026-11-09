"""Closed writes stay errors; only renewal can defer to the bounded data reader."""

from threading import Condition
from types import SimpleNamespace
from uuid import UUID

import pytest
from test_docx_analysis_windows_io import io as io
from test_docx_analysis_windows_io import pair

from ara.docx_analysis_worker.windows._control_writer import Writer
from ara.docx_analysis_worker.windows._errors import ClosedPipeError, WindowsRuntimeError
from ara.docx_analysis_worker.wire import WireBinding


def close_write(io, status, completion, monkeypatch):
    if completion:
        monkeypatch.setattr(io, "result", lambda *args: (status, 0))
    else:
        io.submission = status


@pytest.mark.parametrize("status", [109, 232, 233])
@pytest.mark.parametrize("completion", [False, True])
def test_closed_write_reports_error_and_releases_native_resources(
    io, monkeypatch, status, completion
):
    pipes = pair(io)
    close_write(io, status, completion, monkeypatch)
    try:
        with pytest.raises(ClosedPipeError, match="runtime_unavailable"):
            pipes.writer.begin_write(b"payload").poll()
        assert pipes.writer._operation is None
        assert pipes.writer.close()
        assert pipes.reader.close()
        assert not io.live
    finally:
        pipes.writer.close()
        pipes.reader.close()


@pytest.mark.parametrize("status", [109, 232, 233, 5])
@pytest.mark.parametrize("completion", [False, True])
@pytest.mark.parametrize("renewal", [False, True])
def test_only_closed_renewal_defers_to_data_reader(io, monkeypatch, status, completion, renewal):
    pipes = pair(io)
    close_write(io, status, completion, monkeypatch)
    stopped = []
    state = SimpleNamespace(
        binding=WireBinding(UUID(int=1), UUID(int=2)),
        deadline=20_000_000_000,
        lease=10_000_000_000,
        tick=lambda: 1_000_000_000,
        cv=Condition(),
        stopped=False,
        closing=False,
        natural=False,
        control_eof=False,
        permit_ready=False,
        stop=lambda *args: stopped.append(args),
    )
    command = SimpleNamespace(outcome="pending", receipt=False) if renewal else None
    try:
        writer = Writer(state, pipes.writer)
        if status == 5:
            with pytest.raises(WindowsRuntimeError):
                writer.send(12_000_000_000, state.lease, command)
            assert not state.control_eof
        else:
            assert writer.send(12_000_000_000, state.lease, command) is False
            assert state.control_eof is renewal
            assert stopped == ([] if renewal else [("transport", True)])
            if renewal:
                assert command.outcome == "rejected"
        assert not state.permit_ready
        assert state.lease == 10_000_000_000
        if renewal:
            assert not command.receipt
    finally:
        assert pipes.writer.close()
        assert pipes.reader.close()
        assert not io.live
