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
