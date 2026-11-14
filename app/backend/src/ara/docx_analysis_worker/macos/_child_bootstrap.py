"""Minimal admission barrier and supplementary guardian EOF watcher."""

import os
import select
import stat
import threading
from uuid import UUID

from ..wire import StreamDecoder, WireBinding
from ._bootstrap import TOKENS, TokenReader
from ._clock import DarwinClock
from ._launch import MODES


def main(args):
    try:
        run, attempt, deadline, lease, mode, slot, gate, prepared = args
        binding = WireBinding(UUID(run), UUID(attempt))
        if str(binding.run_id) != run or str(binding.attempt_id) != attempt or mode not in MODES:
            return 75
        raw_numbers = (deadline, lease, slot, gate, prepared)
        deadline, lease, slot, gate, prepared = map(int, (deadline, lease, slot, gate, prepared))
        if any(str(int(v)) != v for v in raw_numbers) or not 0 < lease <= deadline <= 2**63 - 1:
            return 75
        if len({slot, gate, prepared}) != 3 or min(slot, gate, prepared) < 3:
            return 75
        info = os.fstat(slot)
        if not (
            stat.S_ISREG(info.st_mode)
            and stat.S_IMODE(info.st_mode) == 0o600
            and info.st_uid == os.geteuid()
            and info.st_size == 0
            and info.st_nlink == 1
        ):
            return 75
        if not all(stat.S_ISFIFO(os.fstat(fd).st_mode) for fd in (0, 1, 2, gate, prepared)):
            return 75
        if mode == "early_exit":
            return 0
        clock = DarwinClock()
        allowed, started = threading.Event(), threading.Event()

        def watch():
            try:
                reader = TokenReader("gate", eof_required=False)
                started.set()
                while True:
                    if not allowed.is_set() and clock.now_ns() >= min(deadline, lease):
                        os._exit(74)
                    if select.select([gate], [], [], 0.1)[0]:
                        data = os.read(gate, 9)
                        if not data:
                            os._exit(74)
                        reader.feed(data)
                        if reader.ready:
                            allowed.set()
            except BaseException:
                os._exit(74)

        thread = threading.Thread(target=watch, daemon=True)
        thread.start()
        started.wait()
        if mode != "prepared_missing":
            os.write(prepared, TOKENS["prepared"] + (b"!" if mode == "prepared_extra" else b""))
        os.close(prepared)
        allowed.wait()
        if mode == "protected_model":
            from ara.model_protection.private_bootstrap import ProtectedRequestDecoder

            decoder = ProtectedRequestDecoder(binding)
        else:
            decoder = StreamDecoder(binding, lane="request")
        request = None
        while True:
            if not select.select([0], [], [], 0.1)[0]:
                continue
            data = os.read(0, 65536)
            if not data:
                decoder.finish()
                break
            for message in decoder.feed(data):
                request = message
        if request is None:
            return 75
        from ._fixture_child import run_fixture

        return (
            run_fixture(binding, request, mode, model_key=decoder.take_key())
            if mode == "protected_model"
            else run_fixture(binding, request, mode)
        )
    except BaseException:
        return 75
