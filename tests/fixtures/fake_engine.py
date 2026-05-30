"""A fake MCP engine for proxy tests.

Behaves enough like the real CodeGraph engine to exercise the intercepting
proxy:
  - initialize → return capabilities
  - tools/list → return a fixed list of fake codegraph_* tools
  - tools/call codegraph_search → return a synthetic search result
  - shutdown → exit 0
  - --exit-code N → consume one frame, exit with code N

Run via: python -m tests.fixtures.fake_engine
"""

from __future__ import annotations

import json
import sys


_FAKE_TOOLS = [
    {"name": "codegraph_search",
     "description": "Search for symbols by name.",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "codegraph_callers",
     "description": "Find callers of a symbol.",
     "inputSchema": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}},
    {"name": "codegraph_status",
     "description": "Index status.",
     "inputSchema": {"type": "object", "properties": {}, "required": []}},
]


def _write(frame: dict) -> None:
    sys.stdout.write(json.dumps(frame) + "\n")
    sys.stdout.flush()


def main(argv: list[str]) -> int:
    if len(argv) >= 3 and argv[1] == "--exit-code":
        sys.stdin.readline()
        return int(argv[2])

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = req.get("method")
        req_id = req.get("id")

        if method == "initialize":
            _write({"jsonrpc": "2.0", "id": req_id, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake-engine", "version": "0.0.1"},
            }})
        elif method == "tools/list":
            _write({"jsonrpc": "2.0", "id": req_id, "result": {"tools": _FAKE_TOOLS}})
        elif method == "tools/call":
            name = req.get("params", {}).get("name")
            args = req.get("params", {}).get("arguments", {})
            if name == "codegraph_search":
                text = f"FAKE search result for query={args.get('query')!r}"
            elif name == "codegraph_callers":
                text = f"FAKE callers result for symbol={args.get('symbol')!r}"
            elif name == "codegraph_status":
                text = "FAKE status: 3 files indexed"
            else:
                text = f"FAKE unknown tool: {name}"
            _write({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": text}],
                "isError": False,
            }})
        elif method == "shutdown":
            _write({"jsonrpc": "2.0", "id": req_id, "result": None})
            return 0
        # Other methods: ignore silently to keep tests simple.

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
