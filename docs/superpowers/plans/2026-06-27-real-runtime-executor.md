# Real-Runtime Executor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bind a real CLI coding agent (Claude Code by default) into the cell's Executor seat so a ticket becomes a real code change, verified by real tests, delivered as a real PR through `perform()` (exactly-once) — built deterministically, demonstrated live opt-in.

**Architecture:** A thin runtime package behind the existing Protocols. `CliAgentRunner` (parameterized by `CliAgentSpec`) drives any headless CLI agent; `RealExecutor` (Executor Protocol) turns its edits into an `Output`; `RealVerifier` (Verifier Protocol) runs the target's tests; `deliver_on_pass` opens the PR through `perform()`. No existing `cell/*` module changes.

**Tech Stack:** Python ≥3.11, stdlib only (`subprocess`), pytest. The live runtimes (`claude`, `gh`) and the sandbox repo are external and touched ONLY by the manual runbook.

## Global Constraints

- Python ≥ 3.11; **stdlib only**, no new third-party dependencies.
- Run tests: `python -m pytest -o addopts="" -q`.
- **Athletic, not skeletal and not fat:** each unit does one job *well* — real error handling for the genuine failure modes (non-zero exit, missing binary, empty diff, timeout, missing pytest), clean Protocol-bound interfaces, meaningful returns. No speculative options/retries/queues. No new `Cell`/handbrake seam.
- **Zero changes to existing `cell/*` or `planes/*`** — only NEW files under `src/cell/runtime/`, `src/cell/live.py`, `tests/test_runtime.py`, plus an additive `CLAUDE.md` doc pointer.
- **The offline test suite is deterministic and offline:** `FakeRunner`, temp git repos, and fake effects — NO real LLM, NO network, NO real `gh`, NO real `claude`.
- **Build subagents MUST NOT perform live external actions:** never create a GitHub repo, never run a real `claude -p`, never run a real `gh pr create`. Those belong to the manual runbook (Task 6) only.
- Bind to Protocols (`Runner`, `Executor`, `Verifier`) — invariant #1.
- Branch: `feat/real-runtime-executor` (already created, holds the spec).
- Preset CLI flags (`permission_args`, `argv_template`) are best-effort against a fast-moving landscape; tests verify *rendering mechanics*, not real flags. Claude Code is the live-verified default; others are config-ready presets.

---

### Task 1: The runtime seam — `Runner` Protocol + parameterized CLI-agent runner

**Files:**
- Create: `src/cell/runtime/__init__.py` (empty)
- Create: `src/cell/runtime/runner.py`
- Test: `tests/test_runtime.py`

**Interfaces:**
- Produces: `RunResult(returncode:int, stdout:str, stderr:str, timed_out:bool=False)`; `Runner` Protocol `run(prompt:str, cwd:str)->RunResult`; `RunnerError(Exception)`; `CliAgentSpec(argv_template:list[str], permission_args:list[str], instruction_file:str)` with classmethods `claude_code()/codex()/gemini()/pi()`; `CliAgentRunner(spec:CliAgentSpec, *, timeout:int=600)`; `FakeRunner(change:Callable[[str],None])`; module fn `render_argv(spec, prompt)->list[str]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_runtime.py`:

