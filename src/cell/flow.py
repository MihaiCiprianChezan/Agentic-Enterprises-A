"""The one flow — composing the role contracts (M2).

Wires Director → Orchestrator → Executor → Verifier per Role-Contracts.md, binding only
to the Protocols (invariant #1): nothing here knows whether an agent or a human implements
a role. Each handoff is recorded to the event plane (invariant #5), so state lives outside
the actors and any implementer can take over mid-flow.

Scope is M2: composition + swappability + the structural verification gate. Full trace/cost
is M3; the handbrake (pause/inspect/inject/resume) is M4; compiled governance is M5.
"""

from __future__ import annotations

from cell.domain.objects import ActorRef, Ticket, Verdict
from cell.planes.memory import EventStore
from cell.roles.contracts import Director, Executor, Orchestrator, Verifier

# Fallback attribution for the decomposition handoff when the Orchestrator declares no
# identity. Honest ("unattributed") rather than falsely claiming a specific version; a
# role that exposes `.actor` is attributed precisely (see _actor_of).
_UNATTRIBUTED_ORCHESTRATION = ActorRef(role="Orchestrator", version="unattributed")


class NonIndependentVerification(Exception):
    """Raised when a Verdict's `verified_by` equals the Output's `produced_by`. The checker
    must never be the producer (Constitution Art. 5.1; Build-Spec R5)."""


class EmptyDecomposition(Exception):
    """Raised when the Orchestrator yields no work items for a Goal. The flow is total —
    it never returns a None verdict; an empty decomposition is an anomaly to escalate."""


def _actor_of(role, fallback: ActorRef) -> ActorRef:
    """The role's declared identity for attribution, or a fallback. Reads an optional
    `.actor` without widening the Protocol — precise when present, honest when absent."""
    actor = getattr(role, "actor", None)
    return actor if isinstance(actor, ActorRef) else fallback


def run_flow(
    ticket: Ticket,
    director: Director,
    orchestrator: Orchestrator,
    executor: Executor,
    verifier: Verifier,
    store: EventStore,
    flow_id: str,
    *,
    max_revisions: int = 2,
) -> Verdict:
    """Run one ticket end to end and return the decisive Verdict.

    The Director specifies a Goal, the Orchestrator decomposes it into WorkItems, and each
    item runs the produce → score → revise loop. The flow stops at the first non-`pass`
    verdict (a `return` that outlived its revisions, or a `block`); otherwise it returns the
    final `pass`.
    """
    goal = director.specify(ticket)
    store.append(flow_id, "decision", goal.created_by,
                 {"stage": "specify", "goal_id": goal.id, "in_purpose": goal.in_purpose})

    items = orchestrator.decompose(goal)
    orchestrator_actor = _actor_of(orchestrator, _UNATTRIBUTED_ORCHESTRATION)
    store.append(flow_id, "decision", orchestrator_actor,
                 {"stage": "decompose", "work_items": [item.id for item in items]})

    if not items:
        store.append(flow_id, "escalation", orchestrator_actor,
                     {"stage": "decompose", "reason": "empty decomposition", "goal_id": goal.id})
        raise EmptyDecomposition(f"orchestrator produced no work items for goal {goal.id}")

    verdict: Verdict | None = None
    for item in items:
        verdict = _produce_and_verify(item, goal, executor, verifier, store, flow_id, max_revisions)
        if verdict.decision != "pass":
            break  # return (revisions exhausted) or block -> stop here (Art. 5; wiring doc)
    return verdict


def _produce_and_verify(item, goal, executor, verifier, store, flow_id, max_revisions) -> Verdict:
    attempt = 0
    while True:
        output = executor.execute(item)
        store.append(flow_id, "action", output.produced_by,
                     {"stage": "execute", "output_id": output.id, "work_item_id": output.work_item_id,
                      "artifact_ref": output.artifact_ref, "attempt": attempt})

        verdict = verifier.verify(output, goal)
        if verdict.verified_by == output.produced_by:
            raise NonIndependentVerification(
                f"verified_by {verdict.verified_by} must differ from produced_by {output.produced_by}"
            )
        store.append(flow_id, "verdict", verdict.verified_by,
                     {"stage": "verify", "verdict_id": verdict.id, "decision": verdict.decision,
                      "output_id": output.id, "work_item_id": output.work_item_id,
                      "attempt": attempt})

        if verdict.decision == "return" and attempt < max_revisions:
            attempt += 1
            continue  # produce -> score -> revise (Verifier ↔ Executor loop)
        return verdict
