"""Strict private journal metadata and bounded pg_controldata identity reading."""

import json
import re

from ._models import ClusterError, require

SCHEMAS = {
    "initialization": "aira-pg-initialization/1",
    "prepared": "aira-pg-prepared/1",
    "cluster": "aira-pg-cluster/1",
}


def system_id(value):
    require(type(value) is str and re.fullmatch(r"[1-9][0-9]{0,19}", value) is not None)
    require(int(value) < 2**64)
    return value


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result)
        result[key] = value
    return result


def bad_constant(value):
    raise ClusterError("cluster_recovery_required")


def make(kind, installation, target, system=None, oid=None):
    value = dict(schema_version=SCHEMAS[kind], installation_id=str(installation), target=target)
    if kind != "initialization":
        value["system_identifier"] = system_id(system)
    if kind == "cluster":
        require(type(oid) is int and 1 <= oid < 2**32)
        value.update(postgres_major=18, database_name="aira", database_oid=oid)
    return value


def encode(value):
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode() + b"\n"
    )


def decode(raw, kind, installation, target):
    require(type(raw) is bytes and 0 < len(raw) <= 4096)
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=bad_constant
        )
    except (ValueError, UnicodeError, RecursionError):
        raise ClusterError("cluster_recovery_required") from None
    require(type(value) is dict)
    expected = make(
        kind, installation, target, value.get("system_identifier"), value.get("database_oid")
    )
    require(set(value) == set(expected) and value == expected)
    if kind == "cluster":
        require(type(value["postgres_major"]) is int)
    return value


def control(raw, *, initial):
    # This selects identity metadata only. Successful server startup remains the
    # authority for accepting the physical cluster, including its control CRC.
    require(type(raw) is bytes and 0 < len(raw) <= 65536)
    try:
        lines = raw.decode("ascii").splitlines()
    except UnicodeError:
        raise ClusterError("cluster_recovery_required") from None
    require(len(lines) <= 128 and all(len(line) <= 2048 for line in lines))
    wanted = {
        "pg_control version number",
        "Database system identifier",
        "Database cluster state",
        "Database block size",
        "Data page checksum version",
    }
    values = {}
    for line in lines:
        key, separator, value = line.partition(":")
        if separator and key in wanted:
            require(key not in values)
            values[key] = value.strip()
    require(set(values) == wanted)
    require(values["pg_control version number"] == "1800")
    require(values["Database block size"] == "8192")
    require(values["Data page checksum version"] == "1")
    if initial:
        require(values["Database cluster state"] == "shut down")
    else:
        require(
            values["Database cluster state"] in ("shut down", "in production", "in crash recovery")
        )
    return system_id(values["Database system identifier"])