```python
"""Sub-project B — real-runtime executor. Deterministic, offline: a FakeRunner / temp git
repos / fake effects stand in for the real CLI agent, gh, and sandbox repo. No LLM, no network.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from cell.runtime.runner import (
    CliAgentRunner,
    CliAgentSpec,
    FakeRunner,
    RunnerError,
    RunResult,
    render_argv,
)


def test_claude_preset_renders_argv():
    argv = render_argv(CliAgentSpec.claude_code(), "do the thing")
    assert argv[:3] == ["claude", "-p", "do the thing"]
    assert "--permission-mode" in argv  # permission args appended for unattended runs


def test_runner_runs_a_real_subprocess_in_cwd(tmp_path):
    spec = CliAgentSpec(
        argv_template=["python", "-c", "import pathlib; pathlib.Path('out.txt').write_text('hi')"],
        permission_args=[], instruction_file="X")
    result = CliAgentRunner(spec).run("ignored", str(tmp_path))
    assert result.returncode == 0
    assert (tmp_path / "out.txt").read_text() == "hi"


def test_runner_reports_a_nonzero_exit(tmp_path):
    spec = CliAgentSpec(argv_template=["python", "-c", "import sys; sys.exit(3)"],
                        permission_args=[], instruction_file="X")
    result = CliAgentRunner(spec).run("", str(tmp_path))
    assert result.returncode == 3


def test_runner_raises_on_missing_binary(tmp_path):
    spec = CliAgentSpec(argv_template=["definitely-not-a-real-binary-zzz"],
                        permission_args=[], instruction_file="X")
    with pytest.raises(RunnerError):
        CliAgentRunner(spec).run("", str(tmp_path))


def test_runner_times_out(tmp_path):
    spec = CliAgentSpec(argv_template=["python", "-c", "import time; time.sleep(5)"],
                        permission_args=[], instruction_file="X")
    result = CliAgentRunner(spec, timeout=1).run("", str(tmp_path))
    assert result.timed_out is True


def test_fake_runner_applies_the_change(tmp_path):
    runner = FakeRunner(lambda cwd: Path(cwd, "f.txt").write_text("x"))
    result = runner.run("", str(tmp_path))
    assert result.returncode == 0
    assert (tmp_path / "f.txt").read_text() == "x"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_runtime.py -o addopts="" -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'cell.runtime'`.

- [ ] **Step 3: Create the package marker**

Create `src/cell/runtime/__init__.py` as an empty file.

- [ ] **Step 4: Write the runner**

Create `src/cell/runtime/runner.py`:

```python
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

import subprocess
from dataclasses import dataclass, field
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
    let an unattended run proceed without hanging on approval, and the instruction-file name."""
    argv_template: list[str]          # the literal "{prompt}" element is replaced by the prompt
    permission_args: list[str]        # appended; let an unattended run proceed (don't over-permit)
    instruction_file: str             # CLAUDE.md / AGENTS.md / .github/copilot-instructions.md

    @classmethod
    def claude_code(cls) -> "CliAgentSpec":
        return cls(["claude", "-p", "{prompt}"], ["--permission-mode", "acceptEdits"], "CLAUDE.md")

    @classmethod
    def codex(cls) -> "CliAgentSpec":
        return cls(["codex", "exec", "{prompt}"], ["--full-auto"], "AGENTS.md")

    @classmethod
    def gemini(cls) -> "CliAgentSpec":
        return cls(["gemini", "-p", "{prompt}"], ["--yolo"], "GEMINI.md")

    @classmethod
    def pi(cls) -> "CliAgentSpec":
        return cls(["pi", "{prompt}"], [], "AGENTS.md")


def render_argv(spec: CliAgentSpec, prompt: str) -> list[str]:
    base = [prompt if arg == "{prompt}" else arg for arg in spec.argv_template]
    return base + list(spec.permission_args)


class CliAgentRunner:
    """Runs a headless CLI agent in `cwd`. Surfaces the real failure modes clearly (missing
    binary, non-zero exit, timeout) rather than swallowing them."""

    def __init__(self, spec: CliAgentSpec, *, timeout: int = 600) -> None:
        self.spec = spec
        self.timeout = timeout

    def run(self, prompt: str, cwd: str) -> RunResult:
        argv = render_argv(self.spec, prompt)
        try:
            proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=self.timeout)
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_runtime.py -o addopts="" -q`
Expected: PASS (6 tests).

- [ ] **Step 6: Commit**

