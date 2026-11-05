"""Independent closed PostgreSQL configuration and observation acceptance."""

import dataclasses
import importlib
from uuid import UUID

import pytest

INSTALLATION = UUID("b1234567-1234-4234-8234-123456789abc")


def api():
    return importlib.import_module("ara.desktop.postgres_profile")


def make(**changes):
    values = dict(
        target="macos-arm64",
        installation_id=INSTALLATION,
        postgres_root="/private/tmp/SYNTHETIC_PRIVATE O'Brien/postgres",
        system_user="Synthetic User",
    )
    values.update(changes)
    return api().make_plan(**values)


def reject(code, call):
    with pytest.raises(api().ProfileError) as caught:
        call()
    assert caught.value.code == code
    assert "SYNTHETIC_PRIVATE" not in str(caught.value) + repr(caught.value)


def settings(plan):
    arguments = plan.postgres_arguments
    assert arguments[:2] == ("-D", plan.data_dir)
    pairs = arguments[2:]
    assert len(pairs) % 2 == 0 and all(k == "-c" for k in pairs[::2])
    parsed = [v.split("=", 1) for v in pairs[1::2]]
    assert len({k for k, v in parsed}) == len(parsed)
    return dict(parsed)


def observation(plan):
    values = settings(plan)
    values["shared_buffers"] = "4096"
    values["block_size"] = "8192"
    values["data_checksums"] = "on"
    return dict(
        server_version_num=180006,
        system_identifier="7654321098765432100",
        database="aira",
        user="aira_local",
        session_user="aira_local",
        in_recovery=False,
        encoding="UTF8",
        collate="C",
        ctype="C",
        settings=values,
    )


def check(plan, value, **kwargs):
    return api().check_observation(
        plan, value, expected_system_identifier="7654321098765432100", **kwargs
    )


def test_mac_plan_private_peer_endpoint_and_literal_arguments():
    plan = make()
    assert plan.data_dir == plan.postgres_root + "/data18"
    assert plan.staging_dir == plan.postgres_root + "/.data18.pending"
    assert plan.socket_root == "/private/tmp/aira-pg-" + INSTALLATION.hex
    assert len((plan.socket_root + "/.s.PGSQL.5432").encode()) < 104
    assert plan.port == 5432
    config = settings(plan)
    assert config["listen_addresses"] == ""
    assert config["unix_socket_directories"] == plan.socket_root
    assert config["unix_socket_permissions"] == "0700"
    for name in ("fsync", "full_page_writes", "synchronous_commit"):
        assert config[name] == "on"
    for name in (
        "default_transaction_read_only",
        "zero_damaged_pages",
        "ignore_checksum_failure",
        "ssl",
        "logging_collector",
        "archive_mode",
    ):
        assert config[name] == "off"
    for name in (
        "shared_preload_libraries",
        "session_preload_libraries",
        "local_preload_libraries",
        "archive_command",
        "restore_command",
    ):
        assert config[name] == ""
    assert config["log_statement"] == "none"
    assert config["log_min_error_statement"] == "panic"
    assert config["log_parameter_max_length_on_error"] == "0"
    assert config["max_connections"] == "32"
    assert config["shared_buffers"] == "32MB"
    assert config["data_directory"] == plan.data_dir
    assert config["config_file"] == plan.postgres_root + "/server.conf"
    assert config["hba_file"] == plan.postgres_root + "/pg_hba.conf"
    assert config["ident_file"] == plan.postgres_root + "/pg_ident.conf"
    assert set(plan.files) == {"server.conf", "pg_hba.conf", "pg_ident.conf"}
    assert plan.files["server.conf"].startswith(b"#")
    assert plan.files["pg_ident.conf"].decode().splitlines() == [
        'aira_owner "Synthetic User" aira_local'
    ]
    hba = plan.files["pg_hba.conf"].decode().splitlines()
    assert hba[0] == "local postgres,aira aira_local peer map=aira_owner"
    assert "local all all reject" in hba
    assert "host all all 0.0.0.0/0 reject" in hba
    assert "host all all ::0/0 reject" in hba
    assert all("trust" not in line and "include" not in line for line in hba)


