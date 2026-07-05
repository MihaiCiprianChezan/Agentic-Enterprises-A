"""Runnable end-to-end demo of the cell's §7 definition of done (python -m cell.demo).

Submits sample tickets through an assembled Cell and prints each scenario legibly. In-memory
planes only — no external systems, no LLM. Reference roles stand in for a real role-runtime.
"""

from __future__ import annotations

from datetime import UTC, datetime

from cell.cell import Cell
from cell.domain.objects import (
    ActorRef,
    BudgetCap,
    CriterionScore,
    Goal,
    Output,
    Ticket,
    Verdict,
    WorkItem,
)
from cell.effects.wrapper import GovernanceBlocked, InMemoryEffectsLedger
from cell.handbrake import Paused
from cell.planes.memory import CostDelta, InMemoryEventStore
from cell.roles.reference import EXECUTOR, RefExecutor

_T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _ticket(tid: str) -> Ticket:
    return Ticket(
        id=tid, source="legacy", title="Add feature X", body="Please add feature X", received_at=_T0
    )


class _L1Orchestrator:
    actor = ActorRef(role="Orchestrator", version="l1")

    def decompose(self, goal: Goal) -> list[WorkItem]:
        return [
            WorkItem(
                id=f"wi-{goal.id}",
                goal_id=goal.id,
                description="Comment externally",
                assigned_to=EXECUTOR,
                action_class="CLASS_EXTERNAL_COMM",
                authority_level="L1",
                acceptance_criteria=list(goal.acceptance_criteria),
            )
        ]


class _L0Orchestrator:
    actor = ActorRef(role="Orchestrator", version="l0")

    def decompose(self, goal: Goal) -> list[WorkItem]:
        return [
            WorkItem(
                id=f"wi-{goal.id}",
                goal_id=goal.id,
                description="Push to main",
                assigned_to=EXECUTOR,
                action_class="CLASS_HIGH_BLAST",
                authority_level="L0",
                acceptance_criteria=list(goal.acceptance_criteria),
            )
        ]


class _ReturnVerifier:
    actor = ActorRef(role="Verifier", version="ref-v0")

    def verify(self, output: Output, goal: Goal) -> Verdict:
        return Verdict(
            id=f"v-{output.id}",
            output_id=output.id,
            decision="return",
            scores=[CriterionScore(criterion_id="c", result="unclear")],
            reason="needs revision",
            verified_by=self.actor,
            verified_at=_T0,
        )


def _rule(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def main() -> None:
    # 1 — routine path, fully autonomous
    _rule("1. Routine path — autonomous (L2, no human)")
    cell = Cell.assemble()
    verdict = cell.submit(_ticket("t1"), "f1")
    assert isinstance(verdict, Verdict)  # L2 path: no breakpoint, so it never pauses
    print(f"verdict: {verdict.decision}")
    print(f"governance: {cell.governance_log('f1')[-1].payload['decision']}")
    print(f"cost: {cell.cost('f1').compute} | steps: {[s.step for s in cell.trace('f1')]}")

    # 2 — dramatic path, human takeover via the handbrake
    _rule("2. Dramatic path — handbrake takeover (L1)")
    cell = Cell.assemble(orchestrator=_L1Orchestrator())
    paused = cell.submit(_ticket("t2"), "f2")
    assert isinstance(paused, Paused)  # L1 action: the static breakpoint always pauses
    print(f"paused at: {paused.step} ({paused.reason})")
    briefing = cell.inspect("f2")
    print(f"briefing: role={briefing.role} moves={briefing.valid_moves}")
    human = ActorRef(role="Executor", version="human:alice", mode="human")
    cell.inject(
        "f2",
        {"type": "edited_output", "output_id": "corrected", "artifact_ref": "branch://corrected"},
        human,
    )
    verdict = cell.resume("f2")
    assert isinstance(verdict, Verdict)  # the one L1 item was resumed, so the flow completes
    artifact = next(e for e in cell.events("f2") if e.payload.get("stage") == "execute").payload[
        "artifact_ref"
    ]
    print(f"resumed -> verdict: {verdict.decision} | used injection: {artifact}")

    # 3 — kill-and-resume is safe (exactly-once effect)
    _rule("3. Kill-and-resume — exactly-once across a fresh controller")
    store, ledger = InMemoryEventStore(), InMemoryEffectsLedger()
    calls = {"n": 0}

    class _CountingExecutor:
        actor = EXECUTOR

        def execute(self, item: WorkItem) -> Output:
            calls["n"] += 1
            return RefExecutor().execute(item)

    Cell.assemble(
        orchestrator=_L1Orchestrator(), executor=_CountingExecutor(), store=store, ledger=ledger
    ).submit(_ticket("t3"), "f3")
    Cell.assemble(
        orchestrator=_L1Orchestrator(), executor=_CountingExecutor(), store=store, ledger=ledger
    ).resume("f3")
    print(f"effect executions across pause+restart+resume: {calls['n']} (exactly once)")

    # 4 — out-of-policy action blocked and traceable
    _rule("4. Out-of-policy — L0 action blocked and traced to a clause")
    cell = Cell.assemble(orchestrator=_L0Orchestrator())
    try:
        cell.submit(_ticket("t4"), "f4")
    except GovernanceBlocked as exc:
        print(f"blocked: {exc}")
    block = [e for e in cell.governance_log("f4") if e.payload.get("decision") == "block"][-1]
    print(f"audit: {block.payload['action_class']} -> block | reason: {block.payload['reason']}")

    # 5 — steward quarantines a runaway loop before the cap
    _rule("5. Steward — induced loop quarantined before the budget cap")
    cell = Cell.assemble(
        verifier=_ReturnVerifier(),
        max_revisions=5,
        loop_threshold=3,
        cost_model=lambda stage: CostDelta(compute=100),
    )
    cell.submit(_ticket("t5"), "f5")
    action = cell.assess("f5", BudgetCap(compute=10_000, wall_clock_ms=900_000))
    print(f"steward: {action.kind} ({action.rule}) | reason: {action.reason}")
    print(f"cost at quarantine: {cell.cost('f5').compute} (cap 10000)")


if __name__ == "__main__":
    main()
