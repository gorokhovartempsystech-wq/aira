"""Native credential-store acceptance using a fresh disposable synthetic record."""
import secrets
import sys
from uuid import uuid4

from ara.model_protection.client import DeviceVault


def main():
    if sys.platform not in {'darwin', 'win32'}:
        raise SystemExit('Native credential store requires macOS or Windows')
    vault = DeviceVault('https://synthetic-license.example')
    identifier, device = uuid4(), 'dv1-' + secrets.token_hex(32)
    key = secrets.token_bytes(32)
    try:
        assert vault.load(identifier, device) is None
        vault.save(identifier, device, key)
        assert vault.load(identifier, device) == key
    finally:
        vault._backend().delete_password('org.aira.device-key.v1', vault._account(identifier, device))
    assert vault.load(identifier, device) is None
    print('Native credential round trip and cleanup passed; no secret output.')


if __name__ == '__main__':
    main()
