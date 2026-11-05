"""Closed PG18 argv/auth configuration; no native calls, environment or file access."""

import re
import unicodedata
from types import MappingProxyType
from uuid import UUID

from ._models import PostgresPlan, ProfileError, require

TARGETS = ("macos-arm64", "macos-x86_64", "windows-x86_64")
PATH_SETTINGS = ("data_directory", "config_file", "hba_file", "ident_file")
FIXED = {
    "unix_socket_permissions": "0700",
    "fsync": "on",
    "full_page_writes": "on",
    "synchronous_commit": "on",
    "default_transaction_read_only": "off",
    "zero_damaged_pages": "off",
    "ignore_checksum_failure": "off",
    "ssl": "off",
    "shared_preload_libraries": "",
    "session_preload_libraries": "",
    "local_preload_libraries": "",
    "archive_mode": "off",
    "archive_command": "",
    "restore_command": "",
    "logging_collector": "off",
    "log_destination": "stderr",
    "log_statement": "none",
    "log_min_error_statement": "panic",
    "log_parameter_max_length_on_error": "0",
    "max_connections": "32",
    "shared_buffers": "32MB",
}
SETTING_NAMES = (
    *PATH_SETTINGS,
    "listen_addresses",
    "port",
    "unix_socket_directories",
    *FIXED,
    "block_size",
    "data_checksums",
)


def string(value, limit):
    require(type(value) is str and bool(value))
    try:
        require(len(value.encode("utf-8")) <= limit)
    except UnicodeError:
        raise ProfileError() from None
    require(not any(unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp") for c in value))
    return value


def account(value):
    value = string(value, 256)
    require(value == value.strip() and not any(c in value for c in '/\\"@'))
    return value


def path(value, windows):
    value = string(value, 1024)
    if windows:
        value = value.replace("\\", "/")
        require(re.match(r"^[A-Za-z]:/", value) is not None)
        parts = value[3:].split("/")
        require(all(p and p not in (".", "..") for p in parts))
        for part in parts:
            require(not any(c in part for c in '<>:"|?*'))
            require(not part.endswith((".", " ")))
            base = part.split(".", 1)[0].upper()
            require(base not in ("CON", "PRN", "AUX", "NUL"))
            require(re.fullmatch(r"(?:COM|LPT)[1-9¹²³]", base) is None)
        return value[0].upper() + value[1:]
    require(value.startswith("/") and "\\" not in value)
    require(all(p and p not in (".", "..") for p in value[1:].split("/")))
    return value


def make_plan(
    *,
    target,
    installation_id,
    postgres_root,
    system_user,
    windows_realm=None,
    port=None,
    socket_id=None,
):
    require(type(target) is str and target in TARGETS, "unsupported_target")
    require(type(installation_id) is UUID and installation_id.version == 4)
    windows = target == "windows-x86_64"
    require(socket_id is None or (type(socket_id) is UUID and socket_id.version == 4))
    root = path(postgres_root, windows)
    user = account(system_user)
    if windows:
        require(socket_id is None)
        realm = account(windows_realm)
        require(type(port) is int and 49152 <= port <= 65535)
        socket_root = None
        principal = user + "@" + realm
        hba_first = (
            "host postgres,aira aira_local 127.0.0.1/32 sspi "
            "map=aira_owner include_realm=1 compat_realm=1 upn_username=0\n"
        )
    else:
        require(windows_realm is None)
        require(port is None or (type(port) is int and port == 5432))
        port = 5432
        realm = None
        socket_root = "/private/tmp/aira-pg-" + (socket_id or installation_id).hex
        principal = user
        hba_first = "local postgres,aira aira_local peer map=aira_owner\n"
    data_dir, staging_dir = root + "/data18", root + "/.data18.pending"
    values = (
        dict(
            data_directory=data_dir,
            config_file=root + "/server.conf",
            hba_file=root + "/pg_hba.conf",
            ident_file=root + "/pg_ident.conf",
            listen_addresses="127.0.0.1" if windows else "",
            port=str(port),
            unix_socket_directories=socket_root or "",
        )
        | FIXED
    )
    arguments = ("-D", data_dir) + tuple(
        item for name, value in values.items() for item in ("-c", name + "=" + value)
    )
    files = {
        "server.conf": b"# AIRA PostgreSQL18: settings supplied by the owned launcher.\n",
        "pg_hba.conf": (
            hba_first
            + "local all all reject\n"
            + "host all all 0.0.0.0/0 reject\n"
            + "host all all ::0/0 reject\n"
        ).encode("utf-8"),
        "pg_ident.conf": ('aira_owner "' + principal + '" aira_local\n').encode("utf-8"),
    }
    return PostgresPlan(
        target=target,
        installation_id=installation_id,
        postgres_root=root,
        data_dir=data_dir,
        staging_dir=staging_dir,
        socket_root=socket_root,
        port=port,
        files=MappingProxyType(files),
        initdb_arguments=(
            "--pgdata",
            staging_dir,
            "--username=aira_local",
            "--encoding=UTF8",
            "--locale=C",
            "--locale-provider=libc",
            "--auth-local=reject",
            "--auth-host=reject",
            "--data-checksums",
            "--no-clean",
            "--no-instructions",
        ),
        postgres_arguments=arguments,
        _system_user=user,
        _windows_realm=realm,
        _expected_settings=MappingProxyType(
            values | {"shared_buffers": "4096", "block_size": "8192", "data_checksums": "on"}
        ),
        _socket_id=socket_id,
    )


def validate_plan(plan):
    require(type(plan) is PostgresPlan)
    canonical = make_plan(
        target=plan.target,
        installation_id=plan.installation_id,
        postgres_root=plan.postgres_root,
        system_user=plan._system_user,
        windows_realm=plan._windows_realm,
        port=plan.port,
        socket_id=plan._socket_id,
    )
    require(plan == canonical)
