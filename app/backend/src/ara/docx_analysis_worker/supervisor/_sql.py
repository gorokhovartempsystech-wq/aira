"""Small ordered SQL primitives; no platform resource or implicit connection setup."""

from contextlib import contextmanager
from uuid import UUID

import psycopg
from sqlalchemy import Engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeout
from sqlalchemy.orm import Session

from ara.documents.storage import DocumentError
from ara.models import DocxAnalysisSupervisor as Fence

from .sql_models import FenceView, LaunchBinding, OwnerBinding, SupervisorStorageError

MAX = 2**63 - 1
FIELDS = ("launch_id", "document_id", "run_id", "attempt_id", "worker_instance_id", "claim_fence")


def fail(code="storage_conflict"):
    raise SupervisorStorageError(code)


def uuid(value):
    if type(value) is not UUID:
        fail("validation_error")
    return value


def owner(value):
    if type(value) is not OwnerBinding:
        fail("validation_error")
    uuid(value.installation_id)
    uuid(value.owner_epoch)
    return value


def binding(value):
    if type(value) is not LaunchBinding:
        fail("validation_error")
    owner(value.owner)
    for field in FIELDS[:-1]:
        uuid(getattr(value, field))
    if type(value.claim_fence) is not int or value.claim_fence != 1:
        fail("validation_error")
    return value


def revision(value):
    if type(value) is not int or not 1 <= value < MAX:
        fail("validation_error")
    return value


@contextmanager
def transaction(engine):
    if not isinstance(engine, Engine):
        fail("validation_error")
    try:
        with Session(engine) as session, session.begin():
            yield session
    except (DocumentError, SupervisorStorageError):
        raise
    except (OperationalError, psycopg.OperationalError, PoolTimeout):
        raise SupervisorStorageError("storage_unavailable") from None
    except Exception:
        raise SupervisorStorageError("storage_error") from None


def locked(session):
    rows = session.scalars(select(Fence).limit(2).with_for_update()).all()
    if len(rows) != 1:
        fail("recovery_required")
    row = rows[0]
    if row.slot_key != 1 or type(row.revision) is not int or not 1 <= row.revision <= MAX:
        fail("recovery_required")
    fields = [getattr(row, field) for field in FIELDS]
    if row.phase == "unprovisioned":
        valid = (
            row.installation_id is None
            and row.owner_epoch is None
            and all(value is None for value in fields)
        )
    elif row.phase == "clean":
        valid = (
            type(row.installation_id) is UUID
            and (row.owner_epoch is None or type(row.owner_epoch) is UUID)
            and all(value is None for value in fields)
        )
    elif row.phase in ("armed", "drained"):
        valid = (
            all(
                type(value) is UUID
                for value in (row.installation_id, row.owner_epoch, *fields[:-1])
            )
            and type(row.claim_fence) is int
            and row.claim_fence == 1
        )
    else:
        valid = False
    if not valid:
        fail("recovery_required")
    return row


def view(row):
    value = None
    if row.phase in ("armed", "drained"):
        value = LaunchBinding(
            OwnerBinding(row.installation_id, row.owner_epoch),
            *(getattr(row, field) for field in FIELDS),
        )
    return FenceView(row.revision, row.phase, row.installation_id, row.owner_epoch, value)


def owned(row, value):
    owner(value)
    if (row.installation_id, row.owner_epoch) != (value.installation_id, value.owner_epoch):
        fail()


def bound(row, value):
    binding(value)
    owned(row, value.owner)
    if any(getattr(row, field) != getattr(value, field) for field in FIELDS):
        fail()


def desired_binding(value):
    return {field: getattr(value, field) for field in FIELDS}


def claim_metadata(run, attempt, claim):
    fields = (
        "document_id",
        "storage_revision",
        "source_sha256",
        "profile",
        "policy_version",
        "snapshot_sha256",
        "command_sha256",
        "execution_spec_sha256",
        "execution_kind",
        "format_version",
    )
    return (
        attempt is not None
        and attempt.id == claim.attempt.attempt_id
        and attempt.request_sha256 == claim.attempt.request_sha256
        and run.started_at == claim.claimed_at
        and run.deadline_at == claim.deadline_at
        and all(getattr(run, field) == getattr(claim.source, field) for field in fields)
    )


def replay(row, expected, values):
    revision(expected)
    return row.revision == expected + 1 and all(
        getattr(row, key) == value for key, value in values.items()
    )


def update(row, expected, values):
    revision(expected)
    if row.revision != expected:
        fail()
    for key, value in values.items():
        setattr(row, key, value)
    row.revision += 1
    return view(row)
