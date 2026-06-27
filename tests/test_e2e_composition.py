"""End-to-end composition harness (sub-project A) — the assembled Cell demonstrates the
build-plan §7 definition of done over the reference roles, with RuleSetGovernance as the live
gate. See docs/superpowers/specs/2026-06-27-end-to-end-composition-design.md.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cell.cell import Cell
from cell.handbrake import Paused
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


class L1Orchestrator:
    """One L1 work item -> a static breakpoint precedes its action (the dramatic path)."""
    actor = ActorRef(role="Orchestrator", version="l1-orch")

    def decompose(self, goal):
        return [WorkItem(id=f"wi-{goal.id}", goal_id=goal.id, description="Comment on the issue",
                         assigned_to=EXECUTOR, action_class="CLASS_EXTERNAL_COMM",
                         authority_level="L1", acceptance_criteria=list(goal.acceptance_criteria))]


def test_routine_path_runs_autonomously_end_to_end():
    cell = Cell.assemble()  # reference roles -> an L2 work item -> no pause
    verdict = cell.submit(_ticket(), "f1")
    assert not isinstance(verdict, Paused)
    assert verdict.decision == "pass"
    # governance ran as the live gate and allowed it
    gate = [e for e in cell.governance_log("f1") if e.payload.get("stage") == "gate"]
    assert gate and gate[-1].payload["decision"] == "allow"
    # the run is fully traced
    assert {s.step for s in cell.trace("f1")} >= {"specify", "decompose", "execute", "verify"}


def test_dramatic_path_takeover_via_the_handbrake():
    cell = Cell.assemble(orchestrator=L1Orchestrator())
    paused = cell.submit(_ticket(), "f1")
    assert isinstance(paused, Paused)

    briefing = cell.inspect("f1")
    assert briefing.authority_level == "L1"
    assert "approve" in briefing.valid_moves and briefing.recent_decisions

    human = ActorRef(role="Executor", version="human:alice", mode="human")
    cell.inject("f1", {"type": "edited_output", "output_id": "corrected",
                       "artifact_ref": "branch://corrected"}, human)
    verdict = cell.resume("f1")
    assert verdict.decision == "pass"
    exec_event = next(e for e in cell.events("f1") if e.payload.get("stage") == "execute")
    assert exec_event.payload["artifact_ref"] == "branch://corrected"
    assert exec_event.actor == human


class L0Orchestrator:
    actor = ActorRef(role="Orchestrator", version="l0-orch")

    def decompose(self, goal):
        return [WorkItem(id=f"wi-{goal.id}", goal_id=goal.id, description="push to main",
                         assigned_to=EXECUTOR, action_class="CLASS_HIGH_BLAST",
                         authority_level="L0", acceptance_criteria=list(goal.acceptance_criteria))]


class ReturnVerifier:
    """Always returns 'return' -> induces a produce->revise loop (the runaway signal)."""
    actor = ActorRef(role="Verifier", version="ref-v0")

    def verify(self, output, goal):
        return Verdict(id=f"v-{output.id}", output_id=output.id, decision="return",
                       scores=[CriterionScore(criterion_id="c", result="unclear")],
                       reason="needs revision", verified_by=self.actor, verified_at=_T0)


def test_kill_and_resume_is_safe_across_a_fresh_controller():
    store, ledger = InMemoryEventStore(), InMemoryEffectsLedger()
    calls = {"n": 0}

    class CountingExecutor:
        actor = EXECUTOR

        def execute(self, item):
            calls["n"] += 1
            return RefExecutor().execute(item)

    Cell.assemble(orchestrator=L1Orchestrator(), executor=CountingExecutor(),
                  store=store, ledger=ledger).submit(_ticket(), "f1")  # pauses at L1

    # a fresh cell over the SAME durable plane resumes from the checkpoint
    fresh = Cell.assemble(orchestrator=L1Orchestrator(), executor=CountingExecutor(),
                          store=store, ledger=ledger)
    verdict = fresh.resume("f1")
    assert verdict.decision == "pass"
    assert calls["n"] == 1  # the external effect ran exactly once


def test_out_of_policy_action_is_blocked_and_traceable():
    calls = {"n": 0}

    class CountingExecutor:
        actor = EXECUTOR

        def execute(self, item):
            calls["n"] += 1
            return RefExecutor().execute(item)

    cell = Cell.assemble(orchestrator=L0Orchestrator(), executor=CountingExecutor())
    with pytest.raises(GovernanceBlocked):
        cell.submit(_ticket(), "f1")
    assert calls["n"] == 0
    block = [e for e in cell.governance_log("f1") if e.payload.get("decision") == "block"]
    assert block and "Art. 4" in block[-1].payload["reason"]  # traces to a clause


def test_steward_quarantines_an_induced_loop_before_the_cap():
    cell = Cell.assemble(verifier=ReturnVerifier(), max_revisions=5, loop_threshold=3,
                         cost_model=lambda stage: CostDelta(compute=100))
    verdict = cell.submit(_ticket(), "f1")  # runs to revision exhaustion
    assert verdict.decision == "return"
    budget = BudgetCap(compute=10_000, wall_clock_ms=15 * 60 * 1000)
    action = cell.assess("f1", budget)
    assert action.kind == "quarantine"
    assert action.rule == "R8"
    assert cell.cost("f1").compute < budget.compute  # quarantined before the cap


def test_demo_runs_without_error(capsys):
    from cell import demo
    demo.main()
    out = capsys.readouterr().out
    assert "Routine" in out and "blocked" in out.lower() and "quarantine" in out.lower()
