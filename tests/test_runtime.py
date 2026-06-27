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


def test_live_is_opt_in(capsys, monkeypatch):
    monkeypatch.delenv("CELL_LIVE", raising=False)
    from cell import live
    live.main()
    out = capsys.readouterr().out
    assert "opt-in" in out.lower()
