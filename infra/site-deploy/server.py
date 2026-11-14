"""A bounded website publisher authenticated by GitHub Actions OIDC."""

import base64
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.request import urlopen

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

REPOSITORY = "gorokhovartempsystech-wq/aira"
REPOSITORY_ID = "1434742176"
OWNER_ID = "277293726"
WORKFLOW = REPOSITORY + "/.github/workflows/site-deploy.yml@refs/heads/main"
ISSUER = "https://token.actions.githubusercontent.com"
ORIGIN = "https://51.250.81.70"
ENDPOINT = "/_deploy/site"
FILES = frozenset(("index.html", "styles.css", "app.js", "favicon.svg", "third-party.txt"))
MAX_BODY = 1024 * 1024
ROOT = Path("/var/lib/aira-site-deploy")


def unbase(value):
    return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)


class Verifier:
    def __init__(self, *, workflow=WORKFLOW, audience=ORIGIN + ENDPOINT):
        self.workflow = workflow
        self.audience = audience
        self.keys = {}
        self.fetched = 0

    def key(self, kid):
        now = time.time()
        if now - self.fetched > 3600 or kid not in self.keys:
            # Never follow a URL supplied by the token.
            with urlopen(ISSUER + "/.well-known/jwks", timeout=10) as response:
                document = json.loads(response.read(128 * 1024))
            self.keys = {key["kid"]: key for key in document["keys"]}
            self.fetched = now
        jwk = self.keys[kid]
        if jwk.get("kty") != "RSA" or jwk.get("alg", "RS256") != "RS256":
            raise ValueError("key")
        return rsa.RSAPublicNumbers(
            int.from_bytes(unbase(jwk["e"]), "big"),
            int.from_bytes(unbase(jwk["n"]), "big"),
        ).public_key()

    def verify(self, token, now=None):
        if len(token) > 16384:
            raise ValueError("token")
        header, payload, signature = token.split(".")
        jose = json.loads(unbase(header))
        claims = json.loads(unbase(payload))
        if jose.get("alg") != "RS256" or jose.get("typ") != "JWT":
            raise ValueError("algorithm")
        self.key(jose["kid"]).verify(
            unbase(signature),
            (header + "." + payload).encode(),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        expected = {
            "iss": ISSUER,
            "aud": self.audience,
            "repository": REPOSITORY,
            "repository_id": REPOSITORY_ID,
            "repository_owner_id": OWNER_ID,
            "ref": "refs/heads/main",
            "ref_type": "branch",
            "workflow_ref": self.workflow,
            "runner_environment": "github-hosted",
        }
        if any(claims.get(key) != value for key, value in expected.items()):
            raise ValueError("identity")
        if claims.get("event_name") not in ("push", "workflow_dispatch"):
            raise ValueError("event")
        now = time.time() if now is None else now
        iat, nbf, exp = (claims[k] for k in ("iat", "nbf", "exp"))
        if not all(type(v) is int for v in (iat, nbf, exp)):
            raise ValueError("time")
        if not (iat <= now + 30 and nbf <= now + 30 and now < exp <= iat + 600):
            raise ValueError("expiry")
        if not re.fullmatch(r"[0-9a-f]{40}", claims.get("sha", "")):
            raise ValueError("commit")
        if not all(
            re.fullmatch(r"[1-9][0-9]{0,19}", claims.get(k, "")) for k in ("run_id", "run_attempt")
        ):
            raise ValueError("run")
        return claims


def publish(root, document, claims):
    if set(document) != {"sha", "files"} or document["sha"] != claims["sha"]:
        raise ValueError("commit mismatch")
    files = document["files"]
    if not isinstance(files, dict) or set(files) != FILES:
        raise ValueError("file allowlist")
    if not all(isinstance(v, str) and v and len(v.encode()) <= 256 * 1024 for v in files.values()):
        raise ValueError("file size")
    encoded = {name: value.encode() for name, value in files.items()}
    digests = {name: hashlib.sha256(value).hexdigest() for name, value in encoded.items()}
    run = [int(claims[k]) for k in ("run_id", "run_attempt")]
    current = root / "current"
    if current.exists():
        previous = json.loads((current / "deployment.json").read_text())
        if run < previous["run"]:
            raise ValueError("stale run")
        if run == previous["run"]:
            if previous["sha"] != claims["sha"] or previous["files"] != digests:
                raise ValueError("run replay with changed content")
            return previous
    releases = root / "releases"
    releases.mkdir(exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="site-", dir=releases))
    receipt = {"sha": claims["sha"], "run": run, "files": digests}
    try:
        for name, value in encoded.items():
            (stage / name).write_bytes(value)
            (stage / name).chmod(0o644)
        (stage / "deployment.json").write_text(json.dumps(receipt, sort_keys=True))
        stage.chmod(0o755)
        # Every public filename points through this one atomic release pointer.
        temporary = root / "next"
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(stage.relative_to(root), target_is_directory=True)
        os.replace(temporary, current)
    except Exception:
        shutil.rmtree(stage)
        raise
    return receipt


class Handler(BaseHTTPRequestHandler):
    verifier = None
    root = ROOT

    def log_message(self, *_args):
        pass  # No token, request headers or uploaded content in logs.

    def setup(self):
        super().setup()
        self.connection.settimeout(20)

    def respond(self, status, value):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != ENDPOINT:
            self.respond(404, {"error": "not found"})
            return
        try:
            authorization = self.headers.get("Authorization", "")
            if not authorization.startswith("Bearer "):
                raise ValueError("missing token")
            claims = self.verifier.verify(authorization[7:])
        except Exception:
            self.respond(401, {"error": "unauthorized"})
            return
        try:
            if (
                self.headers.get("Transfer-Encoding")
                or self.headers.get("Content-Type") != "application/json"
            ):
                raise ValueError("content type")
            length = int(self.headers["Content-Length"])
            if not 0 < length <= MAX_BODY:
                raise ValueError("length")
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("short body")
            result = publish(self.root, json.loads(raw), claims)
        except (ValueError, TypeError, KeyError):
            self.respond(400, {"error": "invalid deployment"})
            return
        except Exception:
            self.respond(500, {"error": "publication failed"})
            return
        self.respond(200, result)


def main():
    Handler.verifier = Verifier()
    HTTPServer(("127.0.0.1", 8768), Handler).serve_forever()


if __name__ == "__main__":
    main()
