"""Independent limits on worker configuration and public error inputs."""

from dataclasses import FrozenInstanceError
from importlib import import_module

import pytest


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_attempts": 0},
        {"max_attempts": 11},
        {"max_attempts": True},
        {"max_attempts": 3.0},
        {"max_attempts": "3"},
        {"lease_seconds": 0},
        {"lease_seconds": -1},
        {"lease_seconds": 301},
        {"lease_seconds": True},
        {"lease_seconds": "30"},
        {"lease_seconds": float("nan")},
        {"lease_seconds": float("inf")},
        {"run_timeout_seconds": 0},
        {"run_timeout_seconds": 86401},
        {"run_timeout_seconds": False},
        {"run_timeout_seconds": float("nan")},
        {"retry_delay_seconds": -1},
        {"retry_delay_seconds": 301},
        {"retry_delay_seconds": False},
        {"retry_delay_seconds": None},
        {"retry_delay_seconds": float("nan")},
        {"retry_delay_seconds": float("inf")},
    ],
)
def test_worker_settings_reject_unsafe_limits(overrides):
    worker = import_module("ara.worker")
    with pytest.raises(ValueError) as caught:
        worker.WorkerSettings(**overrides)
    assert str(caught.value)


def test_worker_settings_accept_finite_boundaries_and_are_frozen():
    worker = import_module("ara.worker")
    settings = worker.WorkerSettings(
        lease_seconds=0.1, max_attempts=10, run_timeout_seconds=86400, retry_delay_seconds=0
    )
    assert settings.lease_seconds == 0.1
    assert settings.max_attempts == 10
    assert settings.run_timeout_seconds == 86400
    assert settings.retry_delay_seconds == 0
    with pytest.raises(FrozenInstanceError):
        settings.max_attempts = 1
    default = worker.WorkerSettings()
    assert (default.lease_seconds, default.max_attempts) == (30, 3)
    assert (default.run_timeout_seconds, default.retry_delay_seconds) == (900, 1)


@pytest.mark.parametrize("code", ["PRIVATE_EXCEPTION_PAYLOAD", "access_revoked", "", None])
def test_unknown_failure_code_is_rejected_before_any_storage_access(code):
    worker = import_module("ara.worker")

    class NoStorage:
        def __getattr__(self, name):
            raise AssertionError("Invalid failure code must not open storage")

    with pytest.raises(ValueError) as caught:
        worker.fail_attempt(NoStorage(), object(), code=code)
    assert "PRIVATE_EXCEPTION_PAYLOAD" not in str(caught.value)