```bash
git add src/cell/runtime/__init__.py src/cell/runtime/runner.py tests/test_runtime.py
git commit -m "feat(b): CLI-agent runner seam (Runner Protocol + CliAgentSpec + FakeRunner)"
```

---

### Task 2: `RealExecutor` — turn agent edits into an `Output`

**Files:**
- Create: `src/cell/runtime/real_executor.py`
- Test: `tests/test_runtime.py` (append)

**Interfaces:**
- Consumes: `Runner`, `RunResult` (Task 1); `WorkItem`, `Output`, `ActorRef` (`cell.domain.objects`).
- Produces: `ExecutorError(Exception)`; `RealExecutor(runner:Runner, checkout_dir:str, branch:str, *, actor:ActorRef=EXECUTOR_ACTOR)` with `execute(item:WorkItem)->Output`; `EXECUTOR_ACTOR = ActorRef("Executor","real-cli")`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_runtime.py`:

```python
from datetime import datetime, timezone

from cell.domain.objects import ActorRef, Criterion, WorkItem
from cell.runtime.real_executor import ExecutorError, RealExecutor


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    Path(path, "README.md").write_text("seed\n")
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "seed"],
                   cwd=path, check=True)


def _work_item() -> WorkItem:
    return WorkItem(id="wi-1", goal_id="g-1", description="add greeting.txt",
                    assigned_to=ActorRef("Executor", "x"), action_class="CLASS_OWN_WRITE",
                    authority_level="L2",
                    acceptance_criteria=[Criterion(id="c1", statement="file exists", kind="test")])


def test_real_executor_commits_the_change_and_returns_an_output(tmp_path):
    _init_repo(tmp_path)
    runner = FakeRunner(lambda cwd: Path(cwd, "greeting.txt").write_text("hello"))
    out = RealExecutor(runner, str(tmp_path), "feat/wi-1").execute(_work_item())
    assert out.work_item_id == "wi-1"
    assert out.artifact_ref.startswith("branch:feat/wi-1@")
    log = subprocess.run(["git", "log", "--oneline", "-1"], cwd=tmp_path, capture_output=True, text=True)
    assert "cell:" in log.stdout


def test_real_executor_raises_when_the_agent_makes_no_change(tmp_path):
    _init_repo(tmp_path)
    runner = FakeRunner(lambda cwd: None)  # agent edited nothing
    with pytest.raises(ExecutorError):
        RealExecutor(runner, str(tmp_path), "feat/wi-1").execute(_work_item())


