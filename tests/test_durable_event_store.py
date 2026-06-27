"""M0 Step 1 — the durable EventStore (Build-Spec §2; M0-Implementation-Notes Step 1).

A persistent sibling of InMemoryEventStore that satisfies the SAME EventStore Protocol.
These mirror the in-memory structural guarantees, plus the one property the in-memory
store cannot have: history survives process death (a fresh store on the same DB re-reads
the full chain). SQLite is enough for one cell (Component-Selection.md).
"""

from __future__ import annotations

import sqlite3

from cell.domain.objects import ActorRef
from cell.planes.memory import (
    Checkpoint,
    DurableEventStore,
    EventStore,
    compute_hash,
)


def _store(tmp_path) -> DurableEventStore:
    return DurableEventStore(tmp_path / "cell.db")


def test_durable_store_satisfies_the_protocol(tmp_path):
    # invariant #1: bind to the contract, not the implementation.
    assert isinstance(_store(tmp_path), EventStore)


def test_durable_event_chain_is_consistent(tmp_path):
    store = _store(tmp_path)
    actor = ActorRef(role="Executor", version="v0")
    store.append("flow1", "action", actor, {"did": "a"})
    store.append("flow1", "action", actor, {"did": "b"})
    assert store.verify_chain("flow1") is True
    assert len(store.read("flow1")) == 2


def test_durable_seq_is_gap_free_and_monotonic(tmp_path):
    store = _store(tmp_path)
    actor = ActorRef(role="Executor", version="v0")
    for i in range(5):
        store.append("flow1", "action", actor, {"n": i})
    seqs = [ev.seq for ev in store.read("flow1")]
    assert seqs == [0, 1, 2, 3, 4]


def test_durable_read_preserves_event_fields(tmp_path):
    store = _store(tmp_path)
    actor = ActorRef(role="Executor", version="v0", mode="agent")
    store.append("flow1", "decision", actor, {"k": "v", "n": 1})
    ev = store.read("flow1")[0]
    assert ev.flow_id == "flow1"
    assert ev.kind == "decision"
    assert ev.actor == actor
    assert ev.payload == {"k": "v", "n": 1}
    assert ev.prev_hash == "GENESIS"
    assert ev.hash == compute_hash("GENESIS", {"k": "v", "n": 1})


def test_durable_history_survives_restart(tmp_path):
    # The property the in-memory store cannot have.
    db = tmp_path / "cell.db"
    actor = ActorRef(role="Executor", version="v0")
    s1 = DurableEventStore(db)
    s1.append("flow1", "action", actor, {"did": "a"})
    s1.append("flow1", "action", actor, {"did": "b"})
    s1.close()

    s2 = DurableEventStore(db)  # simulates a process restart
    assert len(s2.read("flow1")) == 2
    assert s2.verify_chain("flow1") is True


def test_durable_tampering_is_detectable(tmp_path):
    db = tmp_path / "cell.db"
    store = DurableEventStore(db)
    actor = ActorRef(role="Executor", version="v0")
    store.append("flow1", "action", actor, {"did": "a"})
    store.append("flow1", "action", actor, {"did": "b"})
    store.close()

    # Rewrite a payload directly in the DB -> the chain must no longer verify (Art. 10.3).
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE events SET payload = ? WHERE flow_id = ? AND seq = 0",
        ('{"did": "tampered"}', "flow1"),
    )
    conn.commit()
    conn.close()

    assert DurableEventStore(db).verify_chain("flow1") is False


def test_durable_checkpoint_roundtrips_across_restart(tmp_path):
    db = tmp_path / "cell.db"
    s1 = DurableEventStore(db)
    cp = Checkpoint(
        flow_id="flow1",
        at_seq=3,
        step="open_pr",
        state_snapshot={"branch": "x"},
        created_at=None,  # store stamps it; see below
        pending_action={"id": "a1"},
    )
    s1.checkpoint(cp)
    s1.close()

    got = DurableEventStore(db).latest_checkpoint("flow1")
    assert got is not None
    assert got.flow_id == "flow1"
    assert got.at_seq == 3
    assert got.step == "open_pr"
    assert got.state_snapshot == {"branch": "x"}
    assert got.pending_action == {"id": "a1"}


def test_latest_checkpoint_returns_the_newest(tmp_path):
    store = _store(tmp_path)
    store.checkpoint(Checkpoint("flow1", 1, "step_a", {"v": 1}, None))
    store.checkpoint(Checkpoint("flow1", 5, "step_b", {"v": 2}, None))
    got = store.latest_checkpoint("flow1")
    assert got.at_seq == 5
    assert got.step == "step_b"


def test_flows_are_isolated(tmp_path):
    store = _store(tmp_path)
    actor = ActorRef(role="Executor", version="v0")
    store.append("flowA", "action", actor, {"x": 1})
    store.append("flowB", "action", actor, {"y": 2})
    assert len(store.read("flowA")) == 1
    assert len(store.read("flowB")) == 1
    assert store.latest_checkpoint("unknown") is None
