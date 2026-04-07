"""Execute safe shell commands with a blocklist for destructive operations."""
from __future__ import annotations

import asyncio
import re

from ..tool_registry import BaseTool

_PROJECT_ROOT = "/Users/khanh.bui2/Projects/openkhang"
_MAX_TIMEOUT = 30
_DEFAULT_TIMEOUT = 15
_MAX_OUTPUT_CHARS = 5000

# Patterns that are too dangerous to allow via the agent
_BLOCKED_PATTERNS = [
    re.compile(r"\brm\s+(-rf?|-fr?)\b"),                       # recursive delete
    re.compile(r"\bkill\s+(-9|-KILL)\b"),                       # force kill
    re.compile(r"\bgit\s+(push|reset\s+--hard|clean\s+-f)\b"),  # destructive git
    re.compile(r"\bdrop\s+(table|database)\b", re.IGNORECASE),  # SQL drop
    re.compile(r"\btruncate\b", re.IGNORECASE),                 # SQL truncate
    re.compile(r"\bsudo\b"),                                    # privilege escalation
    re.compile(r"\b(mkfs|dd\s+if=)\b"),                        # disk operations
    re.compile(r"\bchmod\s+777\b"),                             # insecure permissions
]


class ShellExecTool(BaseTool):
    """Execute a shell command and return stdout/stderr. Destructive commands are blocked."""

    @property
    def name(self) -> str:
        return "shell_exec"

    @property
    def description(self) -> str:
        return (
            "Execute a shell command and return its output. Useful for checking service status, "
            "querying databases, listing files, or running diagnostic commands. "
            "SAFETY: destructive commands (rm -rf, kill -9, drop, truncate, git push, sudo) are blocked."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to execute",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (max 30)",
                    "default": _DEFAULT_TIMEOUT,
                },
                "working_dir": {
                    "type": "string",
                    "description": "Working directory (defaults to project root)",
                },
            },
            "required": ["command"],
        }

    async def execute(self, **kwargs) -> dict:
        command: str = kwargs["command"]
        timeout: int = min(kwargs.get("timeout", _DEFAULT_TIMEOUT), _MAX_TIMEOUT)
        working_dir: str = kwargs.get("working_dir", _PROJECT_ROOT)

        # Safety check before any execution
        for pattern in _BLOCKED_PATTERNS:
            if pattern.search(command):
                return {
                    "stdout": "",
                    "stderr": "Blocked: this command is potentially destructive. Ask Khanh to run it manually.",
                    "return_code": -1,
                }

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                return {
                    "stdout": "",
                    "stderr": f"Command timed out after {timeout}s",
                    "return_code": -1,
                }
        except Exception as exc:
            return {"stdout": "", "stderr": str(exc), "return_code": -1}

        stdout = _truncate(stdout_bytes.decode(errors="replace"))
        stderr = _truncate(stderr_bytes.decode(errors="replace"))
        return {"stdout": stdout, "stderr": stderr, "return_code": proc.returncode}


def _truncate(text: str) -> str:
    if len(text) > _MAX_OUTPUT_CHARS:
        return text[:_MAX_OUTPUT_CHARS] + f"\n[Truncated — {len(text) - _MAX_OUTPUT_CHARS} chars omitted]"
    return text
