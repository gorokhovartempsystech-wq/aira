"""One isolated inference process. JSON stdin/stdout; never reads secrets."""

import base64
import json
import sys
import time
from uuid import UUID


def main():
    from aira_ml.engine import Engine

    from ara.ml_review.bridge import review_saved

    request = json.load(sys.stdin)
    model = Engine(request["models"])
    result = review_saved(
        base64.b64decode(request["data"], validate=True),
        UUID(request["document_id"]),
        request["revision"],
        model,
        deadline=time.time() + request["seconds"],
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        code = getattr(exc, "code", "review_failed")
        allowed = {
            "unsupported_document",
            "empty_document",
            "invalid_reply",
            "review_limit_exceeded",
        }
        print(json.dumps({"error": code if code in allowed else "review_failed"}))
        raise SystemExit(1) from None
