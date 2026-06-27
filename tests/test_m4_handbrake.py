"""M4 — the Handbrake (Handbrake-Interface.md; One-Cell-Build-Plan §6).

The five primitives on the one flow: breakpoint → inspect → inject → resume → replay.
Acceptance (§5):
  * inspect at the L1 breakpoint returns a legible briefing (recent decisions, pending
    action, cost, valid moves);
  * inject a corrected output + resume → the resumed run USES the injection, not a
    re-decision;
  * resume is exactly-once w.r.t. the external side effect (leans on M0's wrapper);
  * an injection the assumed Role is not authorized to make is refused and logged (R11/Art.9);
  * replay reconstructs a completed run without re-performing side effects.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cell.domain.objects import ActorRef, Ticket, WorkItem
from cell.effects.wrapper import InMemoryEffectsLedger, make_idempotency_key
from cell.handbrake import Briefing, CellHandbrake, InjectionRefused, Paused
from cell.planes.memory import InMemoryEventStore
from cell.planes.observability import InMemoryTraceStore, total_cost
from cell.roles.reference import EXECUTOR, RefDirector, RefExecutor, RefVerifier

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _ticket(tid: str = "t1") -> Ticket:
    return Ticket(id=tid, source="legacy", title="Add feature X",
                  body="Please add feature X", received_at=_T0)


class L1Orchestrator:
    """Yields one L1 work item, so a static breakpoint precedes its action (Art. 5.2)."""

    actor = ActorRef(role="Orchestrator", version="l1-orch")

    def decompose(self, goal):
        return [WorkItem(
            id=f"wi-{goal.id}", goal_id=goal.id, description="Comment on the issue",
            assigned_to=EXECUTOR, action_class="CLASS_EXTERNAL_COMM", authority_level="L1",
            acceptance_criteria=list(goal.acceptance_criteria),
        )]


def _handbrake(**kw):
    return CellHandbrake(
        director=RefDirector(), orchestrator=L1Orchestrator(),
        executor=kw.pop("executor", RefExecutor()), verifier=RefVerifier(),
        store=kw.pop("store", InMemoryEventStore()), **kw,
    )


# --- breakpoint: an L1 action pauses the flow --------------------------------

def test_flow_pauses_at_the_l1_breakpoint():
    hb = _handbrake()
    result = hb.start(_ticket(), "f1")
    assert isinstance(result, Paused)
    assert result.flow_id == "f1"


def test_an_l2_flow_does_not_pause():
    # The reference orchestrator yields an L2 item -> no static breakpoint -> runs through.
    from cell.roles.reference import RefOrchestrator
    hb = CellHandbrake(director=RefDirector(), orchestrator=RefOrchestrator(),
                       executor=RefExecutor(), verifier=RefVerifier(), store=InMemoryEventStore())
    result = hb.start(_ticket(), "f1")
    assert not isinstance(result, Paused)
    assert result.decision == "pass"


# --- inspect: a legible briefing ---------------------------------------------

def test_inspect_returns_a_legible_briefing():
    store = InMemoryEventStore()
    hb = _handbrake(store=store, recorder=InMemoryTraceStore())
    hb.start(_ticket(), "f1")
    briefing = hb.inspect("f1")
    assert isinstance(briefing, Briefing)
    assert briefing.flow_id == "f1"
    assert briefing.step  # where
    assert briefing.why  # why it paused
    assert briefing.pending_action  # what it is about to do
    assert briefing.authority_level == "L1"
    assert briefing.recent_decisions  # the decision trail, with reasons
    assert "approve" in briefing.valid_moves
    assert "edit_output" in briefing.valid_moves


# --- inject + resume: the resumed run uses the injection ----------------------

def test_inject_corrected_output_then_resume_uses_it():
    store = InMemoryEventStore()
    hb = _handbrake(store=store)
    hb.start(_ticket(), "f1")

    human = ActorRef(role="Executor", version="human:alice", mode="human")
    hb.inject("f1", {"type": "edited_output", "output_id": "corrected",
                     "artifact_ref": "branch://corrected"}, human)
    verdict = hb.resume("f1")

    assert not isinstance(verdict, Paused)
    assert verdict.decision == "pass"
    # the verified output is the injected one, produced by the human in the seat
    exec_event = next(e for e in store.read("f1") if e.payload.get("stage") == "execute")
    assert exec_event.payload["artifact_ref"] == "branch://corrected"
    assert exec_event.actor == human


def test_plain_approve_resume_runs_the_agent():
    # resume with no injection proceeds as the agent would (a plain L1 approval).
    store = InMemoryEventStore()
    hb = _handbrake(store=store)
    hb.start(_ticket(), "f1")
    verdict = hb.resume("f1")
    assert verdict.decision == "pass"
    exec_event = next(e for e in store.read("f1") if e.payload.get("stage") == "execute")
    assert exec_event.actor == EXECUTOR  # the agent executor produced it


# --- R11: an out-of-authority injection is refused and logged ----------------

def test_injection_above_the_seat_authority_is_refused_and_logged():
    store = InMemoryEventStore()
    hb = _handbrake(store=store)
    hb.start(_ticket(), "f1")

    human = ActorRef(role="Executor", version="human:alice", mode="human")
    # Seat is L1; trying to inject an L0 (high-blast) action exceeds it (Art. 9 / R11).
    with pytest.raises(InjectionRefused):
        hb.inject("f1", {"type": "override", "action_class": "CLASS_HIGH_BLAST"}, human)

    blocks = [e for e in store.read("f1") if e.kind == "governance"]
    assert blocks and blocks[-1].payload.get("decision") == "block"


# --- resume is exactly-once on the external effect ---------------------------

def test_resume_does_not_refire_a_completed_effect():
    store = InMemoryEventStore()
    ledger = InMemoryEffectsLedger()
    calls = {"effect": 0}

    class CountingExecutor:
        actor = EXECUTOR

        def execute(self, item):
            calls["effect"] += 1
            return RefExecutor().execute(item)

    hb = _handbrake(store=store, ledger=ledger, executor=CountingExecutor())
    hb.start(_ticket(), "f1")
    hb.resume("f1")
    assert calls["effect"] == 1

    # The effect's ledger row is completed; a re-resume must not re-execute it.
    key = make_idempotency_key("f1", "execute:wi-goal-t1", {"output_id": "out-wi-goal-t1"})
    assert ledger.get(key).status == "completed"
    hb.resume("f1")  # idempotent: already done
    assert calls["effect"] == 1


# --- replay: read-only reconstruction ----------------------------------------

def test_replay_reconstructs_without_refiring():
    store = InMemoryEventStore()
    calls = {"effect": 0}

    class CountingExecutor:
        actor = EXECUTOR

        def execute(self, item):
            calls["effect"] += 1
            return RefExecutor().execute(item)

    hb = _handbrake(store=store, executor=CountingExecutor())
    hb.start(_ticket(), "f1")
    hb.resume("f1")
    assert calls["effect"] == 1

    steps = hb.replay("f1")
    assert [s["stage"] for s in steps][:2] == ["specify", "decompose"]
    assert calls["effect"] == 1  # replay never re-performs the effect


# --- durable resume across a fresh controller (simulated restart) ------------

# --- review fixes -----------------------------------------------------------

def test_ad_hoc_breakpoint_pauses_an_otherwise_l2_flow():
    from cell.roles.reference import RefOrchestrator
    store = InMemoryEventStore()
    hb = CellHandbrake(director=RefDirector(), orchestrator=RefOrchestrator(),
                       executor=RefExecutor(), verifier=RefVerifier(), store=store)
    bp_id = hb.set_breakpoint("f1", "pre-execute", "static")
    assert [b["id"] for b in hb.list_breakpoints("f1")] == [bp_id]

    result = hb.start(_ticket(), "f1")
    assert isinstance(result, Paused)  # the ad-hoc breakpoint paused an L2 flow

    hb.clear_breakpoint("f1", bp_id)
    assert hb.list_breakpoints("f1") == []


def test_injection_payload_cannot_override_event_stage():
    store = InMemoryEventStore()
    hb = _handbrake(store=store)
    hb.start(_ticket(), "f1")
    human = ActorRef(role="Executor", version="human:alice", mode="human")
    hb.inject("f1", {"type": "add_context", "stage": "EVIL"}, human)
    inj = next(e for e in store.read("f1") if e.kind == "injection")
    assert inj.payload["stage"] == "inject"


def test_injection_is_tagged_with_its_work_item():
    store = InMemoryEventStore()
    hb = _handbrake(store=store)
    paused = hb.start(_ticket(), "f1")
    human = ActorRef(role="Executor", version="human:alice", mode="human")
    hb.inject("f1", {"type": "add_context"}, human)
    inj = next(e for e in store.read("f1") if e.kind == "injection")
    assert inj.payload["work_item_id"] == paused.pending_action["work_item_id"]


def test_checkpoint_at_seq_points_at_the_breakpoint_event():
    store = InMemoryEventStore()
    hb = _handbrake(store=store)
    hb.start(_ticket(), "f1")
    cp = store.latest_checkpoint("f1")
    bp_event = next(e for e in store.read("f1") if e.kind == "breakpoint")
    assert cp.at_seq == bp_event.seq


def test_resume_records_the_effect_audit_event_before_completion():
    store = InMemoryEventStore()
    ledger = InMemoryEffectsLedger()
    hb = _handbrake(store=store, ledger=ledger)
    hb.start(_ticket(), "f1")
    hb.resume("f1")
    # perform() was given the store, so the effect's action Event is on the durable plane
    # (written before the ledger is marked completed — the R12 ordering).
    assert any("idempotency_key" in e.payload for e in store.read("f1"))


def test_a_fresh_controller_resumes_from_the_durable_plane():
    store = InMemoryEventStore()
    ledger = InMemoryEffectsLedger()
    CellHandbrake(director=RefDirector(), orchestrator=L1Orchestrator(),
                  executor=RefExecutor(), verifier=RefVerifier(),
                  store=store, ledger=ledger).start(_ticket(), "f1")

    # A new controller sharing the same durable plane resumes from the checkpoint.
    fresh = CellHandbrake(director=RefDirector(), orchestrator=L1Orchestrator(),
                          executor=RefExecutor(), verifier=RefVerifier(),
                          store=store, ledger=ledger)
    verdict = fresh.resume("f1")
    assert verdict.decision == "pass"


def test_governance_gate_blocks_an_l0_work_item_up_front():
    from cell.planes.governance import RuleSetGovernance
    from cell.effects.wrapper import GovernanceBlocked

    class L0Orchestrator:
        actor = ActorRef(role="Orchestrator", version="l0")

        def decompose(self, goal):
            return [WorkItem(id=f"wi-{goal.id}", goal_id=goal.id, description="push",
                             assigned_to=EXECUTOR, action_class="CLASS_HIGH_BLAST",
                             authority_level="L0", acceptance_criteria=list(goal.acceptance_criteria))]

    calls = {"n": 0}

    class CountingExecutor:
        actor = EXECUTOR

        def execute(self, item):
            calls["n"] += 1
            return RefExecutor().execute(item)

    store = InMemoryEventStore()
    hb = CellHandbrake(director=RefDirector(), orchestrator=L0Orchestrator(),
                       executor=CountingExecutor(), verifier=RefVerifier(), store=store,
                       governance=RuleSetGovernance())
    with pytest.raises(GovernanceBlocked):
        hb.start(_ticket(), "f1")
    assert calls["n"] == 0  # never executed
    gate = [e for e in store.read("f1") if e.payload.get("stage") == "gate"]
    assert gate and gate[-1].payload["decision"] == "block"
    assert "Art. 4" in gate[-1].payload["reason"]  # the clause travels in the reason


def test_governance_gate_allows_and_logs_an_l2_work_item():
    from cell.planes.governance import RuleSetGovernance
    from cell.roles.reference import RefOrchestrator
    store = InMemoryEventStore()
    hb = CellHandbrake(director=RefDirector(), orchestrator=RefOrchestrator(),
                       executor=RefExecutor(), verifier=RefVerifier(), store=store,
                       governance=RuleSetGovernance())
    verdict = hb.start(_ticket(), "f1")
    assert verdict.decision == "pass"
    gate = [e for e in store.read("f1") if e.payload.get("stage") == "gate"]
    assert gate and gate[-1].payload["decision"] == "allow"


def test_do_item_revises_up_to_max_revisions_on_return():
    # The handbrake's _do_item runs the produce -> score -> revise loop directly: an
    # always-'return' verifier re-executes up to max_revisions, then returns the final
    # 'return' verdict (revisions exhausted). Covers the loop in isolation, not via the Steward.
    from cell.domain.objects import CriterionScore, Verdict
    from cell.roles.reference import RefOrchestrator

    store = InMemoryEventStore()
    calls = {"n": 0}

    class CountingExecutor:
        actor = EXECUTOR

        def execute(self, item):
            calls["n"] += 1
            return RefExecutor().execute(item)

    class ReturnVerifier:
        actor = ActorRef(role="Verifier", version="ref-v0")

        def verify(self, output, goal):
            return Verdict(id=f"v-{output.id}", output_id=output.id, decision="return",
                           scores=[CriterionScore(criterion_id="c", result="unclear")],
                           reason="revise", verified_by=self.actor, verified_at=_T0)

    hb = CellHandbrake(director=RefDirector(), orchestrator=RefOrchestrator(),
                       executor=CountingExecutor(), verifier=ReturnVerifier(),
                       store=store, max_revisions=3)
    verdict = hb.start(_ticket(), "f1")
    assert verdict.decision == "return"
    assert calls["n"] == 4  # initial attempt + 3 revisions


# --- pr8 augment fixes -------------------------------------------------------

def test_breakpoint_uses_the_registry_level_not_the_declared_one():
    # A divergent orchestrator: an L1 action_class but a declared L3 authority_level must
    # still pause -- the compiled registry, not the orchestrator's claim, decides (R2 / Art. 5.2).
    from cell.planes.governance import RuleSetGovernance

    class DivergentOrchestrator:
        actor = ActorRef(role="Orchestrator", version="divergent")

        def decompose(self, goal):
            return [WorkItem(id=f"wi-{goal.id}", goal_id=goal.id, description="comment",
                             assigned_to=EXECUTOR, action_class="CLASS_EXTERNAL_COMM",  # L1 in registry
                             authority_level="L3",  # falsely claims fully-autonomous
                             acceptance_criteria=list(goal.acceptance_criteria))]

    store = InMemoryEventStore()
    hb = CellHandbrake(director=RefDirector(), orchestrator=DivergentOrchestrator(),
                       executor=RefExecutor(), verifier=RefVerifier(), store=store,
                       governance=RuleSetGovernance())
    result = hb.start(_ticket(), "f1")
    assert isinstance(result, Paused)  # registry says L1 -> static breakpoint, not bypassed


def test_resume_returns_the_latest_verdict_not_a_stale_one():
    # With the revise loop an item can have multiple verify events; the resume idempotent
    # guard must return the LATEST verdict, not the first (stale) one.
    from cell.domain.objects import CriterionScore, Verdict

    class FlakyVerifier:
        actor = ActorRef(role="Verifier", version="ref-v0")

        def __init__(self):
            self.n = 0

        def verify(self, output, goal):
            self.n += 1
            decision = "return" if self.n == 1 else "pass"
            return Verdict(id=f"v{self.n}-{output.id}", output_id=output.id, decision=decision,
                           scores=[CriterionScore(criterion_id="c", result="met")],
                           reason="x", verified_by=self.actor, verified_at=_T0)

    store = InMemoryEventStore()
    hb = CellHandbrake(director=RefDirector(), orchestrator=L1Orchestrator(),
                       executor=RefExecutor(), verifier=FlakyVerifier(),
                       store=store)  # L1Orchestrator -> pauses
    hb.start(_ticket(), "f1")
    v1 = hb.resume("f1")  # loop: return then pass -> final pass (two verify events)
    assert v1.decision == "pass"
    v2 = hb.resume("f1")  # re-resume: guard must return the LATEST verdict (pass), not the first (return)
    assert v2.decision == "pass"


def test_resume_after_a_crash_between_execute_and_verify_does_not_rerun_the_executor():
    # Durability gap: the executor produced (and, for a real executor, committed) its Output and
    # the durable "executed" marker was recorded, but the process died before the verdict. A
    # resume must reconstruct the Output from the marker — NOT re-run the executor (which, for a
    # real agent, would re-run it and hit an empty diff).
    store = InMemoryEventStore()
    calls = {"n": 0}

    class CountingExecutor:
        actor = EXECUTOR

        def execute(self, item):
            calls["n"] += 1
            return RefExecutor().execute(item)

    class CrashingVerifier:
        actor = ActorRef(role="Verifier", version="ref-v0")

        def verify(self, output, goal):
            raise RuntimeError("crash during verify (after the execute marker was written)")

    # L1 flow: start pauses; the first resume runs the executor + writes the marker, then verify
    # crashes — leaving an execute marker with no verdict.
    CellHandbrake(director=RefDirector(), orchestrator=L1Orchestrator(),
                  executor=CountingExecutor(), verifier=CrashingVerifier(),
                  store=store).start(_ticket(), "f1")
    with pytest.raises(RuntimeError):
        CellHandbrake(director=RefDirector(), orchestrator=L1Orchestrator(),
                      executor=CountingExecutor(), verifier=CrashingVerifier(),
                      store=store).resume("f1")
    assert calls["n"] == 1  # executor ran once; the marker is on the durable trail

    # A fresh controller resumes with a healthy verifier — it must NOT re-run the executor.
    verdict = CellHandbrake(director=RefDirector(), orchestrator=L1Orchestrator(),
                            executor=CountingExecutor(), verifier=RefVerifier(),
                            store=store).resume("f1")
    assert verdict.decision == "pass"
    assert calls["n"] == 1  # the Output was reconstructed from the durable marker, not re-produced


def test_resume_still_performs_the_work_item_effect_when_only_the_marker_was_written():
    # invariant #4: if a crash left only the execute marker (perform had not completed), a resume
    # that reconstructs the Output must still PERFORM the work-item effect (idempotently), never
    # skip it. perform() is keyed by output.id, so a completed effect returns cached.
    store = InMemoryEventStore()
    ledger = InMemoryEffectsLedger()
    hb = _handbrake(store=store, ledger=ledger)
    paused = hb.start(_ticket(), "f1")  # L1 -> pauses; nothing executed yet

    # Simulate a crash that wrote ONLY the execute marker (no perform completion, no verdict):
    item_id = paused.pending_action["work_item_id"]
    out_id = f"out-{item_id}"
    store.append("f1", "action", EXECUTOR,
                 {"stage": "execute", "output_id": out_id, "work_item_id": item_id,
                  "artifact_ref": f"branch://{item_id}", "attempt": 0})

    key = make_idempotency_key("f1", f"execute:{item_id}", {"output_id": out_id})
    assert ledger.get(key) is None  # the effect was not performed before the crash

    verdict = hb.resume("f1")
    assert verdict.decision == "pass"
    assert ledger.get(key).status == "completed"  # resume performed the effect, did not skip it