def test_real_executor_raises_on_agent_failure(tmp_path):
    _init_repo(tmp_path)

    class FailingRunner:
        def run(self, prompt, cwd):
            return RunResult(returncode=2, stdout="", stderr="boom")

    with pytest.raises(ExecutorError):
        RealExecutor(FailingRunner(), str(tmp_path), "feat/wi-1").execute(_work_item())
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_runtime.py -o addopts="" -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'cell.runtime.real_executor'`.

- [ ] **Step 3: Write the executor**

Create `src/cell/runtime/real_executor.py`:

```python
"""RealExecutor — bind a CLI agent to the Executor contract.

It does one job: run the agent in a checkout on a working branch, then turn its edits into an
Output. It performs NO external effect (no push, no PR) — that is the cell's job (invariant #4).
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone

from cell.domain.objects import ActorRef, Output, WorkItem
from cell.runtime.runner import Runner

EXECUTOR_ACTOR = ActorRef(role="Executor", version="real-cli")


class ExecutorError(Exception):
    """The agent run failed, or produced no change — surfaced, never swallowed."""


def _git(args: list[str], cwd: str) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise ExecutorError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


class RealExecutor:
    def __init__(self, runner: Runner, checkout_dir: str, branch: str, *,
                 actor: ActorRef = EXECUTOR_ACTOR) -> None:
        self.runner = runner
        self.checkout_dir = checkout_dir
        self.branch = branch
        self.actor = actor

    def execute(self, item: WorkItem) -> Output:
        _git(["checkout", "-B", self.branch], self.checkout_dir)
        result = self.runner.run(self._prompt(item), self.checkout_dir)
        if result.returncode != 0:
            raise ExecutorError(f"agent run failed (rc={result.returncode}): {result.stderr[-500:]}")
        _git(["add", "-A"], self.checkout_dir)
        if not _git(["status", "--porcelain"], self.checkout_dir).strip():
            raise ExecutorError("agent produced no changes")
        _git(["-c", "user.email=cell@local", "-c", "user.name=cell", "commit", "-q", "-m",
              f"cell: {item.description[:60]}"], self.checkout_dir)
        sha = _git(["rev-parse", "HEAD"], self.checkout_dir).strip()
        return Output(
            id=f"out-{item.id}", work_item_id=item.id, artifact_ref=f"branch:{self.branch}@{sha}",
            produced_by=self.actor, trace_ref=f"trace://{item.id}",
            produced_at=datetime.now(timezone.utc), side_effects=[])

    def _prompt(self, item: WorkItem) -> str:
        criteria = "\n".join(f"- {c.statement}" for c in item.acceptance_criteria)
        return (f"Task: {item.description}\n\nAcceptance criteria:\n{criteria}\n\n"
                "Make the change in this repository. Do not commit, push, or open a PR.")
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_runtime.py -o addopts="" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cell/runtime/real_executor.py tests/test_runtime.py
git commit -m "feat(b): RealExecutor turns CLI-agent edits into an Output (no external effect)"
```

---

### Task 3: `RealVerifier` — run the target's tests into a Verdict

**Files:**
- Create: `src/cell/runtime/real_verifier.py`
- Test: `tests/test_runtime.py` (append)

**Interfaces:**
- Consumes: `Output`, `Goal`, `Verdict`, `Criterion`, `CriterionScore`, `ActorRef`, `BudgetCap` (`cell.domain.objects`).
- Produces: `RealVerifier(checkout_dir:str, *, actor:ActorRef=VERIFIER_ACTOR, test_cmd:list[str]=("python","-m","pytest","-q"), timeout:int=600)` with `verify(output:Output, goal:Goal)->Verdict`; `VERIFIER_ACTOR = ActorRef("Verifier","real-pytest")`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_runtime.py`:

```python
from cell.domain.objects import BudgetCap, CriterionScore, Goal, Output, Verdict
from cell.runtime.real_verifier import RealVerifier


def _goal() -> Goal:
    return Goal(id="g-1", ticket_id="t-1", outcome="x",
                acceptance_criteria=[Criterion(id="c1", statement="tests pass", kind="test")],
                budget_cap=BudgetCap(compute=1, wall_clock_ms=1),
                created_by=ActorRef("Director", "x"), created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))


def _output() -> Output:
    return Output(id="out-1", work_item_id="wi-1", artifact_ref="branch:x@1",
                  produced_by=ActorRef("Executor", "x"), trace_ref="t",
                  produced_at=datetime(2026, 1, 1, tzinfo=timezone.utc))


def test_real_verifier_passes_on_green_tests(tmp_path):
    Path(tmp_path, "test_ok.py").write_text("def test_ok():\n    assert 1 == 1\n")
    verdict = RealVerifier(str(tmp_path)).verify(_output(), _goal())
    assert verdict.decision == "pass"
    assert verdict.verified_by != _output().produced_by  # R5 independence


def test_real_verifier_returns_on_red_tests(tmp_path):
    Path(tmp_path, "test_bad.py").write_text("def test_bad():\n    assert 1 == 2\n")
    verdict = RealVerifier(str(tmp_path)).verify(_output(), _goal())
    assert verdict.decision == "return"
    assert "fail" in verdict.reason.lower()
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_runtime.py -o addopts="" -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'cell.runtime.real_verifier'`.

- [ ] **Step 3: Write the verifier**

Create `src/cell/runtime/real_verifier.py`:

```python
"""RealVerifier — run the target repo's tests and score them into a Verdict.

