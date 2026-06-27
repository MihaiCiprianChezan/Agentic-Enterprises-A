"""M0 hardening — action-Event wiring, edge-case branches, and the atomicity guard.

These extend the M0 gate: the wrapper must record an `action` Event on completion
(Build-Spec §4.2 step 4 / §6), must respect the governance pre-check and failure
semantics (§4.2 steps 1 & 3), and the durable store's seq guard must actually reject
a forked append (§2.1; M0-Implementation-Notes Step 1).
"""

from __future__ import annotations

import sqlite3

import pytest

from cell.domain.objects import ActorRef
from cell.effects.wrapper import (
    ActionDescriptor,
    GovernanceBlocked,
    InMemoryEffectsLedger,
    IrreversibleInFlight,
    make_idempotency_key,
    perform,
)
from cell.planes.governance import PermissiveGovernance
from cell.planes.memory import DurableEventStore, InMemoryEventStore

ACTOR = ActorRef(role="Executor", version="v0")
GOV = PermissiveGovernance()


def _action(kind: str, *, step: str = "open_pr", action_class: str = "CLASS_VISIBLE_OUTPUT"):
    key = make_idempotency_key("flow1", step, {"branch": "x"})
    return key, ActionDescriptor(
        id="a1", action_class=action_class, effect_kind=kind,
        idempotency_key=key, intent={"branch": "x"},
    )


class _Deny:
    def evaluate(self, action, actor):
        return False, "blocked-for-test"


# --- action-Event wiring (the new behavior) ----------------------------------

def test_perform_appends_one_action_event_on_completion():
    store = InMemoryEventStore()
    ledger = InMemoryEffectsLedger()
    key, action = _action("compensable")

    perform(action, ACTOR, lambda a: "pr-1", ledger, GOV, store=store, flow_id="flow1")

    events = store.read("flow1")
    assert len(events) == 1
    ev = events[0]
    assert ev.kind == "action"
    assert ev.actor == ACTOR
    assert ev.payload["action_id"] == "a1"
    assert ev.payload["idempotency_key"] == key
    assert ev.payload["result_digest"] == "pr-1"


def test_resume_does_not_append_a_second_action_event():
    store = InMemoryEventStore()
    ledger = InMemoryEffectsLedger()
    _key, action = _action("compensable")

    perform(action, ACTOR, lambda a: "pr-1", ledger, GOV, store=store, flow_id="flow1")
    perform(action, ACTOR, lambda a: "pr-1", ledger, GOV, store=store, flow_id="flow1")  # resume

    assert len(store.read("flow1")) == 1  # exactly-once extends to the event log


def test_action_event_keeps_the_chain_verifiable():
    store = InMemoryEventStore()
    ledger = InMemoryEffectsLedger()
    _key, action = _action("compensable")
    perform(action, ACTOR, lambda a: "pr-1", ledger, GOV, store=store, flow_id="flow1")
    assert store.verify_chain("flow1") is True


def test_event_wiring_is_optional():
    # Backward-compatible: the 5-arg call still works and records no event.
    ledger = InMemoryEffectsLedger()
    _key, action = _action("compensable")
    assert perform(action, ACTOR, lambda a: "pr-1", ledger, GOV) == "pr-1"


# --- governance pre-check (R6) -----------------------------------------------

def test_blocked_action_does_not_execute_or_record():
    store = InMemoryEventStore()
    ledger = InMemoryEffectsLedger()
    key, action = _action("compensable")
    calls = {"n": 0}

    def execute(a):
        calls["n"] += 1
        return "x"

    with pytest.raises(GovernanceBlocked):
        perform(action, ACTOR, execute, ledger, _Deny(), store=store, flow_id="flow1")

    assert calls["n"] == 0
    assert ledger.get(key) is None
    assert store.read("flow1") == []


# --- failure semantics (§4.2 step 3) -----------------------------------------

def test_failed_idempotent_retries_on_resume():
    ledger = InMemoryEffectsLedger()
    key, action = _action("idempotent")
    state = {"boom": True, "calls": 0}

    def execute(a):
        state["calls"] += 1
        if state["boom"]:
            state["boom"] = False
            raise RuntimeError("transient")
        return "ok"

    with pytest.raises(RuntimeError):
        perform(action, ACTOR, execute, ledger, GOV)
    assert ledger.get(key).status == "failed"

    result = perform(action, ACTOR, execute, ledger, GOV)  # resume retries
    assert result == "ok"
    assert ledger.get(key).status == "completed"
    assert state["calls"] == 2


def test_failed_irreversible_escalates_on_resume():
    ledger = InMemoryEffectsLedger()
    key, action = _action("irreversible", action_class="CLASS_EXTERNAL_COMM")

    def boom(a):
        raise RuntimeError("send failed")

    with pytest.raises(RuntimeError):
        perform(action, ACTOR, boom, ledger, GOV)
    assert ledger.get(key).status == "failed"

    calls = {"n": 0}

    def execute(a):
        calls["n"] += 1
        return "sent"

    with pytest.raises(IrreversibleInFlight):
        perform(action, ACTOR, execute, ledger, GOV)  # resume must NOT retry
    assert calls["n"] == 0


# --- idempotency-key determinism (the pitfall the notes call out) ------------

def test_idempotency_key_ignores_intent_insertion_order():
    k1 = make_idempotency_key("flow1", "s", {"a": 1, "b": 2})
    k2 = make_idempotency_key("flow1", "s", {"b": 2, "a": 1})
    assert k1 == k2


# --- durable store atomicity guard -------------------------------------------

def test_durable_append_rejects_duplicate_seq(tmp_path):
    store = DurableEventStore(tmp_path / "cell.db")
    store.append("flow1", "action", ACTOR, {"n": 0})
    # Forcing a second row at the same (flow_id, seq) must fail — this is what stops
    # two processes from forking the chain.
    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute(
            "INSERT INTO events (flow_id, seq, prev_hash, hash, kind, actor, payload, cost, at) "
            "VALUES ('flow1', 0, 'p', 'h', 'action', '{}', '{}', NULL, '2026-01-01T00:00:00')"
        )
        store._conn.commit()
