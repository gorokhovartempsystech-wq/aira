"""Explicit operator-only provisioning; credentials originate in ~/secrets.env."""

import argparse
import base64
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from dotenv import dotenv_values

REPOSITORY = "gorokhovartempsystech-wq/aira"
PUBLIC_KEY = "1zLepAlzB1jBqkgj68TJgYYVgoGvLhA2U56fD68w/+4="


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upload-signing-secret", action="store_true", required=True)
    parser.parse_args()
    values = dotenv_values(Path.home() / "secrets.env", interpolate=False)
    token = values.get("GITHUB_TOKEN")
    seed = values.get("AIRA_UPDATE_ED25519_SEED")
    if not token or not seed:
        raise SystemExit("Missing GITHUB_TOKEN or AIRA_UPDATE_ED25519_SEED in ~/secrets.env")
    raw = base64.b64decode(seed, validate=True)
    public = (
        Ed25519PrivateKey.from_private_bytes(raw)
        .public_key()
        .public_bytes(Encoding.Raw, PublicFormat.Raw)
    )
    if base64.b64encode(public).decode() != PUBLIC_KEY:
        raise SystemExit("Signing seed does not match the installed update verification key")
    from nacl.public import PublicKey, SealedBox

    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    endpoint = "https://api.github.com/repos/" + REPOSITORY + "/actions/secrets/"
    with urlopen(Request(endpoint + "public-key", headers=headers), timeout=20) as response:
        key = json.load(response)
    encrypted = SealedBox(PublicKey(base64.b64decode(key["key"], validate=True))).encrypt(
        seed.encode()
    )
    body = json.dumps(
        {"key_id": key["key_id"], "encrypted_value": base64.b64encode(encrypted).decode()}
    ).encode()
    request = Request(
        endpoint + "AIRA_UPDATE_ED25519_SEED",
        data=body,
        method="PUT",
        headers={**headers, "Content-Type": "application/json"},
    )
    with urlopen(request, timeout=20) as response:
        if response.status not in (201, 204):
            raise RuntimeError("Secret provisioning failed")
    print("Existing update signing key stored in GitHub Actions; no credentials printed.")


if __name__ == "__main__":
    try:
        main()
    except HTTPError as error:
        raise SystemExit("GitHub secret provisioning failed: HTTP " + str(error.code)) from None
