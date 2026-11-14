"""Per-process launch admission with one bounded in-flight daemon worker."""

import hashlib
import math
import os
import re
import secrets
import sys
import threading
import time

from .. import LicenseError, StartRequest, authorize_start, normalize_key, require_access
from ._identity import read_device_id
from ._models import ActivationIdentity, ClientError, Snapshot, checked_identity, fail
from ._transport import HttpsTransport

_LIMIT = 15_000_000_000
_UNCERTAIN = set()


def _default_clock():
    if sys.platform == "darwin":
        from ara.docx_analysis_worker.macos import DarwinClock

        return DarwinClock()
    if sys.platform == "win32":
        from ara.docx_analysis_worker.windows import WindowsClock

        return WindowsClock()
    return None


class LicenseClient:
    def __init__(
        self, origin, store, *, device_provider=None, clock=None, transport=None, model_access=None
    ):
        default_transport = HttpsTransport(origin)
        self._store = store
        self._model_access, self._model_key = model_access, None
        self._device = read_device_id if device_provider is None else device_provider
        self._clock = _default_clock() if clock is None else clock
        self._transport = default_transport if transport is None else transport
        self._pid = os.getpid()
        self._lock = threading.Lock()
        self._thread = None
        self._launch_pending = self._launch_unknown = self._thread_started = False
        self._launch_done = threading.Event()
        self._launch_done.set()
        self._intent = None
        self._started = self._last = None
        self._clock_failed = False
        self._cancelled = False
        self._phase, self._error, self._permit = "new", None, None

    def _owner(self):
        if not hasattr(self, "_pid") or self._pid != os.getpid():
            fail("invalid_handle")

    def __copy__(self):
        fail("invalid_handle")

    def __deepcopy__(self, memo):
        fail("invalid_handle")

    def __reduce_ex__(self, protocol):
        fail("invalid_handle")

    def _now_locked(self):
        try:
            if self._clock_failed:
                fail("clock_unavailable")
            value = self._clock.now_ns()
            if (
                type(value) is not int
                or not 0 <= value < 2**63
                or (self._last is not None and value < self._last)
            ):
                fail("clock_unavailable")
            self._last = value
            return value
        except Exception:
            self._clock_failed = True
            fail("clock_unavailable")

    def _failed_locked(self, code):
        self._permit = None
        self._model_key = None
        self._phase = "expired" if code == "license_expired" else "failed"
        self._error = code
        self._cancelled = True

    def _refresh_locked(self):
        if self._phase not in {"checking", "active"}:
            return
        try:
            now = self._now_locked()
            if self._phase == "checking" and now - self._started > _LIMIT:
                fail("verification_timeout")
            if self._permit is not None:
                require_access(self._permit, now_ns=now)
        except (ClientError, LicenseError) as exc:
            self._failed_locked(exc.code)

    def _snapshot_locked(self):
        pending = self._pending_locked()
        permit = self._permit
        return Snapshot(
            self._phase,
            self._error,
            permit.license_id if permit else None,
            permit.expires_at_ms if permit else None,
            not pending and self._phase != "closed",
        )

    def view(self):
        self._owner()
        with self._lock:
            self._refresh_locked()
            return self._snapshot_locked()

    def require_active(self):
        self._owner()
        with self._lock:
            self._refresh_locked()
            if self._phase == "expired":
                fail("license_expired")
            if self._phase != "active" or self._permit is None:
                fail("access_denied")
            return self._permit

    def require_model_key(self):
        self._owner()
        with self._lock:
            self._refresh_locked()
            if self._phase != "active" or self._permit is None:
                fail("access_denied")
            require_access(self._permit, now_ns=self._last)
            if type(self._model_key) is not bytes or len(self._model_key) != 32:
                fail("model_access_unavailable")
            return self._model_key

    def start(self, key=None):
        self._owner()
        try:
            key = normalize_key(key) if key is not None else None
        except LicenseError as exc:
            fail(exc.code)
        intent = hashlib.sha256(key.encode("ascii")).digest() if key is not None else None
        # Lazy native clock initialization outside the state mutex; no file/network work.
        try:
            self._clock.now_ns()
        except Exception:
            pass
        with self._lock:
            self._refresh_locked()
            if self._phase == "closed":
                fail("client_closed")
            if self._pending_locked():
                if not self._cancelled and intent == self._intent:
                    return self._snapshot_locked()
                fail("client_busy")
            self._permit, self._error = None, None
            self._model_key = None
            self._cancelled = False
            try:
                self._started = self._now_locked()
            except ClientError as exc:
                self._failed_locked(exc.code)
                return self._snapshot_locked()
            self._phase, self._intent = "checking", intent
            self._launch_pending, self._thread_started = True, False
            self._launch_done.clear()
        # A pending launch owns the intent even before a Thread object is issued.
        # The worker must not touch the store until start has acknowledged success.
        try:
            thread = threading.Thread(
                target=self._work, args=(key,), name="aira-license-check", daemon=True
            )
            with self._lock:
                self._thread = thread
            thread.start()
        except BaseException:
            with self._lock:
                self._launch_unknown = True
                _UNCERTAIN.add(self)
                if self._phase != "closed":
                    self._failed_locked("client_error")
        else:
            with self._lock:
                self._thread_started = True
        finally:
            with self._lock:
                self._launch_pending = False
                self._launch_done.set()
        with self._lock:
            return self._snapshot_locked()

    def _checkpoint(self):
        self._owner()
        with self._lock:
            self._refresh_locked()
            if self._cancelled or self._phase != "checking":
                fail(self._error or "client_closed")
            return self._last

    def _work(self, key):
        self._launch_done.wait()
        try:
            self._checkpoint()
            try:
                device = self._device()
                if type(device) is not str or not re.fullmatch(r"dv1-[0-9a-f]{64}", device):
                    fail("device_unavailable")
            except Exception:
                fail("device_unavailable")
            self._checkpoint()
            identity = None
            if key is None:
                try:
                    identity = self._store.load()
                    if identity is not None:
                        identity = checked_identity(identity, "activation_store_error")
                except Exception:
                    fail("activation_store_error")
                self._checkpoint()
                if identity is None:
                    with self._lock:
                        if self._phase == "checking" and not self._cancelled:
                            self._phase = "activation_required"
                    return
                if identity.device_id != device:
                    fail("device_mismatch")
            nonce = secrets.token_bytes(32).hex()
            request = (
                StartRequest("activate", device, nonce, license_key=key)
                if key is not None
                else StartRequest("check", device, nonce, license_id=identity.license_id)
            )
            self._checkpoint()
            try:
                data = self._transport.execute(request, self._checkpoint)
            except (ClientError, LicenseError):
                raise
            except Exception:
                fail("network_unavailable")
            received = self._checkpoint()
            permit = authorize_start(request, data, started_ns=self._started, received_ns=received)
            model_key = None
            if self._model_access is not None:
                from ara.model_protection.access_wire import AccessError

                try:
                    model_key = self._model_access.unlock(
                        permit, device_id=device, license_key=key, checkpoint=self._checkpoint
                    )
                    if type(model_key) is not bytes or len(model_key) != 32:
                        fail("model_access_unavailable")
                except AccessError as error:
                    if error.code == "enrollment_required":
                        with self._lock:
                            self._refresh_locked()
                            if self._phase == "checking" and not self._cancelled:
                                self._phase = "activation_required"
                        return
                    fail("model_access_unavailable")
            if key is not None:
                self._checkpoint()
                try:
                    self._store.save(ActivationIdentity(permit.license_id, device))
                except Exception:
                    fail("activation_store_error")
            self._checkpoint()
            with self._lock:
                self._refresh_locked()
                if self._phase == "checking" and not self._cancelled:
                    require_access(permit, now_ns=self._last)
                    self._model_key = model_key
                    self._permit, self._phase, self._error = permit, "active", None
        except Exception as exc:
            code = exc.code if isinstance(exc, (ClientError, LicenseError)) else "client_error"
            code = ClientError(code).code
            with self._lock:
                if self._phase == "checking" and not self._cancelled:
                    self._failed_locked(code)
        finally:
            with self._lock:
                self._intent = None

    def close(self):
        self._owner()
        with self._lock:
            self._cancelled = True
            self._model_key = None
            self._permit, self._phase, self._error = None, "closed", None

    def _pending_locked(self):
        return (
            self._launch_pending
            or self._launch_unknown
            or (self._thread_started and self._thread is not None and self._thread.is_alive())
        )

    def resources_pending(self):
        self._owner()
        with self._lock:
            return bool(self._pending_locked())

    def shutdown(self, timeout=5):
        self._owner()
        if not (type(timeout) in (int, float) and 0 <= timeout <= 5 and math.isfinite(timeout)):
            fail("validation_error")
        end = time.monotonic() + timeout
        self.close()
        self._launch_done.wait(max(0, end - time.monotonic()))
        with self._lock:
            if self._launch_pending or self._launch_unknown:
                return False
            thread = self._thread if self._thread_started else None
        if thread is not None:
            if thread is threading.current_thread():
                return False
            thread.join(max(0, end - time.monotonic()))
        return not self.resources_pending()
