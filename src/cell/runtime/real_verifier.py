"""RealVerifier — run the target repo's tests and score them into a Verdict.

Independent of the Executor (R5): verified_by is the Verifier identity. Robust about the real
failure modes — a red suite, a missing test runner, or a timeout all produce a clear `return`
verdict rather than crashing the flow.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from typing import Literal

from cell.domain.objects import ActorRef, CriterionScore, Goal, Output, Verdict

VERIFIER_ACTOR = ActorRef(role="Verifier", version="real-pytest")


class RealVerifier:
    def __init__(
        self,
        checkout_dir: str,
        *,
        actor: ActorRef = VERIFIER_ACTOR,
        test_cmd: tuple[str, ...] = ("python", "-m", "pytest", "-q"),
        timeout: int = 600,
    ) -> None:
        self.checkout_dir = checkout_dir
        self.actor = actor
        self.test_cmd = list(test_cmd)
        self.timeout = timeout

    def verify(self, output: Output, goal: Goal) -> Verdict:
        passed, detail = self._run_tests()
        decision: Literal["pass", "return"] = "pass" if passed else "return"
        result: Literal["met", "unmet"] = "met" if passed else "unmet"
        return Verdict(
            id=f"verdict-{output.id}",
            output_id=output.id,
            decision=decision,
            scores=[
                CriterionScore(criterion_id=c.id, result=result) for c in goal.acceptance_criteria
            ],
            reason=("tests passed" if passed else f"tests failed:\n{detail[-800:]}"),
            verified_by=self.actor,
            verified_at=datetime.now(UTC),
        )

    def _run_tests(self) -> tuple[bool, str]:
        try:
            proc = subprocess.run(
                self.test_cmd,
                cwd=self.checkout_dir,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except FileNotFoundError:
            return False, f"test runner not found: {self.test_cmd[0]!r}"
        except subprocess.TimeoutExpired:
            return False, f"tests timed out after {self.timeout}s"
        return proc.returncode == 0, proc.stdout + proc.stderr
