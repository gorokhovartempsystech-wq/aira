"""Strong retention across native create; no reconstructed PID authority."""

import os
import threading

from ._errors import LocalResource, WindowsRuntimeError
from ._handles import OwnedHandle, valid_handle

_REGISTRY = {}
_MUTEX, _SPAWN = threading.Lock(), threading.Lock()


class SpawnRecord(LocalResource):
    def __init__(self, api, job):
        job.handle()
        self.api, self.job, self._pid = api, job, os.getpid()
        self._thread, self._process, self._primary, self._storage = None, None, None, None
        self.creation, self.in_flight, self.fault = "not_started", False, False
        self.member, self._resumed, self._exact_kill = False, False, False
        self.exited, self.exit_code, self._closed = False, None, False
        self._close_failed = False
        with _MUTEX:
            if _REGISTRY:
                raise WindowsRuntimeError("runtime_busy")
            _REGISTRY[id(self)] = self

    def _check(self):
        if self._pid != os.getpid() or (not self._closed and _REGISTRY.get(id(self)) is not self):
            raise WindowsRuntimeError("invalid_handle")
        current = threading.get_ident()
        if self._thread is None:
            self._thread = current
        if current != self._thread:
            raise WindowsRuntimeError("invalid_handle")

    def capture(self, ok, process, thread):
        self._check()
        if (
            not self.in_flight
            or self.creation not in ("not_started", "unknown")
            or type(ok) is not bool
        ):
            raise WindowsRuntimeError("invalid_handle")
        if not ok:
            self.creation = "failed"
        elif valid_handle(process) and valid_handle(thread) and process != thread:
            self._process, self._primary = (
                OwnedHandle(self.api, process),
                OwnedHandle(self.api, thread),
            )
            self.creation = "created"
        else:
            self.creation, self.fault = "unknown", True

    def create(self, config, roles, stdio):
        self._check()
        if self.creation != "not_started" or self._closed:
            raise WindowsRuntimeError("invalid_handle")
        temporary = []
        with _SPAWN:
            try:
                mapping = {}
                if len(set(roles.values())) != len(roles) or not set(stdio) <= roles.keys():
                    raise ValueError()
                for role, handle in roles.items():
                    duplicate = self.api.duplicate_rights(
                        handle, 0x100000 if role in ("ordinary", "hard") else None
                    )
                    temporary.append(duplicate)
                    mapping[role] = duplicate.value
                # Fixed entry argv receives duplicate values, not the parent's originals.
                launch = config(mapping) if callable(config) else config
                self.in_flight = True
                self.api.launch(
                    self,
                    launch,
                    self.job.handle(),
                    tuple(mapping.values()),
                    tuple(mapping[r] for r in stdio),
                )
                if self.creation == "not_started":
                    self.creation = "unknown"
                if self.creation != "created":
                    raise ValueError()
                self.member = self.api.in_job(self._process.value, self.job.handle()) is True
                if not self.member:
                    raise ValueError()
            except BaseException:
                if self.in_flight and self.creation == "not_started":
                    self.creation = "unknown"
                self.fault = True
                raise WindowsRuntimeError("runtime_unavailable") from None
            finally:
                self.in_flight = False
                for handle in temporary:
                    try:
                        handle.close()
                    except Exception:
                        self.fault = True
                if self.fault and self.creation == "created":
                    self.terminate()
        if self.fault:
            raise WindowsRuntimeError("runtime_unavailable")

    def resume(self, check):
        self._check()
        if self._resumed or self._closed or self.creation != "created" or self.fault:
            raise WindowsRuntimeError("invalid_handle")
        self._resumed = True
        try:
            if not check():
                self.terminate()
                raise WindowsRuntimeError("runtime_busy")
            if self.api.resume(self._primary.value) != 1:
                raise ValueError()
        except WindowsRuntimeError as exc:
            if exc.code != "runtime_busy":
                self.fault = True
                self.terminate()
            raise WindowsRuntimeError("runtime_unavailable") from None
        except Exception:
            self.fault = True
            self.terminate()
            raise WindowsRuntimeError("runtime_unavailable") from None
        finally:
            self._close_primary()
        if self.fault:
            self.terminate()
            raise WindowsRuntimeError("runtime_unavailable")

    def _close_primary(self):
        if self._primary is not None:
            handle, self._primary = self._primary, None
            try:
                handle.close()
            except Exception:
                self.fault = self._close_failed = True

    def terminate(self):
        self._check()
        if self.in_flight:
            raise WindowsRuntimeError("runtime_busy")
        if self._closed or self.creation in ("not_started", "failed"):
            return
        try:
            self.job.terminate()
        except Exception:
            self.fault = True
        if (
            self._process is not None
            and not self.member
            and not self._exact_kill
            and not self.exited
        ):
            self._exact_kill = True
            try:
                self.api.terminate_process(self._process.value)
            except Exception:
                self.fault = True
        self._close_primary()

    def poll(self):
        self._check()
        if self._closed or self.exited or self._process is None:
            return
        try:
            code = self.api.process_exit(self._process.value)
            if code is not None:
                if type(code) is not int or not 0 <= code < 2**32:
                    raise ValueError()
                self.exited, self.exit_code = True, code if code < 2**31 else code - 2**32
        except Exception:
            self.fault = True
            raise WindowsRuntimeError("runtime_unavailable") from None

    def close(self):
        self._check()
        if self._closed:
            return True
        if self.in_flight or self.creation == "unknown" or self._close_failed:
            return False
        if self.creation == "created" and not self.exited:
            return False
        if self.job.active_count() != 0:
            return False
        self._close_primary()
        if self._process is not None:
            handle, self._process = self._process, None
            try:
                handle.close()
            except Exception:
                self.fault = self._close_failed = True
                return False
        self._closed = True
        with _MUTEX:
            _REGISTRY.pop(id(self), None)
        return True
