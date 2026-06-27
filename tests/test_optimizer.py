"""M8 — the Optimizer: capability/cost-aware implementer routing. Offline and deterministic.

The Optimizer routes a work item to the minimum-cost implementer that clears the task's
constitutional capability floor (it may only optimize *beneath* the floor, never below it).
"""
from __future__ import annotations

import pytest

from datetime import datetime, timezone

from cell.cell import Cell
from cell.domain.objects import ActorRef, Output, Ticket, WorkItem
from cell.optimize import CostAwareOptimizer, Implementer, NoCapableImplementer, mean_cost_for
from cell.planes.memory import CostDelta, InMemoryEventStore

_E = object()   # a stand-in executor; select() never calls it
_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _FakeImpl:
    """An executor that tags its Output with its implementer id (so cost is attributable)."""

    def __init__(self, version: str, boom: bool = False) -> None:
        self.actor = ActorRef("Executor", version)
        self._boom = boom

    def execute(self, item):
        if self._boom:
            raise RuntimeError("boom")
        return Output(id=f"out-{item.id}", work_item_id=item.id, artifact_ref="branch:x",
                      produced_by=self.actor, trace_ref="t://x", produced_at=_T0,
                      cost=CostDelta(compute=5))


def _ticket() -> Ticket:
    return Ticket(id="t", source="x", title="t", body="b", received_at=_T0)


def _item(action_class: str = "CLASS_OWN_WRITE") -> WorkItem:
    return WorkItem(id="wi", goal_id="g", description="d", assigned_to=ActorRef("Executor", "x"),
                    action_class=action_class, authority_level="L2", acceptance_criteria=[])


def _imp(id: str, tier: int, nominal: float) -> Implementer:
    return Implementer(id=id, capability_tier=tier, executor=_E, nominal_cost=nominal)


def test_selects_cheapest_implementer_that_clears_the_floor():
    cands = [_imp("strong", 3, 10.0), _imp("light", 1, 2.0), _imp("std", 2, 5.0)]
    chosen = CostAwareOptimizer().select(_item("CLASS_OWN_WRITE"), cands,
                                         {"strong": 10.0, "light": 2.0, "std": 5.0})
    assert chosen.id == "light"   # L2 floor=1: all eligible, cheapest wins


def test_high_blast_floor_excludes_a_cheaper_low_tier_implementer():
    cands = [_imp("strong", 3, 10.0), _imp("light", 1, 1.0)]
    chosen = CostAwareOptimizer().select(_item("CLASS_HIGH_BLAST"), cands,
                                         {"strong": 10.0, "light": 1.0})
    assert chosen.id == "strong"  # L0 floor=3: light excluded though cheapest — never below the floor


def test_no_capable_implementer_raises():
    with pytest.raises(NoCapableImplementer):
        CostAwareOptimizer().select(_item("CLASS_HIGH_BLAST"), [_imp("light", 1, 1.0)], {"light": 1.0})


def test_attributed_cost_falls_back_to_nominal_when_absent():
    # "light" has no attributed cost → uses nominal 2.0; "std" attributed 1.0 wins.
    cands = [_imp("light", 1, 2.0), _imp("std", 1, 99.0)]
    chosen = CostAwareOptimizer().select(_item("CLASS_OWN_WRITE"), cands, {"std": 1.0})
    assert chosen.id == "std"


def test_all_events_reads_across_flows_and_mean_cost_attributes_by_implementer():
    store = InMemoryEventStore()
    E = lambda v: ActorRef("Executor", v)
    store.append("f1", "action", E("claude"), {"stage": "execute"}, cost=CostDelta(compute=100))
    store.append("f2", "action", E("claude"), {"stage": "execute"}, cost=CostDelta(compute=200))
    store.append("f2", "action", E("codex"), {"stage": "execute"}, cost=CostDelta(compute=10))
    events = store.all_events()
    assert len(events) == 3                       # cross-flow read
    assert mean_cost_for(events, "claude") == 150.0
    assert mean_cost_for(events, "codex") == 10.0
    assert mean_cost_for(events, "gemini") is None  # no history → caller uses nominal


# --- handbrake wiring --------------------------------------------------------