Independent of the Executor (R5): verified_by is the Verifier identity. Robust about the real
failure modes — a red suite, a missing test runner, or a timeout all produce a clear `return`
verdict rather than crashing the flow.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone

from cell.domain.objects import ActorRef, CriterionScore, Goal, Output, Verdict

VERIFIER_ACTOR = ActorRef(role="Verifier", version="real-pytest")


class RealVerifier:
    def __init__(self, checkout_dir: str, *, actor: ActorRef = VERIFIER_ACTOR,
                 test_cmd: tuple[str, ...] = ("python", "-m", "pytest", "-q"),
                 timeout: int = 600) -> None:
        self.checkout_dir = checkout_dir
        self.actor = actor
        self.test_cmd = list(test_cmd)
        self.timeout = timeout

    def verify(self, output: Output, goal: Goal) -> Verdict:
        passed, detail = self._run_tests()
        decision = "pass" if passed else "return"
        result = "met" if passed else "unmet"
        return Verdict(
            id=f"verdict-{output.id}", output_id=output.id, decision=decision,
            scores=[CriterionScore(criterion_id=c.id, result=result) for c in goal.acceptance_criteria],
            reason=("tests passed" if passed else f"tests failed:\n{detail[-800:]}"),
            verified_by=self.actor, verified_at=datetime.now(timezone.utc))

    def _run_tests(self) -> tuple[bool, str]:
        try:
            proc = subprocess.run(self.test_cmd, cwd=self.checkout_dir, capture_output=True,
                                  text=True, timeout=self.timeout)
        except FileNotFoundError:
            return False, f"test runner not found: {self.test_cmd[0]!r}"
        except subprocess.TimeoutExpired:
            return False, f"tests timed out after {self.timeout}s"
        return proc.returncode == 0, proc.stdout + proc.stderr
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_runtime.py -o addopts="" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cell/runtime/real_verifier.py tests/test_runtime.py
git commit -m "feat(b): RealVerifier runs the target tests into a Verdict (R5-independent)"
```

---

### Task 4: `deliver_on_pass` — open the PR through `perform()` (exactly-once)

**Files:**
- Create: `src/cell/runtime/deliver.py`
- Test: `tests/test_runtime.py` (append)

**Interfaces:**
- Consumes: `ActionDescriptor`, `make_idempotency_key`, `perform` (`cell.effects.wrapper`); `Cell` (`cell.cell`) for `.ledger`/`.governance`; `ActorRef`.
- Produces: `open_pr_effect(intent:dict)->str`; `deliver_on_pass(cell, flow_id:str, branch:str, *, actor:ActorRef, title:str, body:str, repo_dir:str, effect=open_pr_effect)->str`; `DELIVERY_ACTOR = ActorRef("Executor","real-cli")`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_runtime.py`:

```python
from cell.cell import Cell
from cell.runtime.deliver import deliver_on_pass


def test_deliver_opens_a_pr_through_perform():
    cell = Cell.assemble()
    calls = {"n": 0}

    def fake_effect(intent):
        calls["n"] += 1
        return "https://github.com/x/y/pull/1"

    actor = ActorRef("Executor", "real-cli")
    url = deliver_on_pass(cell, "f1", "feat/wi-1", actor=actor, title="t", body="b",
                          repo_dir="/tmp/x", effect=fake_effect)
    assert url == "https://github.com/x/y/pull/1"
    assert calls["n"] == 1


def test_deliver_is_exactly_once_on_resume():
    cell = Cell.assemble()
    calls = {"n": 0}

    def fake_effect(intent):
        calls["n"] += 1
        return "https://github.com/x/y/pull/1"

    actor = ActorRef("Executor", "real-cli")
    kw = dict(actor=actor, title="t", body="b", repo_dir="/tmp/x", effect=fake_effect)
    first = deliver_on_pass(cell, "f1", "feat/wi-1", **kw)
    second = deliver_on_pass(cell, "f1", "feat/wi-1", **kw)  # a resume
    assert first == second == "https://github.com/x/y/pull/1"
    assert calls["n"] == 1  # the PR is never opened twice
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_runtime.py -o addopts="" -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'cell.runtime.deliver'`.

