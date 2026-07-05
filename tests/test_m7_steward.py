"""M7 — the Steward (minimal) (One-Cell-Build-Plan §6; Role-Contracts §5).

The Steward watches the live flow for drift / loops / runaway cost and quarantines a
misbehaving flow, rolling it back to a known-good checkpoint. It has full technical capability
and ZERO business authority (Constitution Art. 3.2). Rules: R7 (at the budget cap →
quarantine, Art. 6.1) and R8 (a loop/runaway is quarantined BEFORE the cap, Art. 6.2).

Acceptance: an induced loop is detected and the flow is quarantined before it burns the
budget cap.
"""

from __future__ import annotations

import pytest

from cell.domain.objects import ActorRef, BudgetCap
from cell.planes.memory import CostDelta, InMemoryEventStore
from cell.planes.observability import total_cost
from cell.steward import InvalidRollback, Steward, StewardAction

EXEC = ActorRef(role="Executor", version="ref-v0")
_BUDGET = BudgetCap(compute=10_000, wall_clock_ms=15 * 60 * 1000, units="tokens")


def _loop(store, flow_id, n, *, per=None, work_item="wi-1"):
    """Simulate a looping flow: n execute attempts on the same work item, each costing `per`."""
    if per is None:
        per = CostDelta(compute=100)
    for i in range(n):
        store.append(
            flow_id,
            "action",
            EXEC,
            {"stage": "execute", "work_item_id": work_item, "attempt": i},
            cost=per,
        )


# --- the acceptance: an induced loop is quarantined before the cap -----------


def test_an_induced_loop_is_quarantined_before_the_budget_cap():
    store = InMemoryEventStore()
    _loop(store, "f1", 5)  # 5 attempts on one work item, 100 each = 500, well under 10_000
    steward = Steward(store, loop_threshold=3)

    action = steward.assess("f1", _BUDGET)

    assert isinstance(action, StewardAction)
    assert action.kind == "quarantine"
    assert action.rule == "R8"
    assert "Art. 6.2" in action.clause
    assert steward.is_quarantined("f1") is True
    # quarantined BEFORE the cap: the running cost is still far under the budget
    assert total_cost(store.read("f1")).compute < _BUDGET.compute


def test_cost_reaching_the_cap_is_quarantined():
    store = InMemoryEventStore()
    _loop(store, "f1", 5, per=CostDelta(compute=100))  # 500
    steward = Steward(store, loop_threshold=99)  # disable loop detection; test the cost rule
    action = steward.assess("f1", BudgetCap(compute=400, wall_clock_ms=1))
    assert action.kind == "quarantine"
    assert action.rule == "R7"
    assert "Art. 6.1" in action.clause


def test_a_healthy_flow_is_not_quarantined():
    store = InMemoryEventStore()
    _loop(store, "f1", 2)  # under the loop threshold and well under cap
    steward = Steward(store, loop_threshold=3)
    action = steward.assess("f1", _BUDGET)
    assert action.kind == "ok"
    assert steward.is_quarantined("f1") is False


# --- quarantine + rollback ---------------------------------------------------


def test_quarantine_is_recorded_on_the_durable_trail():
    store = InMemoryEventStore()
    steward = Steward(store)
    steward.quarantine("f1", "manual", rule="R8", clause="Art. 6.2")
    q = [e for e in store.read("f1") if e.payload.get("stage") == "quarantine"]
    assert q and q[-1].actor.role == "Steward"
    assert store.verify_chain("f1") is True  # tamper-evident (R12)


def test_rollback_restores_and_clears_quarantine():
    store = InMemoryEventStore()
    steward = Steward(store)
    steward.quarantine("f1", "loop")
    assert steward.is_quarantined("f1") is True

    action = steward.rollback("f1", to_seq=0)
    assert action.kind == "rollback"
    assert steward.is_quarantined("f1") is False
    assert any(e.payload.get("stage") == "rollback" for e in store.read("f1"))


def test_steward_acts_are_attributed_to_the_steward():
    # Art. 3.2 / Role-Contracts §5: Steward actions are distinguishable in the trail.
    store = InMemoryEventStore()
    Steward(store).quarantine("f1", "loop")
    steward_events = [e for e in store.read("f1") if e.actor.role == "Steward"]
    assert steward_events


# --- review fixes: multi-dimension cap, validated rollback, scoped quarantine -


def test_wall_clock_cap_is_quarantined_even_when_compute_is_low():
    store = InMemoryEventStore()
    _loop(store, "f1", 5, per=CostDelta(compute=1, wall_clock_ms=100))  # compute 5, wall 500
    steward = Steward(store, loop_threshold=99)  # disable loop detection
    action = steward.assess("f1", BudgetCap(compute=10_000, wall_clock_ms=400))
    assert action.kind == "quarantine"
    assert action.rule == "R7"  # wall-clock dimension reached the cap


def test_rollback_rejects_an_invalid_seq():
    store = InMemoryEventStore()
    steward = Steward(store)
    steward.quarantine("f1", "loop")  # one event, seq 0
    with pytest.raises(InvalidRollback):
        steward.rollback("f1", to_seq=99)  # no such event boundary
    assert steward.is_quarantined("f1") is True  # quarantine not spuriously cleared


def test_quarantine_is_not_cleared_by_a_non_steward_rollback_marker():
    store = InMemoryEventStore()
    steward = Steward(store)
    steward.quarantine("f1", "loop")
    # An operating role emits an event that happens to carry stage "rollback".
    store.append("f1", "state", EXEC, {"stage": "rollback", "to_seq": 0})
    assert steward.is_quarantined("f1") is True  # only the Steward's own rollback clears it
