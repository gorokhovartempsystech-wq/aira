"""Explicit model-key service alongside v1 licensing, in a separate SQL schema."""

import re
import secrets
from dataclasses import dataclass, field

import anyio
from fastapi import Request
from sqlalchemy import BigInteger, Column, MetaData, String, Table, Uuid, inspect, select
from sqlalchemy.dialects.postgresql import insert
from starlette.responses import JSONResponse

from ara import licensing as core
from ara.licensing._models import uuid_text
from ara.licensing.server._http import _body
from ara.licensing.server._models import ServerError, transaction, validate_runtime
from ara.licensing.server._schema import licenses, require_schema
from ara.licensing.server._storage import _now, _record

from .access_wire import (
    VERSION,
    AccessError,
    decode,
    hex_text,
    label,
    make_token,
    require,
    shape,
    verify_proof,
    verify_token,
)


class _EnrollmentRequired(ServerError):
    def __init__(self):
        super().__init__("validation_error")
        self.code, self.status, self.message = (
            "enrollment_required",
            403,
            "Device enrollment required",
        )


metadata = MetaData(schema="aira_model_access")
devices = Table(
    "devices",
    metadata,
    Column("license_id", Uuid, primary_key=True),
    Column("device_id", String(68), nullable=False),
    Column("public_key", String(64), nullable=False),
    Column("revision", BigInteger, nullable=False),
)
used = Table(
    "used_challenges",
    metadata,
    Column("nonce", String(64), primary_key=True),
    Column("expires_ms", BigInteger, nullable=False),
)


def _schema(connection):
    inspector = inspect(connection)
    require(
        set(inspector.get_table_names(schema=metadata.schema)) == {"devices", "used_challenges"}
    )
    for table in (devices, used):
        actual = {
            c["name"]: (str(c["type"]), c["nullable"])
            for c in inspector.get_columns(table.name, schema=metadata.schema)
        }
        require(
            actual
            == {
                c.name: (c.type.compile(dialect=connection.dialect), c.nullable)
                for c in table.columns
            }
        )
        require(
            inspector.get_pk_constraint(table.name, schema=metadata.schema)["constrained_columns"]
            == [c.name for c in table.primary_key.columns]
        )


@dataclass(frozen=True)
class Release:
    release_id: str
    manifest_sha256: str
    key: bytes = field(repr=False)

    def __post_init__(self):
        label(self.release_id)
        hex_text(self.manifest_sha256)
        require(type(self.key) is bytes and len(self.key) == 32)


def initialize_model_access(engine):
    with transaction(engine) as connection:
        require_schema(connection, full=True)
        connection.exec_driver_sql("SELECT pg_advisory_xact_lock(1095324225,1297040460)")
        connection.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS aira_model_access")
        names = inspect(connection).get_table_names(schema=metadata.schema)
        if not names:
            metadata.create_all(connection, checkfirst=False)
        _schema(connection)


