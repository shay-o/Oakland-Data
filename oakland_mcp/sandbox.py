"""Subprocess-based sandbox runner for code-mode `python_eval`.

Runs an agent-authored Python script in a separate Python process. The script
is given:

* The current project on `sys.path` so `from oakland_mcp.runtime import ...`
  works. Inside the script, the agent uses the alias `from mcp.oakland import
  ...` — we install that alias in the bootstrap.
* A wall-clock timeout.
* Captured stdout and stderr, plus a duration in milliseconds.

This is deliberately the simplest thing that could work. It is NOT a security
boundary: the script can read your filesystem and make outbound network
requests. For multi-tenant or untrusted use, swap this implementation for
Vercel Sandbox or another isolated executor — the public function signature
stays the same.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT_SECONDS = 30
MAX_OUTPUT_CHARS = 50_000

# Bootstrap installed ahead of every agent script. Aliases the runtime module
# so the agent can write the natural `from mcp.oakland import ...`. The
# project root is prepended to sys.path explicitly because the subprocess
# runs in `-I` (isolated) mode which ignores PYTHONPATH.
_BOOTSTRAP_TEMPLATE = """\
import sys, types
sys.path.insert(0, {project_root!r})
import oakland_mcp.runtime.oakland as _oakland_runtime
_mcp_pkg = types.ModuleType("mcp")
_mcp_pkg.__path__ = []  # mark as package
sys.modules.setdefault("mcp", _mcp_pkg)
sys.modules["mcp.oakland"] = _oakland_runtime
"""


def _truncate(s: str, n: int = MAX_OUTPUT_CHARS) -> str:
    if len(s) <= n:
        return s
    head = s[: n // 2]
    tail = s[-n // 2 :]
    return f"{head}\n... [truncated {len(s) - n} chars] ...\n{tail}"


async def _run_subprocess(
    script: str,
    timeout: float,
    project_root: Path,
) -> tuple[str, str, int]:
    bootstrap = _BOOTSTRAP_TEMPLATE.format(project_root=str(project_root))
    full_script = bootstrap + "\n" + script

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-I",  # isolate from user site-packages and PYTHON* env vars
        "-c",
        full_script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=os.environ.copy(),
    )

    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        return (
            "",
            f"TimeoutError: script exceeded {timeout:.0f}s timeout and was killed.",
            proc.returncode if proc.returncode is not None else -1,
        )

    return (
        stdout_b.decode("utf-8", errors="replace"),
        stderr_b.decode("utf-8", errors="replace"),
        proc.returncode if proc.returncode is not None else -1,
    )


async def run_script(
    script: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Execute `script` in a subprocess and return its outputs.

    Args:
        script: Python source code authored by the agent.
        timeout: Wall-clock timeout in seconds.
        project_root: Path inserted into PYTHONPATH so the runtime is
            importable. Defaults to the repository root.

    Returns:
        {
            "stdout": str,
            "stderr": str,
            "duration_ms": int,
            "exit_code": int,
        }
    """
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent

    t0 = time.monotonic()
    stdout, stderr, exit_code = await _run_subprocess(
        script=script, timeout=timeout, project_root=project_root,
    )
    duration_ms = int((time.monotonic() - t0) * 1000)

    return {
        "stdout": _truncate(stdout),
        "stderr": _truncate(stderr),
        "duration_ms": duration_ms,
        "exit_code": exit_code,
    }
