"""Code-mode runtime for the Oakland Data MCP.

When the agent calls `python_eval(script)`, the script runs in a sandbox where
this package is importable as `mcp.oakland`. The script writes ordinary Python
that calls these functions and prints results — no async/await boilerplate, no
JSON-string parsing.

Read `oakland_mcp/runtime/README.md` for the agent-facing playbook.
"""
