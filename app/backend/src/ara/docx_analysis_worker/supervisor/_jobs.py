"""One permanent worker, one job and one retained result; waits do not free capacity."""

from dataclasses import dataclass, field
from threading import Condition, Event, Thread

from ara.documents.storage import DocumentError

from ._runtime_models import SupervisorError
from .sql_models import SupervisorStorageError

_SAFE_CODES = frozenset(
    (
        "validation_error invalid_handle not_ready busy queue_full "
        "storage_unavailable storage_error "
        "clock_error runtime_unavailable recovery_required shutdown_pending internal_error "
        "storage_conflict queue_overflow not_found idempotency_conflict saved_target_conflict "
        "analysis_in_progress analysis_queue_full analysis_deadline_exceeded analysis_clock_error "
        "analysis_history_exhausted unsupported_analysis_content "
        "empty_document analysis_limit_exceeded "
        "publication_in_progress publication_conflict"
    ).split()
)


@dataclass(frozen=True, slots=True)
class Result:
    generation: object
    value: object = field(default=None, repr=False)
    error: str | None = None
    status: int | None = None


class Lane:
    def __init__(self, name, wake):
        self.name, self.wake = name, wake
        self.cv, self.ready = Condition(), Event()
        self.thread = Thread(target=self._run, name="aira-supervisor-" + name, daemon=True)
        self._job = self._result = None
        self._running = self._closing = self._started = self.uncertain = False

    def start(self):
        with self.cv:
            if self._started:
                raise SupervisorError("busy")
            self._started = True
        try:
            self.thread.start()
        except BaseException:
            self.uncertain = True
            raise SupervisorError("runtime_unavailable") from None

    @property
    def busy(self):
        with self.cv:
            return self._job is not None or self._running or self._result is not None

    def submit(self, generation, fn):
        with self.cv:
            if self._closing or self.uncertain or self.busy:
                raise SupervisorError("busy")
            self._job = generation, fn
            self.cv.notify_all()

    def take(self):
        with self.cv:
            result, self._result = self._result, None
            return result

    def close(self):
        with self.cv:
            self._closing = True
            self.cv.notify_all()

    def _run(self):
        self.ready.set()
        while True:
            with self.cv:
                self.cv.wait_for(lambda: self._job is not None or self._closing)
                if self._job is None:
                    return
                generation, fn = self._job
                self._job, self._running = None, True
            try:
                result = Result(generation, fn())
            except (DocumentError, SupervisorStorageError, SupervisorError) as error:
                code = error.code if error.code in _SAFE_CODES else "storage_error"
                result = Result(generation, error=code, status=getattr(error, "status", None))
            except BaseException:
                result = Result(generation, error="internal_error")
            finally:
                fn = None
            with self.cv:
                self._running, self._result = False, result
            self.wake.set()
