"""Native Windows DLL contract check; does not start updater/network/installer."""

import argparse
import ctypes
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sdk", type=Path)
    args = parser.parse_args()
    dll = ctypes.CDLL(str((args.sdk / "x64/Release/WinSparkle.dll").resolve(strict=True)))
    names = (
        "set_app_details",
        "set_appcast_url",
        "set_eddsa_public_key",
        "set_automatic_check_for_updates",
        "set_error_callback",
        "set_did_not_find_update_callback",
        "set_update_cancelled_callback",
        "set_update_dismissed_callback",
        "set_can_shutdown_callback",
        "set_shutdown_request_callback",
        "init",
        "cleanup",
        "check_update_with_ui_and_install",
    )
    for name in names:
        getattr(dll, "win_sparkle_" + name)
    config = json.loads(Path(__file__).with_name("release-config.json").read_text())
    setter = dll.win_sparkle_set_eddsa_public_key
    setter.argtypes = [ctypes.c_char_p]
    setter.restype = ctypes.c_int
    assert setter(b"invalid") == 0
    assert setter(config["public_key"].encode("ascii")) == 1
    print("PASS native WinSparkle exports and public-key acceptance (no installation test)")


if __name__ == "__main__":
    main()
