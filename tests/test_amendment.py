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


def test_a_non_board_actor_cannot_ratify_an_amendment():
    store = InMemoryEventStore()
    with pytest.raises(AmendmentRefused):
        _board(store).ratify_amendment("Article 11", {"x": 1}, NOT_BOARD)


def test_suspension_policy_declares_the_governed_values():
    assert SUSPENSION_POLICY["response_sla_hours"] == 24
    assert SUSPENSION_POLICY["max_suspensions_per_window"] == 1
    assert SUSPENSION_POLICY["collapse_alert_pass_rate"] == 0.5
