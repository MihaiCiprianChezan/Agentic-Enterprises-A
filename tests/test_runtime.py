"""Sub-project B — real-runtime executor. Deterministic, offline: a FakeRunner / temp git
repos / fake effects stand in for the real CLI agent, gh, and sandbox repo. No LLM, no network.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cell.cell import Cell
from cell.domain.objects import (
    ActorRef,
    BudgetCap,
    Criterion,
    Goal,
    Output,
    WorkItem,
)
from cell.planes.memory import CostDelta
from cell.runtime.deliver import deliver_on_pass
from cell.runtime.real_executor import ExecutorError, RealExecutor
from cell.runtime.real_verifier import RealVerifier
from cell.runtime.runner import (
    CliAgentRunner,
    CliAgentSpec,
    FakeRunner,
    RunnerError,
    RunResult,
    render_argv,
)


def test_claude_preset_renders_argv():
    # The prompt is NOT an argv element (it goes on stdin); argv is the command + flags, including
    # JSON output so token usage can be parsed back.
    argv = render_argv(CliAgentSpec.claude_code())
    assert argv == ["claude", "-p", "--permission-mode", "acceptEdits", "--output-format", "json"]


def test_claude_preset_parses_token_usage_from_json():
    spec = CliAgentSpec.claude_code()
    assert spec.usage_parser is not None
    cost = spec.usage_parser('{"result":"ok","usage":{"input_tokens":1000,"output_tokens":500}}')
    assert cost.compute == 1500 and cost.units == "tokens"
    assert spec.usage_parser("not json at all") is None  # parse failure → no cost, not a crash


def test_runner_sets_cost_from_the_specs_usage_parser(tmp_path):
    spec = CliAgentSpec(
        argv_template=["python", "-c", "print('TOKENS=7')"],
        permission_args=[],
        instruction_file="X",
        usage_parser=lambda out: CostDelta(compute=7.0) if "TOKENS=7" in out else None,
    )
    res = CliAgentRunner(spec).run("p", str(tmp_path))
    assert res.cost is not None and res.cost.compute == 7.0


def test_runner_survives_a_throwing_usage_parser(tmp_path):
    def boom(_out):
        raise ValueError("bad usage shape")

    spec = CliAgentSpec(
        argv_template=["python", "-c", "print('ok')"],
        permission_args=[],
        instruction_file="X",
        usage_parser=boom,
    )
    res = CliAgentRunner(spec).run("p", str(tmp_path))
    assert res.returncode == 0 and res.cost is None  # best-effort: never fails the run


def test_claude_usage_parser_tolerates_non_numeric_tokens():
    parse = CliAgentSpec.claude_code().usage_parser
    assert parse('{"usage":{"input_tokens":"oops","output_tokens":null}}') is None


def test_real_executor_threads_runner_cost_onto_the_output(tmp_path):
    _init_repo(tmp_path)

    class _CostRunner:
        def run(self, prompt, cwd):
            Path(cwd, "greeting.txt").write_text("hi")
            return RunResult(returncode=0, stdout="", stderr="", cost=CostDelta(compute=123))

    out = RealExecutor(_CostRunner(), str(tmp_path), "feat/wi-1").execute(_work_item())
    assert out.cost is not None and out.cost.compute == 123


def test_runner_passes_the_prompt_on_stdin(tmp_path):
    # The prompt must reach the agent via stdin (so a multi-line prompt can't be mangled by a
    # Windows .CMD shim and the permission flags after it aren't dropped).
    spec = CliAgentSpec(
        argv_template=[
            "python",
            "-c",
            "import sys, pathlib; pathlib.Path('got.txt').write_text(sys.stdin.read())",
        ],
        permission_args=[],
        instruction_file="X",
    )
    CliAgentRunner(spec).run("the real prompt", str(tmp_path))
    assert (tmp_path / "got.txt").read_text() == "the real prompt"


def test_runner_encodes_the_prompt_as_utf8_on_stdin(tmp_path):
    # A non-ASCII prompt must reach the agent as UTF-8 regardless of the platform's locale
    # codepage. The child reads raw bytes so the assertion is deterministic cross-platform.
    spec = CliAgentSpec(
        argv_template=[
            "python",
            "-c",
            "import sys, pathlib; pathlib.Path('got.bin').write_bytes(sys.stdin.buffer.read())",
        ],
        permission_args=[],
        instruction_file="X",
    )
    CliAgentRunner(spec).run("café — slugify ✨", str(tmp_path))
    assert (tmp_path / "got.bin").read_bytes() == "café — slugify ✨".encode()


def test_runner_raises_on_an_empty_argv_template(tmp_path):
    spec = CliAgentSpec(argv_template=[], permission_args=[], instruction_file="X")
    with pytest.raises(RunnerError):
        CliAgentRunner(spec).run("x", str(tmp_path))


def test_runner_runs_a_real_subprocess_in_cwd(tmp_path):
    spec = CliAgentSpec(
        argv_template=["python", "-c", "import pathlib; pathlib.Path('out.txt').write_text('hi')"],
        permission_args=[],
        instruction_file="X",
    )
    result = CliAgentRunner(spec).run("ignored", str(tmp_path))
    assert result.returncode == 0
    assert (tmp_path / "out.txt").read_text() == "hi"


def test_runner_reports_a_nonzero_exit(tmp_path):
    spec = CliAgentSpec(
        argv_template=["python", "-c", "import sys; sys.exit(3)"],
        permission_args=[],
        instruction_file="X",
    )
    result = CliAgentRunner(spec).run("", str(tmp_path))
    assert result.returncode == 3


def test_runner_raises_on_missing_binary(tmp_path):
    spec = CliAgentSpec(
        argv_template=["definitely-not-a-real-binary-zzz"], permission_args=[], instruction_file="X"
    )
    with pytest.raises(RunnerError):
        CliAgentRunner(spec).run("", str(tmp_path))


def test_runner_times_out(tmp_path):
    spec = CliAgentSpec(
        argv_template=["python", "-c", "import time; time.sleep(5)"],
        permission_args=[],
        instruction_file="X",
    )
    result = CliAgentRunner(spec, timeout=1).run("", str(tmp_path))
    assert result.timed_out is True


def test_fake_runner_applies_the_change(tmp_path):
    runner = FakeRunner(lambda cwd: Path(cwd, "f.txt").write_text("x"))
    result = runner.run("", str(tmp_path))
    assert result.returncode == 0
    assert (tmp_path / "f.txt").read_text() == "x"


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    Path(path, "README.md").write_text("seed\n")
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"], cwd=path, check=True
    )
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "seed"],
        cwd=path,
        check=True,
    )


def _work_item() -> WorkItem:
    return WorkItem(
        id="wi-1",
        goal_id="g-1",
        description="add greeting.txt",
        assigned_to=ActorRef("Executor", "x"),
        action_class="CLASS_OWN_WRITE",
        authority_level="L2",
        acceptance_criteria=[Criterion(id="c1", statement="file exists", kind="test")],
    )


def test_real_executor_commits_the_change_and_returns_an_output(tmp_path):
    _init_repo(tmp_path)
    runner = FakeRunner(lambda cwd: Path(cwd, "greeting.txt").write_text("hello"))
    out = RealExecutor(runner, str(tmp_path), "feat/wi-1").execute(_work_item())
    assert out.work_item_id == "wi-1"
    assert out.artifact_ref.startswith("branch:feat/wi-1@")
    log = subprocess.run(
        ["git", "log", "--oneline", "-1"], cwd=tmp_path, capture_output=True, text=True
    )
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


def _goal() -> Goal:
    return Goal(
        id="g-1",
        ticket_id="t-1",
        outcome="x",
        acceptance_criteria=[Criterion(id="c1", statement="tests pass", kind="test")],
        budget_cap=BudgetCap(compute=1, wall_clock_ms=1),
        created_by=ActorRef("Director", "x"),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _output() -> Output:
    return Output(
        id="out-1",
        work_item_id="wi-1",
        artifact_ref="branch:x@1",
        produced_by=ActorRef("Executor", "x"),
        trace_ref="t",
        produced_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


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


def test_deliver_opens_a_pr_through_perform():
    cell = Cell.assemble()
    calls = {"n": 0}

    def fake_effect(intent):
        calls["n"] += 1
        return "https://github.com/x/y/pull/1"

    actor = ActorRef("Executor", "real-cli")
    url = deliver_on_pass(
        cell,
        "f1",
        "feat/wi-1",
        actor=actor,
        title="t",
        body="b",
        repo_dir="/tmp/x",
        effect=fake_effect,
    )
    assert url == "https://github.com/x/y/pull/1"
    assert calls["n"] == 1
    assert any(
        e.kind == "action" and e.payload.get("idempotency_key") for e in cell.store.read("f1")
    )  # the PR-open is on the durable trace


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


def test_deliver_does_not_reopen_a_pr_left_in_flight():
    # at-most-once: if a prior attempt crashed mid gh-pr-create (ledger in_flight), a resume
    # must NOT re-open the PR — it escalates instead.
    from cell.effects.wrapper import IrreversibleInFlight, make_idempotency_key

    cell = Cell.assemble()
    key = make_idempotency_key("f9", "open_pr", {"branch": "feat/wi-1"})
    cell.ledger.put_in_flight(key)  # a prior attempt that crashed mid-effect
    calls = {"n": 0}

    def fake_effect(intent):
        calls["n"] += 1
        return "https://github.com/x/y/pull/1"

    with pytest.raises(IrreversibleInFlight):
        deliver_on_pass(
            cell,
            "f9",
            "feat/wi-1",
            actor=ActorRef("Executor", "real-cli"),
            title="t",
            body="b",
            repo_dir="/tmp/x",
            effect=fake_effect,
        )
    assert calls["n"] == 0  # never re-opened


def test_live_is_opt_in(capsys, monkeypatch):
    monkeypatch.delenv("CELL_LIVE", raising=False)
    from cell import live

    live.main()
    out = capsys.readouterr().out
    assert "opt-in" in out.lower()


def test_real_verifier_returns_when_the_runner_is_missing(tmp_path):
    Path(tmp_path, "test_ok.py").write_text("def test_ok():\n    assert True\n")
    verdict = RealVerifier(str(tmp_path), test_cmd=("definitely-not-a-real-binary-zzz",)).verify(
        _output(), _goal()
    )
    assert verdict.decision == "return"
    assert "not found" in verdict.reason.lower()


def test_real_verifier_returns_on_timeout(tmp_path):
    verdict = RealVerifier(
        str(tmp_path), test_cmd=("python", "-c", "import time; time.sleep(5)"), timeout=1
    ).verify(_output(), _goal())
    assert verdict.decision == "return"
    assert "timed out" in verdict.reason.lower()