def test_initdb_uses_staging_and_preserves_partial_work():
    plan = make()
    args = plan.initdb_arguments
    assert type(args) is tuple and args[:2] == ("--pgdata", plan.staging_dir)
    assert {
        "--username=aira_local",
        "--encoding=UTF8",
        "--locale=C",
        "--locale-provider=libc",
        "--auth-local=reject",
        "--auth-host=reject",
        "--data-checksums",
        "--no-clean",
        "--no-instructions",
    } <= set(args)
    assert not any(v.startswith(("--no-sync", "--pwfile", "--allow-group")) for v in args)
    assert "--pgdata" not in args[2:]
    assert plan.data_dir not in args


def test_windows_plan_keeps_realm_and_uses_only_local_ipv4():
    plan = make(
        target="windows-x86_64",
        postgres_root="c:\\Users\\Synthetic User\\AIRA\\postgres",
        windows_realm="SYNTHETIC_MACHINE",
        port=52121,
    )
    assert plan.postgres_root == "C:/Users/Synthetic User/AIRA/postgres"
    assert plan.socket_root is None and plan.port == 52121
    config = settings(plan)
    assert config["listen_addresses"] == "127.0.0.1"
    assert config["unix_socket_directories"] == ""
    assert plan.files["pg_ident.conf"] == (
        b'aira_owner "Synthetic User@SYNTHETIC_MACHINE" aira_local\n'
    )
    first = plan.files["pg_hba.conf"].decode().splitlines()[0]
    assert first == (
        "host postgres,aira aira_local 127.0.0.1/32 sspi "
        "map=aira_owner include_realm=1 compat_realm=1 upn_username=0"
    )
    assert plan.connection()["passfile"] == "NUL"
    value = observation(plan)
    value["settings"]["data_directory"] = value["settings"]["data_directory"].lower()
    assert check(plan, value) is None


def test_connection_is_closed_and_detached():
    plan = make()
    assert dict(plan.connection()) == dict(
        dbname="aira",
        user="aira_local",
        host=plan.socket_root,
        port="5432",
        connect_timeout="2",
        application_name="aira_desktop",
        sslmode="disable",
        gssencmode="disable",
        passfile="/dev/null",
    )
    assert plan.connection("postgres")["dbname"] == "postgres"
    with pytest.raises(TypeError):
        plan.connection()["host"] = "elsewhere"
    reject("validation_error", lambda: plan.connection("other"))
    with pytest.raises(TypeError):
        plan.files["pg_hba.conf"] = b"trust"
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.port = 1
    assert "SYNTHETIC_PRIVATE" not in repr(plan)
    assert "Synthetic User" not in repr(plan)
    assert api().ProfileError("SYNTHETIC_PRIVATE").code == "validation_error"


@pytest.mark.parametrize(
    "changes",
    [
        {"installation_id": str(INSTALLATION)},
        {"installation_id": UUID(int=0)},
        {"system_user": ""},
        {"system_user": " x"},
        {"system_user": 'x" all trust'},
        {"system_user": "x\ny"},
        {"system_user": "/.*"},
        {"system_user": "x\\y"},
        {"system_user": "x@realm"},
        {"system_user": "x" * 257},
        {"windows_realm": "unwanted"},
        {"port": 9999},
        {"port": True},
        {"postgres_root": "/"},
        {"postgres_root": "relative"},
        {"postgres_root": "/private/../tmp/pg"},
        {"postgres_root": "/private/./tmp/pg"},
        {"postgres_root": "/private//tmp/pg"},
        {"postgres_root": "/private/tmp/pg/"},
        {"postgres_root": "/private/tmp/pg\x00"},
        {"postgres_root": "/private/tmp/pg\n"},
        {"postgres_root": "/private/tmp/pg\\foo"},
        {"postgres_root": "/" + "x" * 1024},
    ],
)
def test_invalid_input_is_not_coerced(changes):
    reject("validation_error", lambda: make(**changes))