- [ ] **Step 3: Write the delivery**

Create `src/cell/runtime/deliver.py`:

```python
"""Delivery — open the PR as the cell's one external effect, through perform().

The agent produced the change; the cell hands it back. Routing the open-PR through perform()
against the cell's durable ledger makes it exactly-once: a crash/resume never opens a second PR
(invariant #4 / M0). The real `gh` mechanics live in open_pr_effect (exercised live); the
idempotency that matters is tested here with a fake effect.
"""

from __future__ import annotations

import subprocess
from typing import Any, Callable

from cell.domain.objects import ActorRef
from cell.effects.wrapper import ActionDescriptor, make_idempotency_key, perform

DELIVERY_ACTOR = ActorRef(role="Executor", version="real-cli")


def open_pr_effect(intent: dict[str, Any]) -> str:
    """Push the branch and open a PR; return the PR URL. Real external effect (live only)."""
    repo_dir, branch = intent["repo_dir"], intent["branch"]
    subprocess.run(["git", "push", "-u", "origin", branch], cwd=repo_dir, check=True,
                   capture_output=True, text=True)
    proc = subprocess.run(
        ["gh", "pr", "create", "--head", branch, "--title", intent["title"], "--body", intent["body"]],
        cwd=repo_dir, check=True, capture_output=True, text=True)
    return proc.stdout.strip()


def deliver_on_pass(cell, flow_id: str, branch: str, *, actor: ActorRef, title: str, body: str,
                    repo_dir: str, effect: Callable[[dict[str, Any]], str] = open_pr_effect) -> str:
    """Open the PR for `branch` exactly-once via the cell's wrapper. Call only on a pass verdict."""
    key = make_idempotency_key(flow_id, "open_pr", {"branch": branch})
    action = ActionDescriptor(
        id=f"deliver-{branch}", action_class="CLASS_VISIBLE_OUTPUT", effect_kind="compensable",
        idempotency_key=key,
        intent={"branch": branch, "title": title, "body": body, "repo_dir": repo_dir})
    return perform(action, actor, lambda a: effect(a.intent), cell.ledger, cell.governance)
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_runtime.py -o addopts="" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cell/runtime/deliver.py tests/test_runtime.py
git commit -m "feat(b): deliver_on_pass opens the PR exactly-once through perform()"
```

---

### Task 5: The live runner (`python -m cell.live`) — opt-in, env-gated

**Files:**
- Create: `src/cell/live.py`
- Test: `tests/test_runtime.py` (append)

