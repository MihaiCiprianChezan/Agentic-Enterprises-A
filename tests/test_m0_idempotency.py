"""M0 acceptance tests — the two seams.

These encode the M0 "definition of done" from One-Cell-Build-Plan.md §7 item 3 and
Build-Spec.md §7. The structural tests (event chain, tamper-evidence, key determinism)
pass now. The two exactly-once tests are `skip`-marked until effects.wrapper.perform()
is implemented (the M0 task, owned in the real repo via Claude Code): remove the skip
when you implement it and they become the real M0 acceptance gate.

Run:  pytest -q
"""

from __future__ import annotations

import pytest

from cell.domain.objects import ActorRef
from cell.effects.wrapper import (
    ActionDescriptor,
    InMemoryEffectsLedger,
    make_idempotency_key,
    perform,
)
from cell.planes.governance import PermissiveGovernance
from cell.planes.memory import InMemoryEventStore


# --- event store: append-only + tamper-evident chain (Build-Spec §2.1) -------

def test_event_chain_is_consistent():
    store = InMemoryEventStore()
    actor = ActorRef(role="Executor", version="v0")
    store.append("flow1", "action", actor, {"did": "a"})
    store.append("flow1", "action", actor, {"did": "b"})
    assert store.verify_chain("flow1") is True
    assert len(store.read("flow1")) == 2


def test_tampering_is_detectable():
    store = InMemoryEventStore()
    actor = ActorRef(role="Executor", version="v0")
    store.append("flow1", "action", actor, {"did": "a"})
    store.append("flow1", "action", actor, {"did": "b"})
    # Mutate a payload in place -> chain must no longer verify (Constitution Art. 10.3)
    store._events["flow1"][0].payload["did"] = "tampered"
    assert store.verify_chain("flow1") is False


def test_idempotency_key_is_deterministic():
    k1 = make_idempotency_key("flow1", "open_pr", {"branch": "x"})
    k2 = make_idempotency_key("flow1", "open_pr", {"branch": "x"})
    k3 = make_idempotency_key("flow1", "open_pr", {"branch": "y"})
    assert k1 == k2 and k1 != k3


# --- the idempotency wrapper: exactly-once across resume (Build-Spec §4) ------

@pytest.mark.skip(reason="M0: implement effects.wrapper.perform(), then remove this skip")
def test_completed_effect_is_not_refired():
    """The core M0 guarantee: a second perform() with the same key returns the prior
    result and does NOT execute again."""
    ledger = InMemoryEffectsLedger()
    gov = PermissiveGovernance()
    actor = ActorRef(role="Executor", version="v0")
    calls = {"n": 0}

    def execute(action):
        calls["n"] += 1
        return "pr-123"

    key = make_idempotency_key("flow1", "open_pr", {"branch": "x"})
    action = ActionDescriptor(
        id="a1", action_class="CLASS_VISIBLE_OUTPUT", effect_kind="compensable",
        idempotency_key=key, intent={"branch": "x"},
    )

    r1 = perform(action, actor, execute, ledger, gov)
    r2 = perform(action, actor, execute, ledger, gov)  # simulates a resume
    assert r1 == r2 == "pr-123"
    assert calls["n"] == 1  # executed exactly once


@pytest.mark.skip(reason="M0: implement effects.wrapper.perform(), then remove this skip")
def test_irreversible_effect_is_at_most_once():
    """For an irreversible effect, an in-flight record must NOT be re-executed on resume
    (at-most-once); the execute callable is never called a second time."""
    ledger = InMemoryEffectsLedger()
    gov = PermissiveGovernance()
    actor = ActorRef(role="Executor", version="v0")
    key = make_idempotency_key("flow1", "send_msg", {"to": "client"})
    ledger.put_in_flight(key)  # a prior attempt that crashed mid-effect

    calls = {"n": 0}

    def execute(action):
        calls["n"] += 1
        return "sent"

    action = ActionDescriptor(
        id="a2", action_class="CLASS_EXTERNAL_COMM", effect_kind="irreversible",
        idempotency_key=key, intent={"to": "client"},
    )

    with pytest.raises(Exception):
        perform(action, actor, execute, ledger, gov)
    assert calls["n"] == 0  # at-most-once: never re-executed
