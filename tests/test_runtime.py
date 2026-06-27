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