@pytest.mark.parametrize("target", [None, "linux-x86_64", "MACOS-ARM64", ""])
def test_unknown_targets(target):
    reject("unsupported_target", lambda: make(target=target))


@pytest.mark.parametrize(
    "changes",
    [
        {"windows_realm": None},
        {"windows_realm": "bad@realm"},
        {"port": None},
        {"port": 49151},
        {"port": 65536},
        {"port": True},
        {"postgres_root": "C:relative"},
        {"postgres_root": "//server/share/pg"},
        {"postgres_root": "//?/C:/pg"},
        {"postgres_root": "C:/pg/file:stream"},
        {"postgres_root": "C:/NUL/pg"},
        {"postgres_root": "C:/temp./pg"},
        {"postgres_root": "C:/temp /pg"},
        {"postgres_root": "C:/temp*/pg"},
        {"postgres_root": "C:/temp/../pg"},
    ],
)
def test_invalid_windows_inputs(changes):
    values = dict(
        target="windows-x86_64",
        postgres_root="C:/AIRA/postgres",
        windows_realm="MACHINE",
        port=52121,
    )
    values.update(changes)
    reject("validation_error", lambda: make(**values))


def test_good_observation_and_admin_database():
    plan = make()
    value = observation(plan)
    assert check(plan, value) is None
    value["database"] = "postgres"
    assert check(plan, value, database="postgres") is None
    assert "SELECT" in api().OBSERVATION_SQL.upper()
    assert "pg_control_system" in api().OBSERVATION_SQL
    assert "pg_settings" in api().OBSERVATION_SQL


@pytest.mark.parametrize(
    "key,value",
    [
        ("server_version_num", 170006),
        ("server_version_num", 190000),
        ("server_version_num", True),
        ("system_identifier", "7654321098765432101"),
        ("system_identifier", 7654321098765432100),
        ("system_identifier", "07654321098765432100"),
        ("database", "foreign"),
        ("user", "foreign"),
        ("session_user", "foreign"),
        ("in_recovery", True),
        ("in_recovery", 0),
        ("encoding", "LATIN1"),
        ("collate", "en_US.UTF-8"),
        ("ctype", "en_US.UTF-8"),
        ("settings", []),
    ],
)
def test_observation_mismatch(key, value):
    plan = make()
    actual = observation(plan)
    actual[key] = value
    reject("postgres_mismatch", lambda: check(plan, actual))


def test_each_required_setting_is_checked_and_no_extra_fields_admitted():
    plan = make()
    valid = observation(plan)
    for key in valid["settings"]:
        changed = observation(plan)
        changed["settings"][key] = "SYNTHETIC_PRIVATE_wrong"
        reject("postgres_mismatch", lambda: check(plan, changed))
        del changed["settings"][key]
        reject("postgres_mismatch", lambda: check(plan, changed))
    changed = observation(plan)
    changed["settings"]["surprise"] = "value"
    reject("postgres_mismatch", lambda: check(plan, changed))
    for key in valid:
        changed = observation(plan)
        del changed[key]
        reject("postgres_mismatch", lambda: check(plan, changed))
    valid["surprise"] = 0
    reject("postgres_mismatch", lambda: check(plan, valid))


@pytest.mark.parametrize("identifier", [None, "", "0", "01", "-1", str(2**64), 42])
def test_expected_cluster_id_must_be_independent_valid_input(identifier):
    plan = make()
    reject(
        "validation_error",
        lambda: api().check_observation(
            plan, observation(plan), expected_system_identifier=identifier
        ),
    )


def test_factory_and_check_do_not_open_files_or_connect(monkeypatch):
    import builtins
    import os
    import socket
    import subprocess

    module = api()

    def forbidden(*args, **kwargs):
        raise AssertionError("Pure profile attempted an external action")

    for obj, name in (
        (builtins, "open"),
        (os, "open"),
        (os, "urandom"),
        (socket, "socket"),
        (subprocess, "Popen"),
    ):
        monkeypatch.setattr(obj, name, forbidden)
    plan = make()
    assert check(plan, observation(plan)) is None
    assert module.make_plan is not None