**Interfaces:**
- Consumes: `Cell`, `RealExecutor`, `RealVerifier`, `CliAgentRunner`, `CliAgentSpec`, `deliver_on_pass`, `DurableEventStore`, `SqliteEffectsLedger`, `Ticket`, `Paused`.
- Produces: `main()->None` (no-op + notice unless `CELL_LIVE=1`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_runtime.py`:

```python
def test_live_is_opt_in(capsys, monkeypatch):
    monkeypatch.delenv("CELL_LIVE", raising=False)
    from cell import live
    live.main()
    out = capsys.readouterr().out
    assert "opt-in" in out.lower()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_runtime.py::test_live_is_opt_in -o addopts="" -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cell.live'`.

- [ ] **Step 3: Write the live runner**

Create `src/cell/live.py`:

```python
"""The live real-slice runner (python -m cell.live). OPT-IN and env-gated — it performs real
external actions (a real CLI-agent run and a real PR), so it never runs in the test suite.

Required env when CELL_LIVE=1:
  CELL_TARGET_DIR   absolute path to a local checkout of the sandbox repo (with a GitHub remote)
  CELL_TASK         the ticket text (the change to make)
Optional:
  CELL_BRANCH       working branch name (default: cell/slice)

See src/cell/runtime/README.md for the full runbook.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

from cell.cell import Cell
from cell.domain.objects import Ticket
from cell.effects.wrapper import SqliteEffectsLedger
from cell.handbrake import Paused
from cell.planes.memory import DurableEventStore
from cell.runtime.deliver import DELIVERY_ACTOR, deliver_on_pass
from cell.runtime.real_executor import RealExecutor
from cell.runtime.real_verifier import RealVerifier
from cell.runtime.runner import CliAgentRunner, CliAgentSpec


def main() -> None:
    if os.environ.get("CELL_LIVE") != "1":
        print("Live slice is opt-in. Set CELL_LIVE=1 plus CELL_TARGET_DIR and CELL_TASK to run "
              "it (see src/cell/runtime/README.md). It performs a real CLI-agent run and opens a "
              "real PR, so it is never part of the test suite.")
        return

    target = os.environ.get("CELL_TARGET_DIR")
    task = os.environ.get("CELL_TASK")
    if not target or not task:
        print("error: CELL_TARGET_DIR and CELL_TASK are required when CELL_LIVE=1.", file=sys.stderr)
        raise SystemExit(2)
    branch = os.environ.get("CELL_BRANCH", "cell/slice")
    state_db = os.path.join(target, ".cell-state.db")

    cell = Cell.assemble(
        executor=RealExecutor(CliAgentRunner(CliAgentSpec.claude_code()), target, branch),
        verifier=RealVerifier(target),
        store=DurableEventStore(state_db), ledger=SqliteEffectsLedger(state_db))

    ticket = Ticket(id="live-1", source="cli", title=task[:60], body=task,
                    received_at=datetime.now(timezone.utc))
    verdict = cell.submit(ticket, "live-1")
    if isinstance(verdict, Paused):
        print(f"paused at {verdict.step}: {verdict.reason} — inspect via the handbrake.")
        return
    if verdict.decision != "pass":
        print(f"verification did not pass ({verdict.decision}): {verdict.reason}")
        return

    url = deliver_on_pass(cell, "live-1", branch, actor=DELIVERY_ACTOR,
                          title=f"cell: {task[:60]}", body="Opened by the agent-native cell.",
                          repo_dir=target)
    print(f"PASS — pull request opened: {url}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_runtime.py::test_live_is_opt_in -o addopts="" -v`
Expected: PASS (no env set → notice printed, no external action).

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -o addopts="" -q`
Expected: PASS — all tests green, 0 warnings, 0 skips.

- [ ] **Step 6: Commit**

```bash
git add src/cell/live.py tests/test_runtime.py
git commit -m "feat(b): opt-in env-gated live runner (python -m cell.live)"
```

---

### Task 6: Live runbook + doc pointer + final verification & PR

**Files:**
- Create: `src/cell/runtime/README.md`
- Modify: `CLAUDE.md` (layout pointer only)

- [ ] **Step 1: Write the live runbook**

Create `src/cell/runtime/README.md`:

```markdown
# Runtime package — binding a real CLI agent (sub-project B)

The cell drives a real CLI coding agent through the Executor seat. The code here is built and
tested **offline and deterministically** (a `FakeRunner`, temp git repos, fake effects). The
**live** demonstration is opt-in and performs real external actions — run it yourself; it is
never part of CI and is never run by automated agents.

## The faithful split
- The agent (default: Claude Code, `claude -p`) **produces the change** on a working branch.
- The cell **verifies** it (runs the target's tests) and **opens the PR** through `perform()` —
  exactly-once, so a crash/resume never opens two PRs. The cell never merges (L0).

## Running the live slice (manual, opt-in)

1. **Scaffold a sandbox repo** (disposable): a tiny Python package with one failing pytest test
   that fully specifies a small change (the "ticket"), e.g. `slugify()`. Push it to GitHub:
   `gh repo create <you>/cell-sandbox --public --source . --push`.
2. **Clone it locally** and note the path → `CELL_TARGET_DIR`.
3. **Install + authenticate** the agent CLI (`claude`) and `gh` on this machine.
4. **Run it:**
   ```bash
   CELL_LIVE=1 CELL_TARGET_DIR=/path/to/cell-sandbox \
     CELL_TASK="Implement slugify() in src/... so tests/test_slug.py passes." \
     python -m cell.live
   ```
5. **Result:** the agent edits a branch, the cell runs the tests, and on green it prints the PR
   URL. Re-running (or resuming after a kill) opens **no** second PR — the `perform()`/durable
   ledger guarantee on a real GitHub side effect.

## Selecting another runtime
Swap the spec: `CliAgentRunner(CliAgentSpec.codex())` (or `.gemini()` / `.pi()`). Those presets
are config-ready and run through the same runner; confirm their flags on first use (CLIs evolve
fast) and ensure that CLI is installed/authenticated. Claude Code is the live-verified default.
```

- [ ] **Step 2: Add the CLAUDE.md layout pointer**

In `CLAUDE.md`, in the `## Project layout` code block, find the line
`  handbrake.py          # CellHandbrake — the five control primitives on the flow (M4)` and add
immediately after it:

```
  runtime/              # bind a real CLI coding agent to the Executor seat (sub-project B)
  live.py               # opt-in live real-slice runner (CELL_LIVE=1 python -m cell.live)
```

- [ ] **Step 3: Run the full suite**

Run: `python -m pytest -o addopts="" -q`
Expected: PASS — all green, 0 warnings, 0 skips.

- [ ] **Step 4: Commit**

```bash
git add src/cell/runtime/README.md CLAUDE.md
git commit -m "docs(b): live runbook + layout pointer for the runtime package"
```

- [ ] **Step 5: Push and open the PR**

```bash
git push -u origin feat/real-runtime-executor
gh pr create --base main --head feat/real-runtime-executor \
  --title "Sub-project B: real CLI-agent runtime in the Executor seat" \
  --body "Binds a real CLI coding agent (Claude Code default; Codex/Gemini/Pi as presets) behind the Executor Protocol. RealExecutor produces the change; the cell verifies (real pytest) and opens the PR through perform() exactly-once. Thin/athletic, zero changes to existing cell/*. Offline deterministic tests (FakeRunner); the live real-slice run is opt-in (python -m cell.live, see runtime/README.md). Spec: docs/superpowers/specs/2026-06-27-real-runtime-executor-design.md."
```

- [ ] **Step 6: Address Augment review, then merge**

Address valid findings (TDD), comment the resolution, and merge with `gh pr merge <n> --merge --delete-branch`. The live demonstration (Task 6 runbook) is run separately by the user, with explicit confirmation, since it creates real GitHub artifacts and costs tokens.

---

## Notes for the implementer

- **Never run live external commands** (`claude`, real `gh pr create`, `gh repo create`) during the build — the suite uses `FakeRunner`/temp repos/fake effects exclusively. The runbook (Task 6) is documentation; a human runs it.
- The reference roles (`RefDirector`, `RefOrchestrator`) are reused via `Cell.assemble(...)`; only the Executor and Verifier are real. The work item is `CLASS_OWN_WRITE` (L2) → no breakpoint → routine path.
- `Cell` exposes `.ledger` and `.governance` (from sub-project A) — `deliver_on_pass` uses them; do not reach into the handbrake.
- Keep each unit athletic: real error handling for the failure modes shown, nothing speculative beyond them.
```
