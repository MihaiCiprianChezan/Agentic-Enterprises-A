"""M8 — the Optimizer: capability/cost-aware implementer routing.

A non-authoritative system role (sibling to the Steward): the Steward optimizes for reliability,
the Optimizer for efficiency/capability-fit. It does **selection only, no business decisions**
(model §10) — it matches a work item to the **minimum-cost implementer that still clears the task's
constitutional capability floor**, and may minimize cost only *beneath* that floor, never below it.

The floor is read from governance (`capability_floor`) — constitutional input, not the Optimizer's
judgment. The Optimizer is a pure function; the handbrake records the routing decision so it is
auditable (and recoverable on resume).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from cell.domain.objects import ActorRef, WorkItem
from cell.planes.governance import capability_floor
from cell.roles.contracts import Executor

OPTIMIZER_ACTOR = ActorRef("Optimizer", "ref")  # the non-authoritative system role that routes


@dataclass(frozen=True)
class Implementer:
    """A candidate worker the Optimizer may route to."""

    id: str  # also the executor actor's `version`, so its cost is attributable
    capability_tier: int  # 1 light · 2 standard · 3 strong
    executor: Executor  # the bound implementer (a runtime preset, the reference executor, …)
    nominal_cost: float  # cold-start cost used until attributed history exists


class NoCapableImplementer(Exception):
    """No candidate clears the task's capability floor — escalate; never route below the floor."""


class Optimizer(Protocol):
    def select(
        self, item: WorkItem, candidates: list[Implementer], costs: dict[str, float]
    ) -> Implementer: ...


class CostAwareOptimizer:
    """Picks the cheapest implementer that clears the work item's constitutional capability floor."""

    def select(
        self, item: WorkItem, candidates: list[Implementer], costs: dict[str, float]
    ) -> Implementer:
        floor = capability_floor(item.action_class)
        eligible = [c for c in candidates if c.capability_tier >= floor]
        if not eligible:
            raise NoCapableImplementer(
                f"no implementer clears the tier-{floor} floor for {item.action_class}"
            )
        return min(eligible, key=lambda c: costs.get(c.id, c.nominal_cost))


def mean_cost_for(events, implementer_id: str) -> float | None:
    """The mean attributed `compute` cost of past `execute` events by this implementer. Attribution
    is by the explicit `implementer` tag the handbrake records when it routes (authoritative), with
    a fallback to the executor actor's `version`. None when there is no history (caller uses nominal)."""
    samples = [
        e.cost.compute
        for e in events
        if e.payload.get("stage") == "execute"
        and e.cost is not None
        and (e.payload.get("implementer") or e.actor.version) == implementer_id
    ]
    return sum(samples) / len(samples) if samples else None
