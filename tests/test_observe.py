"""Tests for the read-only observability inspector (cell.observe).

Offline and deterministic: build a known flow in a temp DurableEventStore, then assert the
inspector interprets it correctly. No network, no real gh, no LLM.
"""

from __future__ import annotations

from cell.domain.objects import ActorRef
from cell.observe import format_summary, format_timeline, main, summarize, verify_chain
from cell.planes.memory import CostDelta, DurableEventStore


def _build_passing_flow(path: str, flow_id: str = "f1") -> DurableEventStore:
    """A faithful one-attempt happy path: specify -> decompose -> govern -> execute -> verdict
    pass -> perform the delivery effect."""
    store = DurableEventStore(path)
    D, ORC, E, V = (
        ActorRef("Director", "ref"),
        ActorRef("Orchestrator", "ref"),
        ActorRef("Executor", "real-cli"),
        ActorRef("Verifier", "ref"),
    )
    store.append(flow_id, "decision", D, {"stage": "specify", "goal_id": "g1", "in_purpose": True})
    store.append(flow_id, "decision", ORC, {"stage": "decompose", "work_items": ["wi1"]})
    store.append(
        flow_id,
        "governance",
        E,
        {
            "stage": "govern",
            "decision": "allow",
            "authority_level": "L2",
            "action_class": "CLASS_OWN_WRITE",
            "reason": "within ceiling",
        },
    )
    store.append(
        flow_id,
        "action",
        E,
        {
            "stage": "execute",
            "output_id": "o1",
            "work_item_id": "wi1",
            "attempt": 1,
            "artifact_ref": "branch:cell/slice@a1b2c3d",
        },
        cost=CostDelta(compute=1200.0),
    )
    store.append(
        flow_id,
        "verdict",
        V,
        {
            "stage": "verify",
            "verdict_id": "v1",
            "output_id": "o1",
            "attempt": 1,
            "decision": "pass",
        },
    )
    store.append(
        flow_id,
        "action",
        E,
        {
            "action_id": "deliver-f1-cell/slice",
            "action_class": "visible_output",
            "effect_kind": "irreversible",
            "idempotency_key": "k-ab12cd34",
            "result_digest": "https://github.com/x/y/pull/1",
        },
    )
    return store


def test_summarize_reports_pass_attempts_rederivations_governance_and_chain(tmp_path):
    store = _build_passing_flow(str(tmp_path / "state.db"))
    s = summarize(store.read("f1"))
    assert s.verdict == "PASS"
    assert s.execute_attempts == 1
    assert s.rederivations == 1  # one specify decision
    assert s.gov_allow == 1 and s.gov_block == 0
    assert s.chain_intact is True
    assert len(s.effects) == 1
    assert s.effects[0].result == "https://github.com/x/y/pull/1"


def test_timeline_shows_the_key_facts(tmp_path):
    store = _build_passing_flow(str(tmp_path / "state.db"))
    out = format_timeline(store.read("f1"))
    assert "execute → branch:cell/slice@a1b2c3d" in out
    assert "PASS" in out
    assert "https://github.com/x/y/pull/1" in out
    # the authority level is the string "L2" in real payloads — render it once, not "LL2"
    assert "ALLOW L2 CLASS_OWN_WRITE" in out
    assert "LL2" not in out


def test_timeline_shows_the_optimizer_route_decision(tmp_path):
    store = DurableEventStore(str(tmp_path / "state.db"))
    store.append(
        "f",
        "decision",
        ActorRef("Optimizer", "ref"),
        {
            "stage": "route",
            "work_item_id": "wi",
            "chosen": "haiku-light",
            "floor": 1,
            "costs": {"haiku-light": 1.0, "opus-strong": 20.0},
        },
    )
    out = format_timeline(store.read("f"))
    assert "route → haiku-light (floor 1)" in out


def test_timeline_shows_version_registry_events(tmp_path):
    store = DurableEventStore(str(tmp_path / "state.db"))
    R = ActorRef("Registry", "ref")
    store.append(
        "__versions__",
        "version",
        R,
        {"stage": "register", "role": "Executor", "version": "exec-v2", "status": "active"},
    )
    store.append(
        "__versions__",
        "version",
        R,
        {"stage": "status", "version": "exec-v2", "status": "suspended"},
    )
    out = format_timeline(store.read("__versions__"))
    assert "register Executor exec-v2 (active)" in out
    assert "status exec-v2 → suspended" in out


