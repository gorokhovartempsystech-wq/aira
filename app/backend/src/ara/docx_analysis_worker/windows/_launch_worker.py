"""The only E3 launch/process/cleanup owner. No payload decoding here."""


def run(state):
    with state.cv:
        while state.gate is None:
            state.cv.wait(0.05)
        admitted = state.gate
    try:
        if admitted:
            state.tick()
            state.holder.start()
            channels = state.holder.channels
            with state.cv:
                state.handoff = channels
                state.cv.notify_all()
        else:
            with state.cv:
                state.handoff = "failed"
                state.frame = None
                state.cv.notify_all()
    except Exception:
        with state.cv:
            stopped = state.stopped
            state.handoff, state.frame = "failed", None
            state.cv.notify_all()
        if not stopped:
            state.stop("process", True)
    while True:
        state.tick()
        try:
            observation = state.holder.poll_process()
            with state.cv:
                state.observation = observation
                can_close = state.handoff == "failed" or all(state.quiescent.values())
            if (
                observation.hard_fault
                or (observation.process_exited and observation.exit_code != 0)
                or observation.creation == "unknown"
            ):
                state.stop("process", True)
            if can_close and state.holder.finish_close():
                with state.cv:
                    state.resources_closed = True
                    state.frame = None
                    state.cv.notify_all()
                return
        except Exception:
            state.stop("process", True)
            with state.cv:
                state.blocked = True
        state.pause(0.05)