class ModelAccessService:
    def __init__(self, runtime, releases):
        validate_runtime(runtime)
        require(type(releases) is tuple and bool(releases) and len(releases) <= 16)
        require(all(type(item) is Release for item in releases))
        require(len({item.release_id for item in releases}) == len(releases))
        self.runtime, self.releases = runtime, {item.release_id: item for item in releases}

    def _release(self, body):
        label(body["release_id"])
        hex_text(body["manifest_sha256"])
        release = self.releases.get(body["release_id"])
        require(release is not None and release.manifest_sha256 == body["manifest_sha256"])
        return release

    def _license(self, connection, predicate):
        row = (
            connection.execute(select(licenses).where(predicate).with_for_update())
            .mappings()
            .one_or_none()
        )
        return _record(row), _now(connection, self.runtime)

    def challenge(self, body):
        shape(
            body,
            "schema_version operation license_id license_key device_id public_key "
            "client_nonce release_id manifest_sha256",
        )
        require(body["schema_version"] == VERSION and body["operation"] in {"enroll", "unlock"})
        require(
            type(body["device_id"]) is str
            and re.fullmatch(r"dv1-[0-9a-f]{64}", body["device_id"]) is not None
        )
        hex_text(body["client_nonce"])
        hex_text(body["public_key"])
        identifier = uuid_text(body["license_id"])
        self._release(body)
        with transaction(self.runtime.engine) as connection:
            require_schema(connection)
            _schema(connection)
            record, now = self._license(connection, licenses.c.license_id == identifier)
            device = (
                connection.execute(select(devices).where(devices.c.license_id == identifier))
                .mappings()
                .one_or_none()
            )
            if body["operation"] == "enroll":
                digest = core.key_digest(body["license_key"], self.runtime.pepper)
                stored = connection.execute(
                    select(licenses.c.key_digest).where(licenses.c.license_id == identifier)
                ).scalar_one()
                require(secrets.compare_digest(digest, stored))
                core.activate(record, device_id=body["device_id"], now_ms=now)
            else:
                require(body["license_key"] is None)
                core.check(record, device_id=body["device_id"], now_ms=now)
                if device is None or (device["device_id"], device["public_key"]) != (
                    body["device_id"],
                    body["public_key"],
                ):
                    raise _EnrollmentRequired()
            payload = {
                k: body[k]
                for k in (
                    "operation",
                    "license_id",
                    "device_id",
                    "public_key",
                    "client_nonce",
                    "release_id",
                    "manifest_sha256",
                )
            }
            revision = device["revision"] if device is not None else 0
            require(type(revision) is int and 0 <= revision < 2**63 - 1)
            payload.update(
                schema_version=VERSION,
                nonce=secrets.token_hex(32),
                issued_ms=now,
                expires_ms=now + 60_000,
                revision=revision,
            )
            return dict(schema_version=VERSION, token=make_token(payload, self.runtime.pepper))

    def complete(self, body):
        shape(body, "schema_version token signature")
        require(body["schema_version"] == VERSION)
        payload = verify_token(body["token"], self.runtime.pepper)
        shape(
            payload,
            "schema_version operation license_id device_id public_key client_nonce "
            "release_id manifest_sha256 nonce issued_ms expires_ms revision",
        )
        require(
            payload["schema_version"] == VERSION and payload["operation"] in {"enroll", "unlock"}
        )
        release = self._release(payload)
        verify_proof(payload["public_key"], body["token"], body["signature"])
        identifier = uuid_text(payload["license_id"])
        with transaction(self.runtime.engine) as connection:
            require_schema(connection)
            _schema(connection)
            record, now = self._license(connection, licenses.c.license_id == identifier)
            device = (
                connection.execute(select(devices).where(devices.c.license_id == identifier))
                .mappings()
                .one_or_none()
            )
            require(payload["revision"] == (device["revision"] if device else 0))
            require(type(payload["issued_ms"]) is int and type(payload["expires_ms"]) is int)
            require(
                payload["issued_ms"] <= now < payload["expires_ms"] == payload["issued_ms"] + 60_000
            )
            operation = core.activate if payload["operation"] == "enroll" else core.check
            current = operation(record, device_id=payload["device_id"], now_ms=now)
            connection.execute(used.delete().where(used.c.expires_ms <= now))
            claimed = connection.execute(
                insert(used)
                .values(nonce=payload["nonce"], expires_ms=payload["expires_ms"])
                .on_conflict_do_nothing()
                .returning(used.c.nonce)
            ).scalar_one_or_none()
            require(claimed is not None)
            if payload["operation"] == "enroll":
                values = dict(
                    device_id=payload["device_id"],
                    public_key=payload["public_key"],
                    revision=payload["revision"] + 1,
                )
                connection.execute(
                    insert(devices)
                    .values(license_id=identifier, **values)
                    .on_conflict_do_update(index_elements=[devices.c.license_id], set_=values)
                )
                connection.execute(
                    licenses.update()
                    .where(licenses.c.license_id == identifier)
                    .values(
                        device_id=current.device_id,
                        activated_at_ms=current.activated_at_ms,
                        expires_at_ms=current.expires_at_ms,
                    )
                )
            else:
                device = (
                    connection.execute(select(devices).where(devices.c.license_id == identifier))
                    .mappings()
                    .one_or_none()
                )
                require(
                    device is not None
                    and (device["device_id"], device["public_key"])
                    == (payload["device_id"], payload["public_key"])
                )
            return dict(
                schema_version=VERSION,
                license_id=str(identifier),
                device_id=current.device_id,
                client_nonce=payload["client_nonce"],
                release_id=release.release_id,
                manifest_sha256=release.manifest_sha256,
                checked_at_ms=now,
                expires_at_ms=current.expires_at_ms,
                key=release.key.hex(),
            )


def attach_model_access(app, service):
    require(type(service) is ModelAccessService)
    limiter = anyio.CapacityLimiter(4)

    async def execute(request, operation):
        acquired = False
        try:
            require(request.scope.get("scheme") == "https")
            limiter.acquire_nowait()
            acquired = True
            body = decode(await _body(request))
            with anyio.CancelScope(shield=True):
                result = await anyio.to_thread.run_sync(getattr(service, operation), body)
            return JSONResponse(result, headers={"Cache-Control": "no-store"})
        except _EnrollmentRequired:
            return JSONResponse(
                {"code": "enrollment_required"},
                status_code=403,
                headers={"Cache-Control": "no-store"},
            )
        except (AccessError, core.LicenseError, ServerError):
            return JSONResponse(
                {"code": "model_access_unavailable"},
                status_code=403,
                headers={"Cache-Control": "no-store"},
            )
        except Exception:
            return JSONResponse(
                {"code": "model_access_unavailable"},
                status_code=503,
                headers={"Cache-Control": "no-store"},
            )
        finally:
            if acquired:
                limiter.release()

    @app.post("/license/model/v1/challenge", include_in_schema=False)
    async def challenge(request: Request):
        return await execute(request, "challenge")

    @app.post("/license/model/v1/complete", include_in_schema=False)
    async def complete(request: Request):
        return await execute(request, "complete")
