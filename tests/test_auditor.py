"""M9b — the Auditor (rate + report). Rates each version as a population from field activity,
faithful to Constitution Art 11 (danger = safety breach; collapse = regressed/alert-only). Offline.
"""
from __future__ import annotations

from cell.auditor import AUDIT_TRAIL, Auditor
from cell.domain.objects import ActorRef
from cell.planes.memory import CostDelta, InMemoryEventStore
from cell.versions import VersionRegistry

_E = lambda v: ActorRef("Executor", v)
_V = ActorRef("Verifier", "ref")


def _seed_runs(store, flow, version, n_pass, n_total):
    """Append n_total execute+verdict pairs for `version`, n_pass of them passing."""
    for i in range(n_total):
        oid = f"{version}-o{i}"
        store.append(flow, "action", _E(version),
                     {"stage": "execute", "output_id": oid, "implementer": version},
                     cost=CostDelta(compute=5))
        store.append(flow, "verdict", _V,
                     {"stage": "verify", "output_id": oid,
                      "decision": "pass" if i < n_pass else "return"})


def _auditor(store):
    return Auditor(store, VersionRegistry(store))


def test_a_passing_version_with_enough_runs_rates_healthy():
    store = InMemoryEventStore()
    _seed_runs(store, "f", "good", n_pass=5, n_total=5)
    assert _auditor(store).rate()["good"].verdict == "healthy"


def test_too_few_runs_rates_unproven():
    store = InMemoryEventStore()
    _seed_runs(store, "f", "new", n_pass=2, n_total=2)   # < collapse_alert_min_runs (5)
    assert _auditor(store).rate()["new"].verdict == "unproven"


def test_catastrophic_collapse_rates_regressed_not_dangerous():
    store = InMemoryEventStore()
    _seed_runs(store, "f", "bad", n_pass=1, n_total=6)   # pass_rate 0.17 < 0.5 over >=5 runs
    rating = _auditor(store).rate()["bad"]
    assert rating.verdict == "regressed"                 # alert-only, NOT dangerous (Art 11)


def test_a_version_in_an_escalated_flow_rates_dangerous():
    store = InMemoryEventStore()
    _seed_runs(store, "fq", "risky", n_pass=5, n_total=5)   # quality is fine…
    store.append("fq", "escalation", ActorRef("Steward", "ref"),
                 {"stage": "quarantine", "reason": "cost-spiral", "rule": "R8"})  # …but its flow was quarantined
    rating = _auditor(store).rate()["risky"]
    assert rating.verdict == "dangerous"


def test_a_version_worse_than_its_predecessor_rates_regressed():
    store = InMemoryEventStore()
    reg = VersionRegistry(store)
    reg.register("Executor", "v1")
    reg.register("Executor", "v2")
    _seed_runs(store, "f1", "v1", n_pass=5, n_total=5)   # v1: 1.0
    _seed_runs(store, "f2", "v2", n_pass=3, n_total=5)   # v2: 0.6 (above collapse floor, but worse than v1)
    rating = Auditor(store, reg).rate()["v2"]
    assert rating.verdict == "regressed" and rating.vs_predecessor == "worse"


def test_leaderboard_ranks_proven_versions_by_fitness():
    store = InMemoryEventStore()
    _seed_runs(store, "f", "a", n_pass=5, n_total=5)   # 1.0
    _seed_runs(store, "f", "b", n_pass=3, n_total=5)   # 0.6
    board = _auditor(store).leaderboard("Executor")
    assert [r.version for r in board] == ["a", "b"]     # higher pass rate first


def test_report_emits_audit_records_on_the_audit_trail():
    store = InMemoryEventStore()
    _seed_runs(store, "f", "good", n_pass=5, n_total=5)
    _auditor(store).report()
    ratings = [e for e in store.read(AUDIT_TRAIL) if e.payload.get("stage") == "rating"]
    assert ratings and ratings[0].payload["version"] == "good"
    assert ratings[0].payload["verdict"] == "healthy"


def test_the_auditor_takes_no_world_action():
    # Rating a version dangerous must NOT suspend it — 9b reports, 9c acts.
    store = InMemoryEventStore()
    reg = VersionRegistry(store)
    reg.register("Executor", "risky")
    _seed_runs(store, "fq", "risky", n_pass=5, n_total=5)
    store.append("fq", "escalation", ActorRef("Steward", "ref"), {"stage": "quarantine"})
    auditor = Auditor(store, reg)
    assert auditor.rate()["risky"].verdict == "dangerous"
    auditor.report()
    assert reg.status_of("risky") == "active"   # untouched — the Auditor never suspends in 9b


def test_cell_audit_returns_ratings_for_versions_that_ran():
    from datetime import datetime, timezone

    from cell.cell import Cell
    from cell.domain.objects import Ticket
    cell = Cell.assemble(store=InMemoryEventStore())
    cell.submit(Ticket(id="t", source="x", title="t", body="b",
                       received_at=datetime(2026, 1, 1, tzinfo=timezone.utc)), "f")
    ratings = cell.audit()
    assert "ref-v0" in ratings    # the RefExecutor version that ran (unproven on a single run)
