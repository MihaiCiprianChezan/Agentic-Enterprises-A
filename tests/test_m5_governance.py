"""M5 — compile governance from the constitution (Build-Spec §5; One-Cell-Build-Plan §6).

The constitution's enforceable Articles compiled into rules evaluated per action, before
effect (Art. 5.3). Each rule names the clause it traces to (§5.4). Acceptance: an attempted
L0 action (e.g. push to a protected branch) is blocked and logged, and the block traces to a
constitution clause; a novel/unclassified action is forced to L0 with a classification
proposal (R3).
"""

from __future__ import annotations

import pytest

from cell.domain.objects import ActorRef
from cell.effects.wrapper import ActionDescriptor, GovernanceBlocked, InMemoryEffectsLedger, perform
from cell.planes.governance import (
    ACTION_CLASS_REGISTRY,
    RULE_CLAUSES,
    GovernanceDecision,
    RuleSetGovernance,
)
from cell.planes.memory import InMemoryEventStore

AGENT = ActorRef(role="Executor", version="ref-v0")
HUMAN = ActorRef(role="Executor", version="human:alice", mode="human")


def _action(action_class: str) -> ActionDescriptor:
    return ActionDescriptor(id="a1", action_class=action_class, effect_kind="compensable",
                            idempotency_key="k1", intent={})


# --- the acceptance: an L0 action is blocked and traces to a clause ----------

def test_l0_action_is_blocked_and_cites_a_clause():
    gov = RuleSetGovernance()
    decision = gov.decide(_action("CLASS_HIGH_BLAST"), AGENT)
    assert isinstance(decision, GovernanceDecision)
    assert decision.allowed is False
    assert decision.level == "L0"
    assert decision.rule == "R1"
    assert "Art. 4" in decision.clause
    assert "5.2" in decision.reason  # the static-breakpoint requirement


def test_novel_action_is_forced_to_l0_with_a_proposal():
    gov = RuleSetGovernance()
    decision = gov.decide(_action("CLASS_SOMETHING_NEW"), AGENT)
    assert decision.allowed is False
    assert decision.level == "L0"
    assert decision.rule == "R3"
    assert decision.novel is True


def test_safe_classes_are_allowed():
    gov = RuleSetGovernance()
    assert gov.decide(_action("CLASS_READ"), AGENT).allowed is True       # L3
    assert gov.decide(_action("CLASS_SANDBOX"), AGENT).allowed is True    # L3
    own = gov.decide(_action("CLASS_OWN_WRITE"), AGENT)                   # L2
    assert own.allowed is True and own.level == "L2"


# --- R11: a human in a Role cannot exceed its ceiling via the Handbrake -------

def test_human_cannot_take_an_l0_action():
    gov = RuleSetGovernance()
    decision = gov.decide(_action("CLASS_HIGH_BLAST"), HUMAN)
    assert decision.allowed is False
    assert decision.rule == "R11"
    assert "Art. 9" in decision.clause


# --- R6/R12: every decision is logged with its clause ------------------------

def test_block_is_logged_with_its_clause():
    gov = RuleSetGovernance()
    store = InMemoryEventStore()
    gov.evaluate_and_log(_action("CLASS_HIGH_BLAST"), AGENT, store, "f1")
    gov_events = [e for e in store.read("f1") if e.kind == "governance"]
    assert gov_events
    ev = gov_events[-1]
    assert ev.payload["decision"] == "block"
    assert ev.payload["clause"]  # non-empty citation
    assert ev.payload["rule"] == "R1"


def test_allow_is_logged_too():
    gov = RuleSetGovernance()
    store = InMemoryEventStore()
    gov.evaluate_and_log(_action("CLASS_READ"), AGENT, store, "f1")
    ev = [e for e in store.read("f1") if e.kind == "governance"][-1]
    assert ev.payload["decision"] == "allow"


# --- §5.4: the compiled set is traceable -------------------------------------

def test_every_rule_traces_to_a_clause():
    # The attestation property: no enforced rule without a clause it cites.
    assert set(RULE_CLAUSES) == {f"R{i}" for i in range(1, 13)}
    assert all(clause.startswith("Art.") for clause in RULE_CLAUSES.values())


# --- integration: the wrapper blocks an L0 effect before it fires ------------

def test_perform_blocks_an_l0_effect():
    gov = RuleSetGovernance()
    ledger = InMemoryEffectsLedger()
    calls = {"n": 0}

    def execute(a):
        calls["n"] += 1
        return "pushed"

    with pytest.raises(GovernanceBlocked):
        perform(_action("CLASS_HIGH_BLAST"), AGENT, execute, ledger, gov)
    assert calls["n"] == 0  # blocked before the effect fired
    assert ledger.get("k1") is None  # nothing recorded


def test_registry_is_unchanged_by_evaluation():
    # R2: a role cannot change the registry; evaluation is read-only over it.
    before = dict(ACTION_CLASS_REGISTRY)
    RuleSetGovernance().decide(_action("CLASS_SOMETHING_NEW"), AGENT)
    assert ACTION_CLASS_REGISTRY == before
