"""M6 — graduate autonomy (One-Cell-Build-Plan §6).

Autonomy levels start conservative (Art. 4) and are raised only on observed evidence, and
only by a Board-ratified amendment (Art. 4.1, 8.3; invariant #10). Performance earns a
*proposal*; the Board turns a proposal into a rule (Art. 8.4). Acceptance: a promotion exists
in the audit trail as a human-ratified amendment, never an automatic change.
"""

from __future__ import annotations

import pytest

from cell.autonomy import AmendmentRefused, AutonomyBoard, PromotionProposal
from cell.domain.objects import ActorRef
from cell.planes.governance import ACTION_CLASS_REGISTRY, RuleSetGovernance
from cell.planes.memory import InMemoryEventStore

BOARD = ActorRef(role="Board", version="human:mihai", mode="human")
OBSERVABILITY = ActorRef(role="Steward", version="obs-v0")  # surfaces evidence (Art. 8.4)
AGENT = ActorRef(role="Executor", version="ref-v0")

BOARD_TRAIL = "board"


def _board(store) -> AutonomyBoard:
    return AutonomyBoard(members={"human:mihai"}, store=store)


def _action(action_class: str):
    from cell.effects.wrapper import ActionDescriptor

    return ActionDescriptor(
        id="a1",
        action_class=action_class,
        effect_kind="compensable",
        idempotency_key="k1",
        intent={},
    )


# --- a proposal is only a proposal -------------------------------------------


def test_a_proposal_does_not_change_autonomy():
    store = InMemoryEventStore()
    board = _board(store)
    proposal = board.propose(
        "CLASS_OWN_WRITE",
        "L3",
        evidence="200 clean L2 writes, zero reverts",
        proposed_by=OBSERVABILITY,
    )
    assert isinstance(proposal, PromotionProposal)
    assert proposal.from_level == "L2" and proposal.to_level == "L3"
    # the registry / governance is unchanged — nothing is promoted yet
    assert ACTION_CLASS_REGISTRY["CLASS_OWN_WRITE"] == "L2"
    assert RuleSetGovernance().decide(_action("CLASS_OWN_WRITE"), AGENT).level == "L2"


def test_promotion_is_never_automatic():
    # There is no path from evidence to a level change without ratification: proposing many
    # times still does not promote.
    store = InMemoryEventStore()
    board = _board(store)
    for _ in range(5):
        board.propose("CLASS_OWN_WRITE", "L3", evidence="clean", proposed_by=OBSERVABILITY)
    assert ACTION_CLASS_REGISTRY["CLASS_OWN_WRITE"] == "L2"


# --- the Board ratifies -> the amendment applies and is logged ---------------


def test_board_ratifies_and_the_promotion_takes_effect():
    store = InMemoryEventStore()
    board = _board(store)
    proposal = board.propose(
        "CLASS_OWN_WRITE", "L3", evidence="clean run", proposed_by=OBSERVABILITY
    )
    amended = board.ratify(proposal, BOARD)

    # the re-compiled governance reflects the promotion (L2 act-and-report -> L3 auto)
    assert amended["CLASS_OWN_WRITE"] == "L3"
    assert RuleSetGovernance(amended).decide(_action("CLASS_OWN_WRITE"), AGENT).level == "L3"


def test_the_amendment_is_on_the_board_audit_trail():
    store = InMemoryEventStore()
    board = _board(store)
    proposal = board.propose("CLASS_OWN_WRITE", "L3", evidence="clean", proposed_by=OBSERVABILITY)
    board.ratify(proposal, BOARD)

    amendments = [e for e in store.read(BOARD_TRAIL) if e.payload.get("stage") == "amendment"]
    assert amendments
    ev = amendments[-1]
    assert ev.payload["decision"] == "ratified"
    assert ev.actor == BOARD
    assert ev.payload["from"] == "L2" and ev.payload["to"] == "L3"
    assert "Art. 8" in ev.payload["clause"]
    assert store.verify_chain(BOARD_TRAIL) is True  # tamper-evident (R12)


def test_board_acts_are_separate_from_role_acts():
    # Art. 10.2: Board-acts and Role-acts go to separate trails.
    store = InMemoryEventStore()
    board = _board(store)
    proposal = board.propose("CLASS_OWN_WRITE", "L3", evidence="clean", proposed_by=OBSERVABILITY)
    board.ratify(proposal, BOARD)
    assert store.read(BOARD_TRAIL)  # the board trail has the proposal + amendment
    assert store.read("some-flow") == []  # role flows are untouched


# --- only the Board, only on evidence ----------------------------------------


def test_a_non_board_actor_cannot_ratify():
    store = InMemoryEventStore()
    board = _board(store)
    proposal = board.propose("CLASS_OWN_WRITE", "L3", evidence="clean", proposed_by=OBSERVABILITY)
    with pytest.raises(AmendmentRefused):
        board.ratify(proposal, AGENT)  # an agent cannot author its own rule (invariant #10)
    blocks = [e for e in store.read(BOARD_TRAIL) if e.payload.get("decision") == "block"]
    assert blocks


def test_ratification_requires_evidence():
    store = InMemoryEventStore()
    board = _board(store)
    proposal = PromotionProposal(
        "CLASS_OWN_WRITE", "L2", "L3", evidence="", proposed_by=OBSERVABILITY
    )
    with pytest.raises(AmendmentRefused):
        board.ratify(proposal, BOARD)  # promotion must be earned on observed evidence


# --- review fixes: real raises, current-registry consistency, richer blocks --


def test_proposal_uses_the_boards_current_registry():
    # If the cell already runs an amended registry, the proposal's from_level reflects it.
    store = InMemoryEventStore()
    amended = dict(ACTION_CLASS_REGISTRY)
    amended["CLASS_OWN_WRITE"] = "L3"
    board = AutonomyBoard(members={"human:mihai"}, store=store, registry=amended)
    proposal = board.propose("CLASS_OWN_WRITE", "L3", evidence="x", proposed_by=OBSERVABILITY)
    assert proposal.from_level == "L3"


def test_ratify_refuses_a_non_raise():
    store = InMemoryEventStore()
    board = _board(store)
    proposal = board.propose("CLASS_OWN_WRITE", "L2", evidence="clean", proposed_by=OBSERVABILITY)
    with pytest.raises(AmendmentRefused):
        board.ratify(proposal, BOARD)  # L2 -> L2 is not a graduation


def test_ratify_refuses_a_stale_proposal():
    store = InMemoryEventStore()
    board = _board(store)
    # from_level claims L1 but the current ceiling is L2 -> stale/inconsistent
    stale = PromotionProposal(
        "CLASS_OWN_WRITE", "L1", "L3", evidence="clean", proposed_by=OBSERVABILITY
    )
    with pytest.raises(AmendmentRefused):
        board.ratify(stale, BOARD)


def test_block_event_includes_context():
    store = InMemoryEventStore()
    board = _board(store)
    proposal = board.propose(
        "CLASS_OWN_WRITE", "L3", evidence="clean run", proposed_by=OBSERVABILITY
    )
    with pytest.raises(AmendmentRefused):
        board.ratify(proposal, AGENT)
    block = [e for e in store.read(BOARD_TRAIL) if e.payload.get("decision") == "block"][-1]
    assert block.payload["to"] == "L3"
    assert block.payload["from"] == "L2"
    assert block.payload["evidence"] == "clean run"
