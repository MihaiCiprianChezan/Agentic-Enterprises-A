"""The Steward — system role, minimal (M7).

Realizes One-Cell-Build-Plan §6 M7 and Role-Contracts §5. The Steward watches the live flow
for drift / loops / runaway cost and quarantines a misbehaving flow, rolling it back to a
known-good checkpoint. It has full TECHNICAL capability (pause/quarantine, roll back) and
ZERO business-decision authority (Constitution Art. 3.2): it never makes or changes a
decision, approves a work product, or acts in place of Verification.

Rules it enforces, both citing their clause:
  * R7 (Art. 6.1) — when a Goal's running cost reaches its budget cap, quarantine/escalate.
  * R8 (Art. 6.2) — a flow that loops or runs away is quarantined BEFORE it breaches the cap.
R8 is a continuous signal that runs alongside the per-action governance procedure (Build-Spec
§5.3), not inside it.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal

from cell.domain.objects import ActorRef
from cell.planes.observability import total_cost

STEWARD = ActorRef(role="Steward", version="ref-v0")


class InvalidRollback(Exception):
    """A rollback target that is not a real event boundary for the flow — refused, since a
    trail must never claim a restore that cannot be applied."""


@dataclass(frozen=True)
class StewardAction:
    """The outcome of an assessment or intervention, carrying the rule/clause behind it."""

    flow_id: str
    kind: Literal["ok", "quarantine", "rollback"]
    reason: str
    rule: str
    clause: str


class Steward:
    """Monitors a flow and intervenes technically. Has no method to decide, approve, or
    produce work — its authority is deliberately limited to quarantine and rollback."""

    def __init__(self, store: Any, *, loop_threshold: int = 3) -> None:
        self._store = store
        self._loop_threshold = loop_threshold

    # -- monitoring -----------------------------------------------------------

    def assess(self, flow_id: str, budget_cap: Any) -> StewardAction:
        """Inspect the flow's durable trail and quarantine it if the cost cap is reached (R7)
        or a loop is detected (R8). Returns an `ok` action when the flow is healthy."""
        events = self._store.read(flow_id)
        cost = total_cost(events)
        breach = self._cap_breach(cost, budget_cap)
        if breach is not None:
            return self.quarantine(
                flow_id,
                f"running cost reached the budget cap ({breach})",
                rule="R7",
                clause="Art. 6.1",
            )

        attempts = Counter(
            e.payload.get("work_item_id") for e in events if e.payload.get("stage") == "execute"
        )
        if attempts and max(attempts.values()) > self._loop_threshold:
            worst = max(attempts.values())
            return self.quarantine(
                flow_id,
                f"loop: {worst} execute attempts on one work item exceeds {self._loop_threshold}",
                rule="R8",
                clause="Art. 6.2",
            )

        return StewardAction(flow_id, "ok", "healthy", rule="-", clause="-")

    # -- intervention ---------------------------------------------------------

    def quarantine(
        self, flow_id: str, reason: str, *, rule: str = "R8", clause: str = "Art. 6.2"
    ) -> StewardAction:
        """Pause a drifting flow; it may not proceed (Art. 6.2). Recorded on the durable,
        tamper-evident trail and attributed to the Steward."""
        self._store.append(
            flow_id,
            "escalation",
            STEWARD,
            {"stage": "quarantine", "reason": reason, "rule": rule, "clause": clause},
        )
        return StewardAction(flow_id, "quarantine", reason, rule, clause)

    def rollback(self, flow_id: str, to_seq: int) -> StewardAction:
        """Restore the flow to a known-good checkpoint and lift the quarantine. The Steward
        restores state; it never edits a work product (Art. 3.2). `to_seq` must be a real event
        boundary for the flow, or the rollback is refused (no unapplyable restore on the trail)."""
        events = self._store.read(flow_id)
        last_seq = events[-1].seq if events else -1
        if not (0 <= to_seq <= last_seq):
            raise InvalidRollback(
                f"seq {to_seq} is not a valid event boundary for {flow_id!r} (0..{last_seq})"
            )
        self._store.append(flow_id, "state", STEWARD, {"stage": "rollback", "to_seq": to_seq})
        return StewardAction(
            flow_id, "rollback", f"rolled back to seq {to_seq}", rule="R8", clause="Art. 6.2"
        )

    def is_quarantined(self, flow_id: str) -> bool:
        """Quarantine holds until the STEWARD restores a known-good checkpoint. Only the
        Steward's own events toggle it — a coincidental `rollback` stage from an operating role
        cannot de-quarantine a flow."""
        quarantined = False
        for e in self._store.read(flow_id):
            if e.actor.role != STEWARD.role:
                continue
            stage = e.payload.get("stage")
            if stage == "quarantine":
                quarantined = True
            elif stage == "rollback":
                quarantined = False
        return quarantined

    def _cap_breach(self, cost: Any, budget_cap: Any) -> str | None:
        """Rule C2/R7: report the first budget dimension the running cost has reached, or None.
        Checks every dimension of the BudgetCap, not just compute (Build-Spec §3.2)."""
        if budget_cap is None:
            return None
        if cost.units != budget_cap.units:
            # Costs in different units cannot be compared — fail safe and quarantine.
            return f"units {cost.units!r} != budget units {budget_cap.units!r}"
        if cost.compute >= budget_cap.compute:
            return f"compute {cost.compute} >= {budget_cap.compute}"
        if cost.wall_clock_ms >= budget_cap.wall_clock_ms:
            return f"wall_clock_ms {cost.wall_clock_ms} >= {budget_cap.wall_clock_ms}"
        if (
            budget_cap.human_time_ms is not None
            and cost.human_time_ms is not None
            and cost.human_time_ms >= budget_cap.human_time_ms
        ):
            return f"human_time_ms {cost.human_time_ms} >= {budget_cap.human_time_ms}"
        return None
