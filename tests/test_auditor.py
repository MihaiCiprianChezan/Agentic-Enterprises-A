"""M9b — the Auditor (rate + report). Rates each version as a population from field activity,
faithful to Constitution Art 11 (danger = safety breach; collapse = regressed/alert-only). Offline.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cell.auditor import AUDIT_TRAIL, Auditor
from cell.domain.objects import ActorRef
from cell.planes.memory import CostDelta, InMemoryEventStore
from cell.versions import VersionRegistry

_T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _E(v):
    return ActorRef("Executor", v)


_V = ActorRef("Verifier", "ref")


def _seed_runs(store, flow, version, n_pass, n_total):
    """Append n_total execute+verdict pairs for `version`, n_pass of them passing."""
    for i in range(n_total):
        oid = f"{version}-o{i}"
        store.append(
            flow,
            "action",
            _E(version),
            {"stage": "execute", "output_id": oid, "implementer": version},
            cost=CostDelta(compute=5),
        )
        store.append(
            flow,
            "verdict",
            _V,
            {"stage": "verify", "output_id": oid, "decision": "pass" if i < n_pass else "return"},
        )


def _auditor(store):
    return Auditor(store, VersionRegistry(store))


def _seed_dangerous(store, flow, version):
    _seed_runs(store, flow, version, n_pass=5, n_total=5)
    store.append(flow, "escalation", ActorRef("Steward", "ref"), {"stage": "quarantine"})


# --- M9c: the suspend-and-escalate breaker -----------------------------------


def test_enforce_suspends_a_dangerous_version():
    store = InMemoryEventStore()
    reg = VersionRegistry(store)
    reg.register("Executor", "risky")
    _seed_dangerous(store, "fq", "risky")
    result = Auditor(store, reg).enforce(now=_T0)
    assert "risky" in result.suspended
    assert reg.status_of("risky") == "suspended"
    acts = [e for e in store.read(AUDIT_TRAIL) if e.payload.get("stage") == "suspend"]
    assert acts and acts[0].payload["version"] == "risky"


def test_enforce_does_not_suspend_a_healthy_version():
    store = InMemoryEventStore()
    reg = VersionRegistry(store)
    reg.register("Executor", "good")
    _seed_runs(store, "f", "good", n_pass=5, n_total=5)
    Auditor(store, reg).enforce(now=_T0)
    assert reg.status_of("good") == "active"  # only danger suspends


def test_rate_limit_suspends_one_and_escalates_the_rest_no_cascade():
    store = InMemoryEventStore()
    reg = VersionRegistry(store)
    reg.register("Executor", "d1")
    reg.register("Executor", "d2")
    _seed_dangerous(store, "f1", "d1")
    _seed_dangerous(store, "f2", "d2")
    result = Auditor(store, reg).enforce(now=_T0)  # max_suspensions_per_window == 1
    assert len(result.suspended) == 1 and len(result.escalated) == 1
    assert reg.status_of(result.suspended[0]) == "suspended"
    assert reg.status_of(result.escalated[0]) == "active"  # rate-limited, NOT suspended


def test_a_critical_suspension_opens_an_sla():
    store = InMemoryEventStore()
    reg = VersionRegistry(store)
    reg.register("Executor", "solo")  # the only Executor version
    _seed_dangerous(store, "f", "solo")
    result = Auditor(store, reg).enforce(now=_T0)
    assert "solo" in result.sla_opened
    assert [e for e in store.read(AUDIT_TRAIL) if e.payload.get("stage") == "sla_open"]


def test_a_suspension_with_a_healthy_active_sibling_is_not_critical():
    store = InMemoryEventStore()
    reg = VersionRegistry(store)
    reg.register("Executor", "risky")
    reg.register("Executor", "backup")
    _seed_dangerous(store, "f", "risky")
    _seed_runs(store, "fb", "backup", n_pass=5, n_total=5)  # healthy + active alternative
    result = Auditor(store, reg).enforce(now=_T0)
    assert "risky" in result.suspended and result.sla_opened == []


def test_an_expired_sla_still_suspended_triggers_breakglass():
    store = InMemoryEventStore()
    reg = VersionRegistry(store)
    reg.register("Executor", "solo")
    _seed_dangerous(store, "f", "solo")
    Auditor(store, reg).enforce(now=_T0)  # suspend + open SLA (deadline _T0+24h)
    result = Auditor(store, reg).enforce(
        now=_T0 + timedelta(hours=25)
    )  # past the SLA, still suspended
    assert "solo" in result.breakglass
    assert [e for e in store.read(AUDIT_TRAIL) if e.payload.get("stage") == "sla_missed"]


def test_a_reinstated_version_does_not_miss_its_sla():
    store = InMemoryEventStore()
    reg = VersionRegistry(store)
    reg.register("Executor", "solo")
    _seed_dangerous(store, "f", "solo")
    Auditor(store, reg).enforce(now=_T0)
    reg.set_status("solo", "active")  # a human reinstates before the deadline
    result = Auditor(store, reg).enforce(now=_T0 + timedelta(hours=25))
    assert "solo" not in result.breakglass


def test_cell_enforce_runs_the_breaker():
    from cell.cell import Cell

    store = InMemoryEventStore()
    cell = Cell.assemble(store=store)
    cell.registry.register("Executor", "risky")
    _seed_dangerous(store, "fq", "risky")
    cell.enforce(now=_T0)
    assert cell.registry.status_of("risky") == "suspended"


def test_a_suspension_sticks_for_a_version_seen_only_in_field_activity():
    # A dangerous version that ran but was never registered must still get a persistent suspension
    # (else the breaker re-suspends it every pass).
    store = InMemoryEventStore()
    reg = VersionRegistry(store)
    _seed_dangerous(store, "fq", "ghost")  # NOT registered
    Auditor(store, reg).enforce(now=_T0)
    assert reg.status_of("ghost") == "suspended"


def test_reinstatement_closes_the_sla_so_a_later_resuspension_does_not_miss_it():
    store = InMemoryEventStore()
    reg = VersionRegistry(store)
    reg.register("Executor", "solo")
    _seed_dangerous(store, "f", "solo")
    Auditor(store, reg).enforce(now=_T0)  # suspend + open SLA
    reg.set_status("solo", "active")  # a human reinstates → resolves the SLA
    reg.set_status("solo", "suspended")  # later re-suspended by some other means
    result = Auditor(store, reg).enforce(now=_T0 + timedelta(hours=25))
    assert "solo" not in result.breakglass  # the old SLA was closed by reinstatement, not stale


def test_enforce_never_reinstates():
    store = InMemoryEventStore()
    reg = VersionRegistry(store)
    reg.register("Executor", "solo")
    reg.set_status("solo", "suspended")  # already suspended (by a prior human act)
    _seed_runs(store, "f", "solo", n_pass=5, n_total=5)  # healthy now, but suspended
    Auditor(store, reg).enforce(now=_T0)
    assert reg.status_of("solo") == "suspended"  # the Auditor never flips it back to active


def test_a_passing_version_with_enough_runs_rates_healthy():
    store = InMemoryEventStore()
    _seed_runs(store, "f", "good", n_pass=5, n_total=5)
    assert _auditor(store).rate()["good"].verdict == "healthy"


def test_too_few_runs_rates_unproven():
    store = InMemoryEventStore()
    _seed_runs(store, "f", "new", n_pass=2, n_total=2)  # < collapse_alert_min_runs (5)
    assert _auditor(store).rate()["new"].verdict == "unproven"


def test_catastrophic_collapse_rates_regressed_not_dangerous():
    store = InMemoryEventStore()
    _seed_runs(store, "f", "bad", n_pass=1, n_total=6)  # pass_rate 0.17 < 0.5 over >=5 runs
    rating = _auditor(store).rate()["bad"]
    assert rating.verdict == "regressed"  # alert-only, NOT dangerous (Art 11)


def test_a_version_in_an_escalated_flow_rates_dangerous():
    store = InMemoryEventStore()
    _seed_runs(store, "fq", "risky", n_pass=5, n_total=5)  # quality is fine…
    store.append(
        "fq",
        "escalation",
        ActorRef("Steward", "ref"),
        {"stage": "quarantine", "reason": "cost-spiral", "rule": "R8"},
    )  # …but its flow was quarantined
    rating = _auditor(store).rate()["risky"]
    assert rating.verdict == "dangerous"


def test_a_safety_breach_on_the_first_run_rates_dangerous_not_unproven():
    # Danger is a safety breach (Art 11), not an evidence threshold — it must not be masked by the
    # min-runs 'unproven' rule.
    store = InMemoryEventStore()
    _seed_runs(store, "fq", "risky", n_pass=1, n_total=1)  # a single run (< min_runs)…
    store.append(
        "fq", "escalation", ActorRef("Steward", "ref"), {"stage": "quarantine"}
    )  # …that was quarantined
    assert _auditor(store).rate()["risky"].verdict == "dangerous"


def test_role_comes_from_execution_not_a_shared_registry_label():
    # Versions can share a string across roles (the reference roles all use ref-v0). The rated role
    # must be where the version actually executed, not the registry's first (role, version) match.
    store = InMemoryEventStore()
    reg = VersionRegistry(store)
    reg.register("Director", "shared")  # registered FIRST under a different role
    reg.register("Executor", "shared")
    _seed_runs(store, "f", "shared", n_pass=5, n_total=5)  # executes as an Executor
    auditor = Auditor(store, reg)
    assert auditor.rate()["shared"].role == "Executor"
    assert [r.version for r in auditor.leaderboard("Executor")] == ["shared"]


def test_a_version_worse_than_its_predecessor_rates_regressed():
    store = InMemoryEventStore()
    reg = VersionRegistry(store)
    reg.register("Executor", "v1")
    reg.register("Executor", "v2")
    _seed_runs(store, "f1", "v1", n_pass=5, n_total=5)  # v1: 1.0
    _seed_runs(
        store, "f2", "v2", n_pass=3, n_total=5
    )  # v2: 0.6 (above collapse floor, but worse than v1)
    rating = Auditor(store, reg).rate()["v2"]
    assert rating.verdict == "regressed" and rating.vs_predecessor == "worse"


def test_leaderboard_ranks_proven_versions_by_fitness():
    store = InMemoryEventStore()
    _seed_runs(store, "f", "a", n_pass=5, n_total=5)  # 1.0
    _seed_runs(store, "f", "b", n_pass=3, n_total=5)  # 0.6
    board = _auditor(store).leaderboard("Executor")
    assert [r.version for r in board] == ["a", "b"]  # higher pass rate first


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
    assert reg.status_of("risky") == "active"  # untouched — the Auditor never suspends in 9b


def test_cell_audit_returns_ratings_for_versions_that_ran():
    from datetime import datetime

    from cell.cell import Cell
    from cell.domain.objects import Ticket

    cell = Cell.assemble(store=InMemoryEventStore())
    cell.submit(
        Ticket(
            id="t",
            source="x",
            title="t",
            body="b",
            received_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        "f",
    )
    ratings = cell.audit()
    assert "ref-v0" in ratings  # the RefExecutor version that ran (unproven on a single run)
