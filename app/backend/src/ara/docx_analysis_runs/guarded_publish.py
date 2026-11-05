"""Atomic SQL publication coordinated with one owned local publication permit."""

from contextlib import contextmanager
from dataclasses import fields
from threading import Lock

from sqlalchemy import Engine, select, text

from ara.docx_analysis.storage_codec import StorageCodecError, capture_result
from ara.docx_analysis.storage_codec._records import LOWER_ERRORS
from ara.docx_analysis_worker.control import AttemptIdentity, CommitPermit, ControlView
from ara.docx_analysis_worker.control._models import Uncopyable
from ara.models import DocxAnalysisAttempt as Attempt
from ara.models import DocxAnalysisResult as Result

from . import _lifecycle as life
from . import _storage
from ._lifecycle_models import WorkerUpdate
from ._lifecycle_storage import locked, same_source, state, transaction
from .guarded_port import PublicationPort, publication_fail


class GuardedPublisher(Uncopyable):
    def __init__(self, engine, claim, *, port, limits=None):
        if not isinstance(engine, Engine) or not isinstance(port, PublicationPort):
            _storage.fail("validation_error", 422)
        life.valid_claim(claim)
        self._engine, self._claim, self._port = engine, claim, port
        self._limits = life.limits_checked(limits)
        self._identity = AttemptIdentity(
            claim.run_id, claim.attempt_id, claim.worker_instance_id, claim.claim_fence
        )
        self._document_id = claim.document_id
        self._check_port()
        self._pending, self._reply, self._expected = None, None, None
        self._needs_cancel = False
        self._lock = Lock()

    def __repr__(self):
        return "<GuardedPublisher>"

    def _check_port(self):
        value = self._port.view()
        current = AttemptIdentity(
            self._claim.run_id,
            self._claim.attempt_id,
            self._claim.worker_instance_id,
            self._claim.claim_fence,
        )
        if (
            type(value) is not ControlView
            or type(value.identity) is not AttemptIdentity
            or value.identity != self._identity
            or current != self._identity
            or self._claim.document_id != self._document_id
        ):
            _storage.fail("validation_error", 422)
        return value

    @contextmanager
    def _operation(self):
        from ara.documents.storage import DocumentError

        if not self._lock.acquire(blocking=False):
            publication_fail("publication_in_progress")
        try:
            life.valid_claim(self._claim)
            self._check_port()
            yield
        except Exception as error:
            if self._pending is not None:
                try:
                    self._port.settle(self._pending, outcome="unknown")
                except Exception:
                    pass  # Retain the permit even if the dispatcher/clock is unavailable.
            if isinstance(error, DocumentError):
                raise error from None
            try:
                _storage.fail("storage_error")
            except DocumentError as sanitized:
                raise sanitized from None
        finally:
            self._lock.release()

    def complete(self, *, reply):
        if type(reply) is not bytes:
            _storage.fail("validation_error", 422)
        if len(reply) > self._limits.review.max_reply_bytes:
            _storage.fail("analysis_limit_exceeded", 422)
        with self._operation():
            if self._reply is not None and reply != self._reply:
                publication_fail("publication_conflict")
            if self._pending is not None or self._needs_cancel:
                previous = self._reconcile()
                if previous.accepted or previous.state.summary.status != "running":
                    return previous
            records, denied = self._records()
            if denied is not None:
                return denied
            source, attempt, prior = records
            if prior is not None:
                return life._replay(
                    self._engine,
                    self._claim,
                    source,
                    attempt,
                    prior,
                    self._limits,
                    expected=self._expected,
                    reply=reply,
                )
            try:
                result = capture_result(source, attempt, reply=reply, limits=self._limits)
            except (*LOWER_ERRORS, StorageCodecError) as error:
                code = "analysis_limit_exceeded" if "limit" in error.code else "invalid_result"
                out = life.fail_attempt(self._engine, self._claim, error_code=code)
                return WorkerUpdate(False, out.state)
            out = self._publish(source, attempt, result, reply)
            if self._pending is not None:
                self._port.settle(self._pending, outcome="committed")
                self._pending = None
            return out

    def _records(self):
        from ara.documents.storage import DocumentError

        try:
            return life.load_records(self._engine, self._claim, self._limits)
        except DocumentError as error:
            if error.status == 503:
                raise
            with transaction(self._engine) as session:
                run, _, _ = locked(session, self._claim.document_id, self._claim.run_id)
                if run.status == "succeeded":
                    raise error
            code = (
                "analysis_limit_exceeded"
                if error.code == "analysis_limit_exceeded"
                else "source_corrupt"
            )
            out = life.fail_attempt(self._engine, self._claim, error_code=code)
            return None, WorkerUpdate(False, out.state)

    def _publish(self, source, attempt, result, reply):
        c = self._claim
        with transaction(self._engine) as session:
            run, a, scope = locked(session, c.document_id, c.run_id)
            if not life.match(run, a, c):
                return WorkerUpdate(False, state(run))
            life.expire(run, scope, life.clock(session))
            if run.status == "succeeded":
                stored = session.scalar(select(Result).where(Result.run_id == run.id))
                if stored is not None and stored.reply_data != reply:
                    return WorkerUpdate(False, state(run))
                if not (
                    stored is not None
                    and run.result_sha256 == result.result_sha256
                    and all(
                        getattr(stored, f.name) == getattr(result, f.name) for f in fields(result)
                    )
                    and same_source(session, run, source)
                    and a.request_sha256 == attempt.request_sha256
                    and session.scalar(select(Attempt.request_data).where(Attempt.id == a.id))
                    == attempt.request_data
                ):
                    _storage.fail("storage_error")
                return WorkerUpdate(True, state(run), True)
            if run.status != "running" or run.fence != 1:
                return WorkerUpdate(False, state(run))
            if not (
                same_source(session, run, source)
                and a.request_sha256 == attempt.request_sha256
                and session.scalar(select(Attempt.request_data).where(Attempt.id == a.id))
                == attempt.request_data
            ):
                life.terminal(run, "failed", "source_corrupt", life.clock(session))
                return WorkerUpdate(False, state(run))
            now = life.clock(session)
            if life.expire(run, scope, now):
                return WorkerUpdate(False, state(run))
            self._check_port()
            permit = self._port.reserve()
            if permit is None:
                return WorkerUpdate(False, state(run))
            if type(permit) is not CommitPermit:
                _storage.fail("storage_error")
            self._pending, self._reply, self._expected = permit, reply, result.result_sha256
            session.add(
                Result(
                    run_id=run.id,
                    document_id=run.document_id,
                    attempt_id=a.id,
                    run_status="succeeded",
                    created_at=now,
                    **{f.name: getattr(result, f.name) for f in fields(result)},
                )
            )
            life.terminal(run, "succeeded", None, now)
            run.result_sha256 = result.result_sha256
            session.flush()
            session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            out = WorkerUpdate(True, state(run))
        return out

    def reconcile(self):
        with self._operation():
            return self._reconcile()

    def _reconcile(self):
        c = self._claim
        # This ordered lock is the barrier against the previous uncertain transaction.
        with transaction(self._engine) as session:
            run, a, scope = locked(session, c.document_id, c.run_id)
            if not life.match(run, a, c):
                return WorkerUpdate(False, state(run))
            life.expire(run, scope, life.clock(session))
            if (
                run.status == "running"
                and (self._pending is not None or self._needs_cancel)
                and self._check_port().stop_requested
            ):
                self._cancel(run, life.clock(session))
            out = WorkerUpdate(False, state(run))
        self._needs_cancel = False
        if self._reply is None:
            return out
        if out.state.summary.status == "succeeded":
            records, denied = life.load_records(self._engine, c, self._limits)
            if denied is not None:
                _storage.fail("storage_error")
            source, attempt, result = records
            if result is None:
                _storage.fail("storage_error")
            out = life._replay(
                self._engine,
                c,
                source,
                attempt,
                result,
                self._limits,
                expected=self._expected,
                reply=self._reply,
            )
            if not out.accepted:
                _storage.fail("storage_error")
            outcome = "committed"
        else:
            outcome = (
                "rolled_back"
                if out.state.summary.status in ("running", "cancel_requested")
                else "terminal"
            )
        if self._pending is not None:
            self._port.settle(self._pending, outcome=outcome)
            self._pending = None
            if outcome == "rolled_back" and self._check_port().stop_requested:
                self._needs_cancel = True
                # Stop may have arrived after the first barrier's RAM check.
                with transaction(self._engine) as session:
                    run, a, scope = locked(session, c.document_id, c.run_id)
                    if life.match(run, a, c):
                        now = life.clock(session)
                        life.expire(run, scope, now)
                        if run.status == "running":
                            self._cancel(run, now)
                    out = WorkerUpdate(False, state(run))
                self._needs_cancel = False
        return out

    @staticmethod
    def _cancel(run, now):
        run.status = run.stage = "cancel_requested"
        run.fence = 2
        run.cancel_requested_at = run.updated_at = max(now, run.created_at)
