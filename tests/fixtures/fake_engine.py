"""A fake MCP engine used in proxy tests.

- Default mode: echo frames back with `"proxied": true`. Exit 0 on `shutdown`.
- `--exit-code N` mode: read one frame, then exit with code N.
"""

from __future__ import annotations

import json
import sys


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "--exit-code":
        sys.stdin.readline()
        return int(argv[2])

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
    sys.exit(main(sys.argv))
