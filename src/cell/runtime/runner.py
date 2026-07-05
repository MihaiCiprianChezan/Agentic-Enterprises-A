"""The runtime seam — drive any headless CLI coding agent behind one Protocol.

CLI agentic tools (Claude Code, Codex, Gemini, Pi, Aider…) converged on one shape: a headless
prompt invocation, autonomous editing of the local checkout, and a project instruction file.
They differ only in flags, the instruction-file name, and how they bypass interactive approval
— config, not architecture. So `CliAgentRunner` is one runner parameterized by `CliAgentSpec`;
a new agent is a new preset, not a new class. `FakeRunner` is the offline/test implementer.

Preset flags are best-effort against a fast-moving landscape (Claude Code is the live-verified
default); adjust a preset's args at live time if a CLI changed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from cell.planes.memory import CostDelta


@dataclass
class RunResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    cost: CostDelta | None = None  # the runtime's reported usage (tokens), if its spec parses it


def _claude_usage(stdout: str) -> CostDelta | None:
    """Parse token usage from `claude --output-format json`. Best-effort: returns None on any parse
    failure (the run still works on wall-clock). The exact field path is live-verified on first use."""
    try:
        data = json.loads(stdout)
    except (ValueError, TypeError):
        return None
    usage = data.get("usage") if isinstance(data, dict) else None
    if not isinstance(usage, dict):
        return None

    def _num(x: Any) -> float:
        try:
            return float(x)
        except (TypeError, ValueError):
            return 0.0

    tokens = _num(usage.get("input_tokens")) + _num(usage.get("output_tokens"))
    return CostDelta(compute=tokens, units="tokens") if tokens else None


class RunnerError(Exception):
    """A runtime could not be invoked at all (e.g. its binary is not installed)."""


class Runner(Protocol):
    def run(self, prompt: str, cwd: str) -> RunResult: ...


@dataclass
class CliAgentSpec:
    """What actually differs between CLI agents: how to invoke them headless, the flags that
    let an unattended run proceed without hanging on approval, and the instruction-file name.
    The prompt is delivered on stdin (not as an argv element), so a multi-line prompt can't be
    mangled by a Windows .CMD shim and never appears in the process arg list."""

    argv_template: list[str]  # the headless command + subcommand (no prompt — it's stdin)
    permission_args: list[str]  # appended; let an unattended run proceed (don't over-permit)
    instruction_file: str  # CLAUDE.md / AGENTS.md / .github/copilot-instructions.md
    usage_parser: Callable[[str], CostDelta | None] | None = None  # stdout -> token cost

    @classmethod
    def claude_code(cls) -> CliAgentSpec:
        # --output-format json so token usage can be parsed back into the cost (see _claude_usage).
        return cls(
            ["claude", "-p"],
            ["--permission-mode", "acceptEdits", "--output-format", "json"],
            "CLAUDE.md",
            usage_parser=_claude_usage,
        )

    @classmethod
    def codex(cls) -> CliAgentSpec:
        return cls(["codex", "exec"], ["--full-auto"], "AGENTS.md")

    @classmethod
    def gemini(cls) -> CliAgentSpec:
        return cls(["gemini", "-p"], ["--yolo"], "GEMINI.md")

    @classmethod
    def pi(cls) -> CliAgentSpec:
        return cls(["pi"], [], "AGENTS.md")


def render_argv(spec: CliAgentSpec) -> list[str]:
    """The headless command + permission flags. The prompt is passed on stdin, not here."""
    return list(spec.argv_template) + list(spec.permission_args)


class CliAgentRunner:
    """Runs a headless CLI agent in `cwd`. Surfaces the real failure modes clearly (missing
    binary, non-zero exit, timeout) rather than swallowing them."""

    def __init__(self, spec: CliAgentSpec, *, timeout: int = 600) -> None:
        self.spec = spec
        self.timeout = timeout

    def run(self, prompt: str, cwd: str) -> RunResult:
        argv = render_argv(self.spec)
        if not argv:
            raise RunnerError("CliAgentSpec has no command (empty argv_template)")
        # Resolve the binary to a full path so subprocess finds it cross-platform — on Windows a
        # CLI agent is often a PATHEXT shim (e.g. npm's claude.CMD) that the bare name won't
        # resolve without a shell; shutil.which honours PATH + PATHEXT.
        resolved = shutil.which(argv[0])
        if resolved is None:
            raise RunnerError(f"CLI agent binary not found: {argv[0]!r}")
        argv = [resolved, *argv[1:]]
        try:
            # The prompt goes on stdin so a multi-line prompt can't break a Windows .CMD shim's
            # argument parsing (which would silently drop the permission flags after it). Encoding
            # is pinned to UTF-8 so a non-ASCII prompt is stable across platforms (Windows text
            # mode would otherwise use a locale codepage like cp1252).
            proc = subprocess.run(
                argv,
                cwd=cwd,
                input=prompt,
                capture_output=True,
                encoding="utf-8",
                timeout=self.timeout,
            )
        except FileNotFoundError as exc:
            raise RunnerError(f"CLI agent binary not found: {argv[0]!r}") from exc
        except subprocess.TimeoutExpired as exc:
            # encoding="utf-8" makes this a text-mode run, so any captured output is str
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            return RunResult(returncode=124, stdout=stdout, stderr=stderr, timed_out=True)
        cost = None
        if proc.returncode == 0 and self.spec.usage_parser is not None:
            try:
                cost = self.spec.usage_parser(proc.stdout or "")
            except Exception:
                cost = None  # usage parsing is best-effort — it must never fail a successful run
        return RunResult(
            returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr, cost=cost
        )


class FakeRunner:
    """Deterministic offline runner: applies a canned change to `cwd` and reports success.
    Also the standing proof that the `Runner` seam admits non-Claude implementers."""

    def __init__(self, change: Callable[[str], None]) -> None:
        self._change = change

    def run(self, prompt: str, cwd: str) -> RunResult:
        self._change(cwd)
        return RunResult(returncode=0, stdout="fake-runner: change applied", stderr="")
