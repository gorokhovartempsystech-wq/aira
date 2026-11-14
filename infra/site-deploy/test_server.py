import base64
import json
import tempfile
import threading
import unittest
from copy import deepcopy
from http.server import HTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import server
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa


def encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


class DeploymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.claims = {
            "iss": server.ISSUER,
            "aud": server.ORIGIN + server.ENDPOINT,
            "repository": server.REPOSITORY,
            "repository_id": server.REPOSITORY_ID,
            "repository_owner_id": server.OWNER_ID,
            "ref": "refs/heads/main",
            "ref_type": "branch",
            "workflow_ref": server.WORKFLOW,
            "runner_environment": "github-hosted",
            "event_name": "push",
            "iat": 1000,
            "nbf": 1000,
            "exp": 1300,
            "sha": "a" * 40,
            "run_id": "100",
            "run_attempt": "1",
        }
        self.document = {
            "sha": self.claims["sha"],
            "files": {name: "synthetic " + name for name in server.FILES},
        }
        self.verifier = server.Verifier()
        self.verifier.key = lambda _kid: self.private.public_key()

    def token(self, claims=None, private=None):
        header = encode(b'{"alg":"RS256","typ":"JWT","kid":"synthetic"}')
        payload = encode(json.dumps(self.claims if claims is None else claims).encode())
        signed = (header + "." + payload).encode()
        signature = (private or self.private).sign(signed, padding.PKCS1v15(), hashes.SHA256())
        return signed.decode() + "." + encode(signature)

    def test_valid_main_token(self):
        self.assertEqual(self.verifier.verify(self.token(), now=1100), self.claims)

    def test_separate_publishers_require_their_own_workflow_and_audience(self):
        verifier = server.Verifier(workflow="other/main-workflow", audience="other-service")
        verifier.key = self.verifier.key
        with self.assertRaises(ValueError):
            verifier.verify(self.token(), now=1100)
        claims = {**self.claims, "workflow_ref": "other/main-workflow", "aud": "other-service"}
        self.assertEqual(verifier.verify(self.token(claims), now=1100), claims)
        with self.assertRaises(ValueError):
            self.verifier.verify(self.token(claims), now=1100)

    def test_identity_and_lifetime_restrictions(self):
        invalid = {
            "iss": "https://attacker.invalid",
            "aud": "other-service",
            "repository": "someone/aira",
            "repository_id": "1",
            "repository_owner_id": "1",
            "ref": "refs/heads/feature",
            "ref_type": "tag",
            "workflow_ref": server.WORKFLOW.replace("main", "feature"),
            "runner_environment": "self-hosted",
            "event_name": "pull_request",
            "iat": 1200,
            "nbf": 1200,
            "exp": 2000,
            "sha": "bad",
            "run_id": "0",
            "run_attempt": "-1",
        }
        for key, value in invalid.items():
            with self.subTest(key=key):
                claims = {**self.claims, key: value}
                with self.assertRaises(ValueError):
                    self.verifier.verify(self.token(claims), now=1100)
        with self.assertRaises(ValueError):
            self.verifier.verify(self.token(), now=1300)

    def test_invalid_signature_and_unsigned_token(self):
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        with self.assertRaises(InvalidSignature):
            self.verifier.verify(self.token(private=other), now=1100)
        header = encode(b'{"alg":"none","typ":"JWT"}')
        with self.assertRaises(ValueError):
            self.verifier.verify(
                header + "." + encode(json.dumps(self.claims).encode()) + ".", now=1100
            )

    def test_atomic_publish_and_idempotent_retry(self):
        receipt = server.publish(self.root, self.document, self.claims)
        first = (self.root / "current").resolve()
        self.assertEqual(server.publish(self.root, self.document, self.claims), receipt)
        self.assertEqual((self.root / "current").resolve(), first)
        updated = deepcopy(self.document)
        updated["files"]["index.html"] = "updated page"
        next_run = {**self.claims, "run_id": "101"}
        server.publish(self.root, updated, next_run)
        self.assertEqual((self.root / "current/index.html").read_text(), "updated page")
        self.assertEqual((first / "index.html").read_text(), self.document["files"]["index.html"])

    def test_reject_unsafe_files_sha_and_stale_runs_without_changes(self):
        server.publish(self.root, self.document, self.claims)
        first = (self.root / "current").resolve()
        for name in ("../escape", "downloads/installer.exe", "deployment.json", "/etc/passwd"):
            bad = deepcopy(self.document)
            bad["files"][name] = "bad"
            with self.assertRaises(ValueError):
                server.publish(self.root, bad, self.claims)
        bad = deepcopy(self.document)
        bad["sha"] = "b" * 40
        with self.assertRaises(ValueError):
            server.publish(self.root, bad, self.claims)
        bad = deepcopy(self.document)
        bad["files"]["index.html"] = "replayed token with new content"
        with self.assertRaises(ValueError):
            server.publish(self.root, bad, self.claims)
        with self.assertRaises(ValueError):
            server.publish(self.root, self.document, {**self.claims, "run_id": "99"})
        self.assertEqual((self.root / "current").resolve(), first)

    def test_http_unauthorized_request_cannot_write(self):
        handler = type(
            "TestHandler",
            (server.Handler,),
            {
                "root": self.root,
                "verifier": self.verifier,
            },
        )
        http = HTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=http.serve_forever)
        thread.start()
        try:
            request = Request(
                f"http://127.0.0.1:{http.server_port}" + server.ENDPOINT, data=b"{}", method="POST"
            )
            with self.assertRaises(HTTPError) as error:
                urlopen(request, timeout=3)
            self.assertEqual(error.exception.code, 401)
            self.assertFalse((self.root / "current").exists())
        finally:
            http.shutdown()
            thread.join()
            http.server_close()

    def test_http_valid_publication_and_bad_package(self):
        verifier = self.verifier
        original_verify = verifier.verify
        verifier.verify = lambda token: original_verify(token, now=1100)
        handler = type(
            "TestHandler",
            (server.Handler,),
            {
                "root": self.root,
                "verifier": verifier,
            },
        )
        http = HTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=http.serve_forever)
        thread.start()
        try:
            endpoint = f"http://127.0.0.1:{http.server_port}" + server.ENDPOINT
            headers = {
                "Authorization": "Bearer " + self.token(),
                "Content-Type": "application/json",
            }
            request = Request(
                endpoint, data=json.dumps(self.document).encode(), headers=headers, method="POST"
            )
            with urlopen(request, timeout=3) as response:
                receipt = json.load(response)
            self.assertEqual(receipt["sha"], self.claims["sha"])
            previous = (self.root / "current").resolve()
            bad = deepcopy(self.document)
            bad["files"]["../escape"] = "bad"
            request = Request(
                endpoint, data=json.dumps(bad).encode(), headers=headers, method="POST"
            )
            with self.assertRaises(HTTPError) as error:
                urlopen(request, timeout=3)
            self.assertEqual(error.exception.code, 400)
            self.assertEqual((self.root / "current").resolve(), previous)
        finally:
            http.shutdown()
            thread.join()
            http.server_close()


if __name__ == "__main__":
    unittest.main()
