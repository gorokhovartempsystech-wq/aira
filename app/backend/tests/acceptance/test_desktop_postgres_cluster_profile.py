"""Additive profile extension keeps installation identity and legacy defaults."""

from uuid import UUID, uuid4

import pytest

from ara.desktop import postgres_profile


def test_explicit_fresh_socket_identity_keeps_stable_installation():
    installation = uuid4()
    endpoint = uuid4()
    arguments = dict(
        target="macos-arm64",
        installation_id=installation,
        postgres_root="/private/tmp/SYNTHETIC_PRIVATE/postgres",
        system_user="synthetic",
    )
    old = postgres_profile.make_plan(**arguments)
    fresh = postgres_profile.make_plan(**arguments, socket_id=endpoint)
    assert fresh.installation_id == old.installation_id == installation
    assert fresh.socket_root == "/private/tmp/aira-pg-" + endpoint.hex
    assert fresh.connection()["host"] == fresh.socket_root
    assert old.socket_root == "/private/tmp/aira-pg-" + installation.hex
    assert fresh.data_dir == old.data_dir
    assert fresh.files == old.files


@pytest.mark.parametrize("value", ["string", UUID(int=0), True, 42])
def test_invalid_socket_identity_rejected(value):
    with pytest.raises(postgres_profile.ProfileError) as error:
        postgres_profile.make_plan(
            target="macos-arm64",
            installation_id=uuid4(),
            postgres_root="/private/tmp/pg",
            system_user="synthetic",
            socket_id=value,
        )
    assert error.value.code == "validation_error"


def test_windows_does_not_accept_unix_socket_identity():
    with pytest.raises(postgres_profile.ProfileError) as error:
        postgres_profile.make_plan(
            target="windows-x86_64",
            installation_id=uuid4(),
            postgres_root="C:/AIRA/postgres",
            system_user="synthetic",
            windows_realm="MACHINE",
            port=52121,
            socket_id=uuid4(),
        )
    assert error.value.code == "validation_error"
