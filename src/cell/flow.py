"""The one flow — composing the role contracts (M2) with observability (M3).

Wires Director → Orchestrator → Executor → Verifier per Role-Contracts.md, binding only
to the Protocols (invariant #1): nothing here knows whether an agent or a human implements
a role. Each handoff is recorded to the event plane (invariant #5), so state lives outside
the actors and any implementer can take over mid-flow.

When a `recorder` (and optional `cost_model`) is wired, every step also emits a TraceSpan
with its attributable cost (Build-Spec §3, Rule C1), and the events carry that cost too — so
a completed run is fully replayable (M3). With no recorder the flow behaves exactly as M2.

The handbrake (pause/inspect/inject/resume) is M4; compiled governance is M5.
"""

from __future__ import annotations

from typing import Optional

from cell.domain.objects import ActorRef, Ticket, Verdict
from cell.planes.memory import EventStore
from cell.planes.observability import Clock, CostModel, TraceStore, Tracer, digest
from cell.roles.contracts import Director, Executor, Orchestrator, Verifier


class NonIndependentVerification(Exception):
    """Raised when a Verdict's `verified_by` equals the Output's `produced_by`. The checker
    must never be the producer (Constitution Art. 5.1; Build-Spec R5)."""


class EmptyDecomposition(Exception):
    """Raised when the Orchestrator yields no work items for a Goal. The flow is total —
    it never returns a None verdict; an empty decomposition is an anomaly to escalate."""


def _actor_of(role, role_name: str) -> ActorRef:
    """The role's declared identity for attribution, or an honest fallback. Reads an optional
    `.actor` without widening the Protocol — precise when the implementer declares one,
    `<role>/unattributed` when it does not, never a false version claim."""
    actor = getattr(role, "actor", None)
    return actor if isinstance(actor, ActorRef) else ActorRef(role=role_name, version="unattributed")


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
    recorder: Optional[TraceStore] = None,
    cost_model: Optional[CostModel] = None,
    clock: Optional[Clock] = None,
) -> Verdict:
    """Run one ticket end to end and return the decisive Verdict.

    The Director specifies a Goal, the Orchestrator decomposes it into WorkItems, and each
    item runs the produce → score → revise loop. The flow stops at the first non-`pass`
    verdict (a `return` that outlived its revisions, or a `block`); otherwise it returns the
    final `pass`.
    """
    tracer = Tracer(recorder, flow_id, cost_model, clock)

    def ecost(stage: str):
        # Events carry cost only when a model is wired (Rule C1); else None, as in M2.
        return cost_model(stage) if cost_model else None

    with tracer.span("specify", _actor_of(director, "Director"), "decision",
                     input_digest=digest(ticket)) as span:
        goal = director.specify(ticket)
        span.output_digest = digest(goal)
    store.append(flow_id, "decision", goal.created_by,
                 {"stage": "specify", "goal_id": goal.id, "in_purpose": goal.in_purpose},
                 cost=ecost("specify"))

    orchestrator_actor = _actor_of(orchestrator, "Orchestrator")
    with tracer.span("decompose", orchestrator_actor, "decision", input_digest=digest(goal)) as span:
        items = orchestrator.decompose(goal)
        span.output_digest = digest([item.id for item in items])
    store.append(flow_id, "decision", orchestrator_actor,
                 {"stage": "decompose", "work_items": [item.id for item in items]},
                 cost=ecost("decompose"))

    if not items:
        store.append(flow_id, "escalation", orchestrator_actor,
                     {"stage": "decompose", "reason": "empty decomposition", "goal_id": goal.id},
                     cost=ecost("decompose"))
        raise EmptyDecomposition(f"orchestrator produced no work items for goal {goal.id}")

    verdict: Verdict | None = None
    for item in items:
        verdict = _produce_and_verify(item, goal, executor, verifier, store, flow_id,
                                      max_revisions, tracer, ecost)
        if verdict.decision != "pass":
            break  # return (revisions exhausted) or block -> stop here (Art. 5; wiring doc)
    return verdict


def _produce_and_verify(item, goal, executor, verifier, store, flow_id, max_revisions,
                        tracer, ecost) -> Verdict:
    attempt = 0
    while True:
        with tracer.span("execute", _actor_of(executor, "Executor"), "tool_call",
                         input_digest=digest(item.id)) as span:
            output = executor.execute(item)
            span.output_digest = digest(output.id)
        store.append(flow_id, "action", output.produced_by,
                     {"stage": "execute", "output_id": output.id, "work_item_id": output.work_item_id,
                      "artifact_ref": output.artifact_ref, "attempt": attempt}, cost=ecost("execute"))

        with tracer.span("verify", _actor_of(verifier, "Verifier"), "verification",
                         input_digest=digest(output.id)) as span:
            verdict = verifier.verify(output, goal)
            span.output_digest = digest(verdict.id)
        if verdict.verified_by == output.produced_by:
            raise NonIndependentVerification(
                f"verified_by {verdict.verified_by} must differ from produced_by {output.produced_by}"
            )
        store.append(flow_id, "verdict", verdict.verified_by,
                     {"stage": "verify", "verdict_id": verdict.id, "decision": verdict.decision,
                      "output_id": output.id, "work_item_id": output.work_item_id,
                      "attempt": attempt}, cost=ecost("verify"))

        if verdict.decision == "return" and attempt < max_revisions:
            attempt += 1
            continue  # produce -> score -> revise (Verifier ↔ Executor loop)
        return verdict