def test_timeline_shows_breaker_acts(tmp_path):
    store = DurableEventStore(str(tmp_path / "state.db"))
    A = ActorRef("Auditor", "ref")
    store.append("__audit__", "audit", A, {"stage": "suspend", "version": "risky", "ts": "t"})
    store.append("__audit__", "audit", A, {"stage": "sla_missed", "version": "risky", "ts": "t"})
    out = format_timeline(store.read("__audit__"))
    assert "SUSPEND risky" in out
    assert "SLA-MISSED → break-glass risky" in out


def test_timeline_shows_auditor_ratings(tmp_path):
    store = DurableEventStore(str(tmp_path / "state.db"))
    store.append(
        "__audit__",
        "audit",
        ActorRef("Auditor", "ref"),
        {"stage": "rating", "version": "cheap", "verdict": "healthy", "pass_rate": 1.0},
    )
    out = format_timeline(store.read("__audit__"))
    assert "rating cheap: healthy" in out


def test_tampered_payload_breaks_the_chain_and_is_surfaced(tmp_path):
    import json as _json
    import sqlite3

    db = str(tmp_path / "state.db")
    store = _build_passing_flow(db)
    assert verify_chain(store.read("f1")) == (True, None)
    store.close()  # release the write lock before tampering
    # Rewrite the execute event's payload (seq 3) so its stored hash no longer matches.
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE events SET payload = ? WHERE flow_id = 'f1' AND seq = 3",
        (_json.dumps({"stage": "execute", "artifact_ref": "branch:EVIL"}),),
    )
    conn.commit()
    conn.close()
    tampered = DurableEventStore(db).read("f1")
    assert verify_chain(tampered) == (False, 3)
    s = summarize(tampered)
    assert s.chain_intact is False and s.chain_broken_at == 3
    assert "BROKEN at seq 3" in format_summary(s)


def test_cli_lists_flows_when_no_flow_id(tmp_path, capsys):
    db = str(tmp_path / "state.db")
    _build_passing_flow(db, "live-1")
    rc = main([db])
    assert rc == 0
    assert "live-1" in capsys.readouterr().out


def test_cli_unknown_flow_id_exits_2(tmp_path):
    db = str(tmp_path / "state.db")
    _build_passing_flow(db)
    assert main([db, "does-not-exist"]) == 2


def test_cli_missing_db_exits_2(tmp_path):
    assert main([str(tmp_path / "absent.db")]) == 2


def test_observe_does_not_write_to_the_db(tmp_path):
    # A tamper-evidence inspector must be truly read-only: opening + reading must not alter a byte.
    import hashlib

    db = str(tmp_path / "state.db")
    _build_passing_flow(db).close()

    def digest():
        with open(db, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    before = digest()
    assert main([db, "f1"]) == 0
    assert digest() == before


def test_governance_with_level_key_renders_the_level(tmp_path):
    # RuleSetGovernance logs "level"; the handbrake gate logs "authority_level". Handle both.
    store = DurableEventStore(str(tmp_path / "state.db"))
    store.append(
        "f",
        "governance",
        ActorRef("Executor", "ref"),
        {"decision": "allow", "level": "L2", "action_class": "CLASS_OWN_WRITE"},
    )
    line = format_timeline(store.read("f"))
    assert "ALLOW L2 CLASS_OWN_WRITE" in line
    assert "LNone" not in line


def test_summarize_confirms_exactly_once_via_callback(tmp_path):
    store = _build_passing_flow(str(tmp_path / "state.db"))
    s = summarize(store.read("f1"), confirm_once=lambda key: True)
    assert s.effects[0].once_confirmed is True


def test_cli_non_sqlite_file_exits_2(tmp_path):
    bad = tmp_path / "notadb.txt"
    bad.write_text("not a database")
    assert main([str(bad), "f1"]) == 2


def test_cli_directory_path_exits_2(tmp_path):
    d = tmp_path / "adir"
    d.mkdir()
    assert main([str(d), "f1"]) == 2


def test_cli_prints_a_full_report_for_a_known_flow(tmp_path, capsys):
    db = str(tmp_path / "state.db")
    _build_passing_flow(db)
    rc = main([db, "f1"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "VERDICT: PASS" in out
    assert "https://github.com/x/y/pull/1" in out
    assert "re-derivations: 1" in out
