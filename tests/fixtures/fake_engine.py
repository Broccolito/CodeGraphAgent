"""A fake MCP engine used in proxy tests.

Reads JSON-RPC frames line-by-line from stdin, echoes them back to stdout with
a `"proxied": true` marker injected. Honors a single `{"method": "shutdown"}`
frame to exit cleanly.

Run via: `python -m tests.fixtures.fake_engine`.
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            sys.stderr.write(f"fake_engine: bad json: {line!r}\n")
            sys.stderr.flush()
            continue
        if msg.get("method") == "shutdown":
            return 0
        msg["proxied"] = True
        sys.stdout.write(json.dumps(msg) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
