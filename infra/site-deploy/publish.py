"""Run explicitly in GitHub Actions; authenticate without persistent secrets."""

import hashlib
import json
import os
import subprocess
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

FILES = ("index.html", "styles.css", "app.js", "favicon.svg", "third-party.txt")
ORIGIN = "https://51.250.81.70"
ENDPOINT = ORIGIN + "/_deploy/site"


class Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.references = []

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if tag == "script" and "src" in attributes:
            self.references.append(attributes["src"])
        if tag == "link" and attributes.get("rel") in ("stylesheet", "icon"):
            self.references.append(attributes["href"])


def payload():
    root = Path("sites/aira-download")
    files = {name: (root / name).read_text() for name in FILES}
    if any((root / name).is_symlink() for name in FILES):
        raise ValueError("site assets must be regular files")
    parser = Assets()
    parser.feed(files["index.html"])
    if not parser.references or any(
        ref.removeprefix("./").lstrip("/") not in FILES for ref in parser.references
    ):
        raise ValueError("HTML references an unpublished asset")
    subprocess.run(["node", "--check", str(root / "app.js")], check=True)
    return {"sha": os.environ.get("GITHUB_SHA", ""), "files": files}


def main():
    document = payload()
    if os.environ.get("GITHUB_EVENT_NAME") == "pull_request":
        print("Site asset validation passed; PRs do not publish.")
        return
    if os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise SystemExit("Publication is restricted to main.")
    request = Request(
        os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"] + "&" + urlencode({"audience": ENDPOINT}),
        headers={"Authorization": "Bearer " + os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]},
    )
    with urlopen(request, timeout=20) as response:
        token = json.load(response)["value"]
    request = Request(
        ENDPOINT,
        data=json.dumps(document).encode(),
        method="POST",
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    )
    with urlopen(request, timeout=60) as response:
        receipt = json.load(response)
    expected = {
        name: hashlib.sha256(value.encode()).hexdigest()
        for name, value in document["files"].items()
    }
    if receipt["sha"] != document["sha"] or receipt["files"] != expected:
        raise RuntimeError("Deployment receipt mismatch")
    for name, digest in expected.items():
        with urlopen(ORIGIN + "/" + name, timeout=20) as response:
            if hashlib.sha256(response.read()).hexdigest() != digest:
                raise RuntimeError("Public site mismatch: " + name)
    print("Published and verified all five site assets at commit " + document["sha"])


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # urllib exceptions can contain request details. Never print tokens.
        raise SystemExit("Site publication failed: " + type(error).__name__) from None
