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

import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass
class RunResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


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
    argv_template: list[str]          # the headless command + subcommand (no prompt — it's stdin)
    permission_args: list[str]        # appended; let an unattended run proceed (don't over-permit)
    instruction_file: str             # CLAUDE.md / AGENTS.md / .github/copilot-instructions.md

    @classmethod
    def claude_code(cls) -> "CliAgentSpec":
        return cls(["claude", "-p"], ["--permission-mode", "acceptEdits"], "CLAUDE.md")

    @classmethod
    def codex(cls) -> "CliAgentSpec":
        return cls(["codex", "exec"], ["--full-auto"], "AGENTS.md")

    @classmethod
    def gemini(cls) -> "CliAgentSpec":
        return cls(["gemini", "-p"], ["--yolo"], "GEMINI.md")

    @classmethod
    def pi(cls) -> "CliAgentSpec":
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
        # Resolve the binary to a full path so subprocess finds it cross-platform — on Windows a
        # CLI agent is often a PATHEXT shim (e.g. npm's claude.CMD) that the bare name won't
        # resolve without a shell; shutil.which honours PATH + PATHEXT.
        resolved = shutil.which(argv[0])
        if resolved is None:
            raise RunnerError(f"CLI agent binary not found: {argv[0]!r}")
        argv = [resolved, *argv[1:]]
        try:
            # The prompt goes on stdin so a multi-line prompt can't break a Windows .CMD shim's
            # argument parsing (which would silently drop the permission flags after it).
            proc = subprocess.run(argv, cwd=cwd, input=prompt, capture_output=True, text=True,
                                  timeout=self.timeout)
        except FileNotFoundError as exc:
            raise RunnerError(f"CLI agent binary not found: {argv[0]!r}") from exc
        except subprocess.TimeoutExpired as exc:
            return RunResult(returncode=124, stdout=exc.stdout or "", stderr=exc.stderr or "",
                             timed_out=True)
        return RunResult(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


class FakeRunner:
    """Deterministic offline runner: applies a canned change to `cwd` and reports success.
    Also the standing proof that the `Runner` seam admits non-Claude implementers."""

    def __init__(self, change: Callable[[str], None]) -> None:
        self._change = change

    def run(self, prompt: str, cwd: str) -> RunResult:
        self._change(cwd)
        return RunResult(returncode=0, stdout="fake-runner: change applied", stderr="")
