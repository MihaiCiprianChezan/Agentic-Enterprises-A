"""The versions enabler — a real, event-sourced version registry + per-version scorecard, and the
Optimizer respecting version status. Offline and deterministic; the M9 Auditor precondition.
"""
from __future__ import annotations

from datetime import datetime, timezone

from cell.cell import Cell
from cell.domain.objects import ActorRef, Output, Ticket
from cell.optimize import CostAwareOptimizer, Implementer
from cell.planes.memory import CostDelta, DurableEventStore, InMemoryEventStore
from cell.versions import VersionRegistry, version_stats

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _Impl:
    def __init__(self, version: str) -> None:
        self.actor = ActorRef("Executor", version)

    def execute(self, item):
        return Output(id=f"out-{item.id}", work_item_id=item.id, artifact_ref="branch:x",
                      produced_by=self.actor, trace_ref="t://x", produced_at=_T0,
                      cost=CostDelta(compute=5))


def _ticket(tid="t"):
    return Ticket(id=tid, source="x", title="t", body="b", received_at=_T0)


def _two_impl_cell(store):
    imps = [Implementer("cheap", 1, _Impl("cheap"), nominal_cost=1.0),
            Implementer("pricey", 1, _Impl("pricey"), nominal_cost=9.0)]
    return Cell.assemble(store=store, optimizer=CostAwareOptimizer(), implementers=imps)


def test_register_and_status_round_trip():
    reg = VersionRegistry(InMemoryEventStore())
    reg.register("Executor", "exec-v1")
    assert reg.status_of("exec-v1") == "active"
    assert reg.records()["exec-v1"].role == "Executor"
    reg.set_status("exec-v1", "suspended")
    assert reg.status_of("exec-v1") == "suspended"


def test_status_of_defaults_active_for_a_version_never_registered():
    reg = VersionRegistry(InMemoryEventStore())
    assert reg.status_of("never-seen") == "active"   # field activity is ground truth


def test_fold_takes_the_latest_status():
    reg = VersionRegistry(InMemoryEventStore())
    reg.register("Executor", "v")
    reg.set_status("v", "suspended")
    reg.set_status("v", "active")
    assert reg.status_of("v") == "active"


def test_registry_is_durable_event_sourced(tmp_path):
    db = str(tmp_path / "state.db")
    VersionRegistry(DurableEventStore(db)).register("Executor", "exec-v1")
    fresh = VersionRegistry(DurableEventStore(db))      # re-read from the durable store
    assert fresh.status_of("exec-v1") == "active"


def test_version_stats_scores_runs_outcomes_and_cost_per_version():
    store = InMemoryEventStore()
    E = lambda v: ActorRef("Executor", v)
    store.append("f", "action", E("v1"), {"stage": "execute", "output_id": "o1", "implementer": "v1"},
                 cost=CostDelta(compute=10))
    store.append("f", "verdict", E("ref"), {"stage": "verify", "output_id": "o1", "decision": "pass"})
    store.append("f", "action", E("v2"), {"stage": "execute", "output_id": "o2", "implementer": "v2"},
                 cost=CostDelta(compute=30))
    store.append("f", "verdict", E("ref"), {"stage": "verify", "output_id": "o2", "decision": "return"})
    stats = version_stats(store.all_events())
    assert stats["v1"].runs == 1 and stats["v1"].passes == 1 and stats["v1"].mean_cost == 10
    assert stats["v2"].returns == 1 and stats["v2"].mean_cost == 30


# --- routing gate + wiring ---------------------------------------------------

def test_assemble_registers_wired_implementer_versions_as_active():
    cell = _two_impl_cell(InMemoryEventStore())
    recs = cell.versions()
    assert recs["cheap"].status == "active" and recs["pricey"].status == "active"


def test_optimizer_skips_a_suspended_version():
    store = InMemoryEventStore()
    cell = _two_impl_cell(store)
    cell.registry.set_status("cheap", "suspended")     # the cheaper one is suspended
    cell.submit(_ticket(), "f")
    route = [e for e in store.read("f") if e.payload.get("stage") == "route"]
    assert route and route[0].payload["chosen"] == "pricey"   # routed to the only active version


def test_version_stats_exposed_on_the_cell():
    store = InMemoryEventStore()
    cell = _two_impl_cell(store)
    cell.submit(_ticket(), "f")
    stats = cell.version_stats()
    assert "cheap" in stats and stats["cheap"].runs == 1 and stats["cheap"].passes == 1
