"""M9a — the constitutional amendment for version suspension. The Board ratifies governed content
(the suspension policy) onto the Board-acts trail; nothing reads it yet (the Auditor is 9b/9c).
"""
from __future__ import annotations

import pytest

from cell.autonomy import AmendmentRefused, AutonomyBoard
from cell.domain.objects import ActorRef
from cell.planes.governance import SUSPENSION_POLICY
from cell.planes.memory import InMemoryEventStore

BOARD = ActorRef(role="Board", version="human:mihai", mode="human")
NOT_BOARD = ActorRef(role="Executor", version="ref-v0")
BOARD_TRAIL = "board"


def _board(store) -> AutonomyBoard:
    return AutonomyBoard(members={"human:mihai"}, store=store)


def test_board_ratifies_a_constitutional_amendment_onto_the_board_trail():
    store = InMemoryEventStore()
    content = {"response_sla_hours": 24, "danger": "safety-breach-only"}
    returned = _board(store).ratify_amendment("Article 11 — Version audit & suspension", content, BOARD)
    assert returned == content
    acts = [e for e in store.read(BOARD_TRAIL) if e.payload.get("stage") == "amendment"]
    assert acts and acts[0].payload["content"] == content
    assert acts[0].payload["article"].startswith("Article 11")
    assert store.verify_chain(BOARD_TRAIL) is True   # on the tamper-evident Board trail (Art 10.2/R12)


def test_a_ratified_amendment_is_immutable_against_later_mutation():
    # The audit record must not change if the caller mutates the dict it passed (the payload is
    # re-hashed by verify_chain — a shared reference would break tamper-evidence).
    store = InMemoryEventStore()
    content = {"response_sla_hours": 24}
    _board(store).ratify_amendment("Article 11", content, BOARD)
    content["response_sla_hours"] = 999                  # mutate the caller's dict after ratifying
    assert store.verify_chain(BOARD_TRAIL) is True
    act = [e for e in store.read(BOARD_TRAIL) if e.payload.get("stage") == "amendment"][0]
    assert act.payload["content"]["response_sla_hours"] == 24   # the recorded act is frozen


def test_a_non_board_actor_cannot_ratify_and_the_refusal_is_logged():
    store = InMemoryEventStore()
    with pytest.raises(AmendmentRefused):
        _board(store).ratify_amendment("Article 11", {"x": 1}, NOT_BOARD)
    blocks = [e for e in store.read(BOARD_TRAIL)
              if e.payload.get("stage") == "amendment" and e.payload.get("decision") == "block"]
    assert blocks   # the refusal is on the audit trail (invariant #10)


def test_suspension_policy_declares_the_full_governed_shape():
    assert SUSPENSION_POLICY == {
        "response_sla_hours": 24,
        "max_suspensions_per_window": 1,
        "rate_limit_window_hours": 24,
        "collapse_alert_pass_rate": 0.5,
        "collapse_alert_min_runs": 5,
    }
