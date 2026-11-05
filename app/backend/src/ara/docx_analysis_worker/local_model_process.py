"""Development pipe entrypoint. Native guardian/permit integration is separate."""

import argparse
import sys
from uuid import UUID

from .local_model import run
from .wire import StreamDecoder, WireBinding


def main():
    parser = argparse.ArgumentParser()
    for name in ("models", "engine-root", "run-id", "attempt-id"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    binding = WireBinding(UUID(args.run_id), UUID(args.attempt_id))
    decoder = StreamDecoder(binding, lane="request")
    messages = []
    while chunk := sys.stdin.buffer.read(65536):
        messages.extend(decoder.feed(chunk))
    decoder.finish()
    if len(messages) != 1:
        raise ValueError("Expected one run frame")

    def emit(frame):
        sys.stdout.buffer.write(frame)
        sys.stdout.buffer.flush()

    run(messages[0], model_dir=args.models, engine_dir=args.engine_root, emit=emit)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Do not expose document text or filesystem contents in worker diagnostics.
        print("local_model_failed", file=sys.stderr)
        raise SystemExit(1)
