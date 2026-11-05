"""Public local scope metadata; no activation keys or offline permits."""

import json
from uuid import UUID, uuid4, uuid5

from ._models import CHILDREN, IDENTITY, OWNER, PENDING, HomeError, InstallationIdentity, require

_SCHEMA = "aira-data-home/1"


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


def decode(raw):
    try:
        require(type(raw) is bytes and 0 < len(raw) <= 1024)
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
        require(
            type(data) is dict
            and set(data) == {"schema_version", "installation_id"}
            and data["schema_version"] == _SCHEMA
            and type(data["installation_id"]) is str
        )
        value = UUID(data["installation_id"])
        require(str(value) == data["installation_id"] and value.version == 4)
        return InstallationIdentity(
            value, uuid5(value, "aira/local-user/1"), uuid5(value, "aira/local-project/1")
        )
    except HomeError:
        raise
    except Exception:
        raise HomeError("home_recovery_required") from None


def prepare(filesystem):
    names = filesystem.entries()
    raw = filesystem.read(IDENTITY)
    if raw is not None:
        require(PENDING not in names)
        identity = decode(raw)
        filesystem.sync_existing()
    else:
        # Without a committed identity, even an empty data directory is not adopted.
        require(names <= {OWNER, PENDING})
        pending = filesystem.read(PENDING)
        if pending is not None:
            try:
                decode(pending)
            except HomeError:
                # Only this named unpublished staging file in a proven pristine root.
                filesystem.remove_pending(pending)
                pending = None
        if pending is None:
            pending = json.dumps(
                dict(schema_version=_SCHEMA, installation_id=str(uuid4())), separators=(",", ":")
            ).encode()
            filesystem.write_pending(pending)
        identity = decode(pending)
        filesystem.publish_pending(pending)
    for name in CHILDREN:
        filesystem.ensure_child(name)
    filesystem.sync_existing()
    return identity
