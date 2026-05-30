"""Custom exception hierarchy for codegraphagent.

These exceptions carry structured detail (URLs, hashes, conflicting paths) so
the degraded-mode error shim can render useful, actionable messages back to
the agent over MCP.
"""

from __future__ import annotations


class CodeGraphAgentError(Exception):
    """Base class for any error originating in the shim itself."""


class LayoutConflictError(CodeGraphAgentError):
    """Raised when the project's .codegraph path exists as something other
    than the symlink we own (e.g. a real directory the user created)."""

    def __init__(self, message: str, *, path: str) -> None:
        super().__init__(message)
        self.path = path


class BootstrapError(CodeGraphAgentError):
    """Raised when the engine bundle could not be downloaded, verified, or
    extracted.

    Optional fields let the error shim show the user exactly what URL was
    attempted and (for SHA mismatches) what was expected vs observed.
    """

    def __init__(
        self,
        message: str,
        *,
        url: str | None = None,
        expected_sha: str | None = None,
        observed_sha: str | None = None,
    ) -> None:
        super().__init__(message)
        self.url = url
        self.expected_sha = expected_sha
        self.observed_sha = observed_sha
