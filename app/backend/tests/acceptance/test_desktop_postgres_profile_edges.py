"""Additional review cases for profile forgery, Unicode and transport observations."""

from dataclasses import replace

import pytest
from test_desktop_postgres_profile import api, check, make, observation, reject


def test_metadata_forgery_cannot_change_critical_settings():
    plan = make()
    for altered in (
        replace(plan, data_dir="/private/tmp/foreign"),
        replace(plan, postgres_arguments=("-F",)),
        replace(plan, files=dict(plan.files) | {"pg_hba.conf": b"local all all trust\n"}),
        replace(plan, _expected_settings=dict(plan._expected_settings) | {"fsync": "off"}),
    ):
        reject("validation_error", lambda: altered.connection())
        reject("validation_error", lambda: check(altered, observation(plan)))


def test_unicode_identity_and_paths_remain_literal():
    plan = make(system_user="Синтетический Пользователь", postgres_root="/private/tmp/Документы")
    assert plan.files["pg_ident.conf"].decode() == (
        'aira_owner "Синтетический Пользователь" aira_local\n'
    )
    assert plan.data_dir == "/private/tmp/Документы/data18"
    assert check(plan, observation(plan)) is None


@pytest.mark.parametrize("character", ["\u0085", "\u2028", "\u2029", "\u202e", "\ud800"])
def test_hidden_control_and_invalid_unicode_are_not_config_input(character):
    reject("validation_error", lambda: make(system_user="name" + character + "tail"))
    reject("validation_error", lambda: make(postgres_root="/private/tmp/name" + character))


def test_uint64_boundary_is_supported_without_float_conversion():
    plan = make()
    value = observation(plan)
    value["system_identifier"] = str(2**64 - 1)
    assert api().check_observation(plan, value, expected_system_identifier=str(2**64 - 1)) is None
    value["system_identifier"] = str(2**64)
    reject(
        "postgres_mismatch",
        lambda: api().check_observation(plan, value, expected_system_identifier=str(2**64 - 1)),
    )


def test_windows_case_folding_does_not_admit_another_drive_or_parent():
    plan = make(
        target="windows-x86_64",
        postgres_root="C:/Users/Synthetic/AIRA/postgres",
        windows_realm="MACHINE",
        port=65535,
    )
    for replacement in (
        "D:/Users/Synthetic/AIRA/postgres/data18",
        "C:/Users/Synthetic/AIRA/postgres/../data18",
        "C:/Users/Synthetic/AIRA/postgres/data18:stream",
    ):
        value = observation(plan)
        value["settings"]["data_directory"] = replacement
        reject("postgres_mismatch", lambda: check(plan, value))
