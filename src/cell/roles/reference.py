"""Reference implementations of the operating-role contracts (M2).

Minimal, deterministic implementers that satisfy the Protocols in `contracts.py`.
They exist so the cell can bind to the *contracts* and demonstrate swappability
(invariant #1): any of these can be replaced by another implementer — agent or human —
without touching the others. They are intentionally thin; real Executors/Verifiers
(agent harnesses) slot in behind the same interfaces.

Timestamps are placeholders until the Observability plane stamps real time/cost (M3).
"""

from __future__ import annotations

from datetime import datetime

from cell.domain.objects import (
    ActorRef,
    BudgetCap,
    Criterion,
    CriterionScore,
    Goal,
    Output,
    Ticket,
    Verdict,
    WorkItem,
)

# One active version per role in the MVP (the version-registry stub, Build-Spec §2.4).
DIRECTOR = ActorRef(role="Director", version="ref-v0")
ORCHESTRATOR = ActorRef(role="Orchestrator", version="ref-v0")
EXECUTOR = ActorRef(role="Executor", version="ref-v0")
VERIFIER = ActorRef(role="Verifier", version="ref-v0")

# Per-goal ceiling, Constitution Art. 6.1 (ratified: 250k tokens compute / 15 min wall-clock).
_BUDGET = BudgetCap(compute=250_000, wall_clock_ms=15 * 60 * 1000, units="tokens")
_T0 = datetime(2026, 1, 1)  # placeholder; M3 supplies real timestamps


class RefDirector:
    """Turns a Ticket into a specified, in-purpose Goal with testable acceptance criteria."""

    actor = DIRECTOR

    def specify(self, ticket: Ticket) -> Goal:
        criterion = Criterion(
            id=f"{ticket.id}-c1",
            statement=f"The change resolves: {ticket.title}",
            kind="review",
        )
        return Goal(
            id=f"goal-{ticket.id}",
            ticket_id=ticket.id,
            outcome=ticket.title,
            acceptance_criteria=[criterion],
            budget_cap=_BUDGET,
            created_by=DIRECTOR,
            created_at=ticket.received_at,
            in_purpose=True,
        )


class RefOrchestrator:
    """Decomposes a Goal into sequenced WorkItems and assigns the Executor."""

    actor = ORCHESTRATOR

    def decompose(self, goal: Goal) -> list[WorkItem]:
        return [
            WorkItem(
                id=f"wi-{goal.id}",
                goal_id=goal.id,
                description=f"Implement: {goal.outcome}",
                assigned_to=EXECUTOR,
                action_class="CLASS_OWN_WRITE",
                authority_level="L2",
                acceptance_criteria=list(goal.acceptance_criteria),
            )
        ]


class RefExecutor:
    """Produces the Output (a change on a working branch) for a single WorkItem."""

    actor = EXECUTOR

    def execute(self, item: WorkItem) -> Output:
        return Output(
            id=f"out-{item.id}",
            work_item_id=item.id,
            artifact_ref=f"branch://{item.id}",
            produced_by=EXECUTOR,
            trace_ref=f"trace://{item.id}",
            produced_at=_T0,
        )


class RefVerifier:
    """Independently scores an Output against the Goal's criteria. verified_by is the
    Verifier identity, distinct from the Executor's — Constitution Art. 5.1 / R5."""

    actor = VERIFIER

    def verify(self, output: Output, goal: Goal) -> Verdict:
        scores = [CriterionScore(criterion_id=c.id, result="met") for c in goal.acceptance_criteria]
        return Verdict(
            id=f"verdict-{output.id}",
            output_id=output.id,
            decision="pass",
            scores=scores,
            reason="all acceptance criteria met",
            verified_by=VERIFIER,
            verified_at=_T0,
        )
