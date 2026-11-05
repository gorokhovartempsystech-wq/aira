"""Explicit online licensing client; importing does not probe hardware, files or network."""

from ._identity import parse_smbios_uuid, read_device_id
from ._models import ActivationIdentity, ClientError, Snapshot
from ._runtime import LicenseClient
from ._store import ActivationStore
from ._transport import HttpsTransport

__all__ = [
    "ActivationIdentity",
    "ActivationStore",
    "ClientError",
    "HttpsTransport",
    "LicenseClient",
    "Snapshot",
    "parse_smbios_uuid",
    "read_device_id",
]
