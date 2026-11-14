"""Minimal child barrier with a separately owned cooperative gate watcher."""

import os
import threading

from ..wire import StreamDecoder
from ._bootstrap import TOKENS, TokenReader
from ._clock import WindowsClock
from ._guardian import Lane, close_owned, wait_turn


def run(api, inherited, binding, deadline, lease, mode):
    clock = WindowsClock()
    started, allowed, quit_watch, failed = (threading.Event() for _ in range(4))
    request_lane, output = Lane(inherited["request"]), Lane(inherited["events"])
    prepared = Lane(inherited["prepared"])
    thread = None
    try:
        if mode == "early_exit":
            return 0
        if clock.now_ns() >= min(deadline, lease):
            return 74

        def watch():
            gate = Lane(inherited["gate"])
            reader = TokenReader("gate", eof_required=False)
            own_clock = WindowsClock()
            try:
                # Establish ownership without discarding an immediate read completion.
                gate.operation = gate.endpoint.begin_read()
                started.set()
                while not quit_watch.is_set():
                    if not allowed.is_set() and own_clock.now_ns() >= min(deadline, lease):
                        os._exit(74)
                    result = gate.step()
                    if result is not None:
                        if result.eof:
                            os._exit(74)
                        reader.feed(result.data)
                        if reader.ready:
                            allowed.set()
                    wait_turn(api, [gate])
            except BaseException:
                failed.set()
                if not quit_watch.is_set():
                    os._exit(74)
            finally:
                try:
                    if not close_owned(
                        api, [gate.endpoint], own_clock, own_clock.now_ns() + 2_000_000_000
                    ):
                        failed.set()
                except BaseException:
                    failed.set()

        thread = threading.Thread(target=watch, name="aira-fixture-gate")
        thread.start()
        while not started.wait(0.05):
            if clock.now_ns() >= min(deadline, lease) or failed.is_set():
                return 75
        if mode != "prepared_missing":
            prepared.queue(TOKENS["prepared"] + (b"!" if mode == "prepared_extra" else b""))
            while not prepared.idle:
                if clock.now_ns() >= min(deadline, lease):
                    return 74
                prepared.step()
                if not prepared.idle:
                    wait_turn(api, [prepared])
        if not prepared.close():
            return 75
        while not allowed.wait(0.05):
            if clock.now_ns() >= min(deadline, lease) or failed.is_set():
                return 74
        if mode == "protected_model":
            from ara.model_protection.private_bootstrap import ProtectedRequestDecoder

            decoder = ProtectedRequestDecoder(binding)
        else:
            decoder = StreamDecoder(binding, lane="request")
        request = None
        while True:
            if clock.now_ns() >= deadline or failed.is_set():
                return 74
            result = request_lane.step()
            if result is not None:
                if result.eof:
                    decoder.finish()
                    break
                for message in decoder.feed(result.data):
                    request = message
            wait_turn(api, [request_lane])
        if request is None:
            return 75

        def emit(raw):
            for offset in range(0, len(raw), 65536):
                output.queue(raw[offset : offset + 65536])
                while not output.idle:
                    if clock.now_ns() >= deadline or failed.is_set():
                        raise ValueError()
                    output.step()
                    if not output.idle:
                        wait_turn(api, [output])

        from ._fixture_child import run_fixture

        code = run_fixture(
            api,
            binding,
            request,
            mode,
            emit,
            inherited["diagnostics"].handle(),
            **({"model_key": decoder.take_key()} if mode == "protected_model" else {}),
        )
        quit_watch.set()
        thread.join(2)
        if thread.is_alive() or failed.is_set():
            return 75
        main_resources = [r for n, r in inherited.items() if n != "gate"]
        return (
            code if close_owned(api, main_resources, clock, clock.now_ns() + 2_000_000_000) else 75
        )
    except BaseException:
        return 75
    finally:
        quit_watch.set()
        if thread is not None:
            thread.join(2)