def _routed_cell(store, *, boom_cheap=False):
    imps = [Implementer("cheap", 1, _FakeImpl("cheap", boom=boom_cheap), nominal_cost=1.0),
            Implementer("pricey", 1, _FakeImpl("pricey"), nominal_cost=9.0)]
    return Cell.assemble(store=store, optimizer=CostAwareOptimizer(), implementers=imps)


def test_routing_logs_a_route_event_and_attributes_execute_to_the_chosen_implementer():
    store = InMemoryEventStore()
    _routed_cell(store).submit(_ticket(), "f")
    routes = [e for e in store.read("f") if e.payload.get("stage") == "route"]
    assert routes and routes[0].payload["chosen"] == "cheap"     # cheapest above the floor
    execs = [e for e in store.read("f") if e.payload.get("stage") == "execute"]
    assert execs[0].actor.version == "cheap"                      # attribution loop closed


def test_no_routing_with_fewer_than_two_implementers():
    store = InMemoryEventStore()
    cell = Cell.assemble(store=store, optimizer=CostAwareOptimizer(),
                         implementers=[Implementer("only", 1, _FakeImpl("only"), 1.0)])
    cell.submit(_ticket(), "f")
    assert not [e for e in store.read("f") if e.payload.get("stage") == "route"]  # uniform → no router


def test_reentry_reuses_the_recorded_route_assignment():
    store = InMemoryEventStore()
    with pytest.raises(RuntimeError):
        _routed_cell(store, boom_cheap=True).submit(_ticket(), "f")   # crash after route, in execute
    routes1 = [e for e in store.read("f") if e.payload.get("stage") == "route"]
    assert len(routes1) == 1 and routes1[0].payload["chosen"] == "cheap"
    _routed_cell(store).submit(_ticket(), "f")                        # re-enter with cheap working
    routes2 = [e for e in store.read("f") if e.payload.get("stage") == "route"]
    assert len(routes2) == 1                                          # reused, not re-routed


class _MistaggedImpl:
    """An executor whose Output version differs from its Implementer id — attribution must not rely
    on the executor self-tagging; the handbrake tags the execute event with the routed id."""

    def __init__(self) -> None:
        self.actor = ActorRef("Executor", "wrong-version")

    def execute(self, item):
        return Output(id=f"out-{item.id}", work_item_id=item.id, artifact_ref="branch:x",
                      produced_by=self.actor, trace_ref="t://x", produced_at=_T0,
                      cost=CostDelta(compute=7))


def test_execute_is_attributed_to_the_routed_implementer_not_the_executor_actor():
    store = InMemoryEventStore()
    imps = [Implementer("light", 1, _MistaggedImpl(), nominal_cost=1.0),
            Implementer("strong", 3, _FakeImpl("strong"), nominal_cost=9.0)]
    Cell.assemble(store=store, optimizer=CostAwareOptimizer(), implementers=imps).submit(_ticket(), "f")
    execs = [e for e in store.read("f") if e.payload.get("stage") == "execute"]
    assert execs[0].payload.get("implementer") == "light"   # tagged with the routed id
    assert mean_cost_for(store.all_events(), "light") == 7.0  # attributed despite the actor mismatch


def test_resume_with_a_missing_recorded_implementer_falls_back_without_crashing():
    store = InMemoryEventStore()
    with pytest.raises(RuntimeError):
        _routed_cell(store, boom_cheap=True).submit(_ticket(), "f")   # route=cheap, then crash
    other = [Implementer("other", 1, _FakeImpl("other"), 1.0),
             Implementer("another", 1, _FakeImpl("another"), 2.0)]    # re-assembled WITHOUT "cheap"
    v = Cell.assemble(store=store, optimizer=CostAwareOptimizer(), implementers=other).submit(_ticket(), "f")
    assert v.decision == "pass"                                       # degraded gracefully, no KeyError


def test_all_events_is_ordered_by_flow_then_seq():
    store = InMemoryEventStore()
    A = ActorRef("X", "v")
    store.append("zzz", "decision", A, {"stage": "a"})
    store.append("aaa", "decision", A, {"stage": "b"})
    store.append("aaa", "decision", A, {"stage": "c"})
    assert [(e.flow_id, e.seq) for e in store.all_events()] == [("aaa", 0), ("aaa", 1), ("zzz", 0)]
