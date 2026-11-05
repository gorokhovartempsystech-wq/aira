"""Row-locked entitlement operations; no document data or cached launch grants."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ara import licensing as core
from ara.licensing._models import MAX_EPOCH_MS, identifier, integer
from ara.licensing._policy import checked_record

from ._models import fail, require, transaction, validate_runtime
from ._schema import licenses, require_schema


def _now(connection, runtime):
    try:
        value = (
            runtime.clock_ms()
            if runtime.clock_ms is not None
            else connection.exec_driver_sql(
                "SELECT floor(extract(epoch FROM clock_timestamp())*1000)::bigint"
            ).scalar_one()
        )
        if type(value) is not int or not 0 <= value <= MAX_EPOCH_MS:
            raise ValueError
    except Exception:
        raise core.LicenseError("clock_unavailable") from None
    return value


def _record(row):
    if row is None:
        fail("invalid_license")
    try:
        record = checked_record(
            core.LicenseRecord(
                row["license_id"],
                row["duration_seconds"],
                row["enabled"],
                row["device_id"],
                row["activated_at_ms"],
                row["expires_at_ms"],
            )
        )
        created = row["created_at_ms"]
        require(type(created) is int and 0 <= created <= MAX_EPOCH_MS, "license_storage_error")
        require(
            record.activated_at_ms is None or record.activated_at_ms >= created,
            "license_storage_error",
        )
        return record
    except core.LicenseError:
        raise
    except Exception:
        fail("license_storage_error")


def _row(connection, predicate, *, lock=True):
    query = select(licenses).where(predicate)
    if lock:
        query = query.with_for_update()
    return connection.execute(query).mappings().one_or_none()


def issue_license(runtime, *, license_id, key, duration_seconds):
    validate_runtime(runtime)
    identifier(license_id)
    integer(duration_seconds, MAX_EPOCH_MS // 1000, minimum=1)
    digest = core.key_digest(key, runtime.pepper)
    with transaction(runtime.engine) as connection:
        require_schema(connection)
        connection.execute(
            insert(licenses)
            .values(
                license_id=license_id,
                key_digest=digest,
                duration_seconds=duration_seconds,
                enabled=True,
                created_at_ms=_now(connection, runtime),
            )
            .on_conflict_do_nothing()
        )
        row = _row(connection, licenses.c.license_id == license_id)
        require(
            row is not None
            and (row["key_digest"], row["duration_seconds"]) == (digest, duration_seconds),
            "license_conflict",
        )
        result = _record(row)
    return result


def get_license(runtime, *, license_id):
    validate_runtime(runtime)
    identifier(license_id)
    with transaction(runtime.engine) as connection:
        require_schema(connection)
        result = _record(_row(connection, licenses.c.license_id == license_id, lock=False))
    return result


def set_enabled(runtime, *, license_id, enabled):
    validate_runtime(runtime)
    identifier(license_id)
    require(type(enabled) is bool)
    with transaction(runtime.engine) as connection:
        require_schema(connection)
        _record(_row(connection, licenses.c.license_id == license_id))
        connection.execute(
            licenses.update().where(licenses.c.license_id == license_id).values(enabled=enabled)
        )
        result = _record(_row(connection, licenses.c.license_id == license_id, lock=False))
    return result


def process_request(runtime, request):
    validate_runtime(runtime)
    request = core.decode_request(core.encode_request(request))
    predicate = (
        licenses.c.key_digest == core.key_digest(request.license_key, runtime.pepper)
        if request.operation == "activate"
        else licenses.c.license_id == request.license_id
    )
    with transaction(runtime.engine) as connection:
        require_schema(connection)
        row = _row(connection, predicate)
        record = _record(row)
        now = _now(connection, runtime)
        if now < row["created_at_ms"]:
            raise core.LicenseError("clock_unavailable")
        operation = core.activate if request.operation == "activate" else core.check
        current = operation(record, device_id=request.device_id, now_ms=now)
        if current != record:
            connection.execute(
                licenses.update()
                .where(licenses.c.license_id == current.license_id)
                .values(
                    device_id=current.device_id,
                    activated_at_ms=current.activated_at_ms,
                    expires_at_ms=current.expires_at_ms,
                )
            )
        output = core.encode_grant(core.make_grant(current, request, now_ms=now))
    return output
