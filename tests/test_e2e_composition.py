"""End-to-end composition harness (sub-project A) — the assembled Cell demonstrates the
build-plan §7 definition of done over the reference roles, with RuleSetGovernance as the live
gate. See docs/superpowers/specs/2026-06-27-end-to-end-composition-design.md.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cell.cell import Cell
from cell.domain.objects import ActorRef, BudgetCap, CriterionScore, Output, Ticket, Verdict, WorkItem
from cell.planes.governance import RuleSetGovernance
from cell.planes.memory import CostDelta, InMemoryEventStore
from cell.effects.wrapper import GovernanceBlocked, InMemoryEffectsLedger
from cell.roles.reference import EXECUTOR, RefExecutor

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _ticket(tid: str = "t1") -> Ticket:
    return Ticket(id=tid, source="legacy", title="Add feature X",
                  body="Please add feature X", received_at=_T0)


def test_assemble_wires_the_live_governance_gate():
    cell = Cell.assemble()
    assert isinstance(cell.governance, RuleSetGovernance)
    assert cell.handbrake.governance is cell.governance
    assert cell.steward is not None
