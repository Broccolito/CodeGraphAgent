"""CLI entry point for codegraphagent.

This is the [project.scripts] target. It defers the real work to a function
in this module so that `python -m codegraphagent` and the `codegraphagent`
command share the same entrypoint.
"""


def main() -> int:
    """Run the CodeGraphAgent MCP server.

    Returns the process exit code (0 on clean shutdown, non-zero otherwise).
    Real implementation lands in later tasks; for now this is a stub.
    """
    print("codegraphagent: stub — wiring lands in Task E2")
    return 0
