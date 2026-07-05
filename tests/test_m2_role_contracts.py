"""M2 — roles as contracts (One-Cell-Build-Plan §6; Role-Contracts.md).

Acceptance: the system binds to the role *contracts* (Protocols), and an implementer
behind any one role can be swapped without touching the others or the wiring (invariant #1).
The flow also records each handoff to the event plane (invariant #5) and enforces the
Verifier-independence gate structurally (Constitution Art. 5.1 / Build-Spec R5).
"""

from __future__ import annotations

from datetime import datetime

import pytest

from cell.domain.objects import ActorRef, CriterionScore, Output, Ticket, Verdict
from cell.flow import EmptyDecomposition, NonIndependentVerification, run_flow
from cell.planes.memory import InMemoryEventStore
from cell.roles.contracts import Director, Executor, Orchestrator, Verifier
from cell.roles.reference import RefDirector, RefExecutor, RefOrchestrator, RefVerifier

_T0 = datetime(2026, 1, 1)


def _ticket(tid: str = "t1") -> Ticket:
    return Ticket(
        id=tid, source="legacy", title="Add feature X", body="Please add feature X", received_at=_T0
    )


# --- binding: the reference implementers satisfy their contracts --------------


def test_reference_impls_satisfy_their_protocols():
    assert isinstance(RefDirector(), Director)
    assert isinstance(RefOrchestrator(), Orchestrator)
    assert isinstance(RefExecutor(), Executor)
    assert isinstance(RefVerifier(), Verifier)


# --- the flow composes the contracts end to end ------------------------------


def test_happy_path_runs_to_a_pass_verdict():
    store = InMemoryEventStore()
    verdict = run_flow(
        _ticket(), RefDirector(), RefOrchestrator(), RefExecutor(), RefVerifier(), store, "f1"
    )
    assert verdict.decision == "pass"


def test_flow_records_each_handoff_to_the_event_plane():
    # invariant #5: handoffs go through the durable event plane, not actor memory.
    store = InMemoryEventStore()
    run_flow(_ticket(), RefDirector(), RefOrchestrator(), RefExecutor(), RefVerifier(), store, "f1")
    stages = [e.payload.get("stage") for e in store.read("f1")]
    assert {"specify", "decompose", "execute", "verify"} <= set(stages)
    assert store.verify_chain("f1") is True


# --- the M2 acceptance: swap an implementer behind one role ------------------


def test_executor_is_swappable_without_touching_other_roles():
    class AltExecutor:
        """A different Execution implementer — same contract, different artifact."""

        def execute(self, item):
            return Output(
                id="alt-out",
                work_item_id=item.id,
                artifact_ref="branch://alt",
                produced_by=ActorRef(role="Executor", version="alt-v1"),
                trace_ref="trace://alt",
                produced_at=_T0,
            )

    assert isinstance(AltExecutor(), Executor)

    store_ref, store_alt = InMemoryEventStore(), InMemoryEventStore()
    ref = run_flow(
        _ticket(),
        RefDirector(),
        RefOrchestrator(),
        RefExecutor(),
        RefVerifier(),
        store_ref,
        "f-ref",
    )
    alt = run_flow(
        _ticket(),
        RefDirector(),
        RefOrchestrator(),
        AltExecutor(),
        RefVerifier(),
        store_alt,
        "f-alt",
    )

    # Same Director/Orchestrator/Verifier; only the Executor changed — and it really ran.
    assert ref.decision == "pass"
    assert alt.decision == "pass"
    exec_event = next(e for e in store_alt.read("f-alt") if e.payload.get("stage") == "execute")
    assert exec_event.payload["artifact_ref"] == "branch://alt"


# --- R5: verification is independent of production ---------------------------


def test_reference_verifier_is_independent_of_producer():
    goal = RefDirector().specify(_ticket())
    item = RefOrchestrator().decompose(goal)[0]
    output = RefExecutor().execute(item)
    verdict = RefVerifier().verify(output, goal)
    assert verdict.verified_by != output.produced_by


def test_flow_rejects_non_independent_verification():
    class CapturingExecutor:
        def execute(self, item):
            return Output(
                id="o",
                work_item_id=item.id,
                artifact_ref="a",
                produced_by=ActorRef(role="Executor", version="x"),
                trace_ref="t",
                produced_at=_T0,
            )

    class CollusiveVerifier:
        def verify(self, output, goal):
            # Signs with the producer's identity — must be rejected structurally (R5).
            return Verdict(
                id="v",
                output_id=output.id,
                decision="pass",
                scores=[],
                reason="ok",
                verified_by=output.produced_by,
                verified_at=_T0,
            )

    store = InMemoryEventStore()
    with pytest.raises(NonIndependentVerification):
        run_flow(
            _ticket(),
            RefDirector(),
            RefOrchestrator(),
            CapturingExecutor(),
            CollusiveVerifier(),
            store,
            "f1",
        )


# --- produce -> score -> revise loop -----------------------------------------


def test_return_verdict_triggers_revision_then_passes():
    class FlakyVerifier:
        def __init__(self):
            self.calls = 0

        def verify(self, output, goal):
            self.calls += 1
            decision = "return" if self.calls == 1 else "pass"
            return Verdict(
                id=f"v{self.calls}",
                output_id=output.id,
                decision=decision,
                scores=[CriterionScore(criterion_id="c", result="met")],
                reason="revise" if decision == "return" else "ok",
                verified_by=ActorRef(role="Verifier", version="ref-v0"),
                verified_at=_T0,
            )

    store = InMemoryEventStore()
    fv = FlakyVerifier()
    verdict = run_flow(_ticket(), RefDirector(), RefOrchestrator(), RefExecutor(), fv, store, "f1")
    assert verdict.decision == "pass"
    assert fv.calls == 2  # one return, then one pass


# --- review fixes: totality, attribution, reconstructibility -----------------


def test_empty_decomposition_raises_rather_than_returning_none():
    # run_flow is total: an Orchestrator that yields no work items is an error, not a
    # silent None return that would crash downstream on `.decision`.
    class EmptyOrchestrator:
        def decompose(self, goal):
            return []

    store = InMemoryEventStore()
    with pytest.raises(EmptyDecomposition):
        run_flow(
            _ticket(), RefDirector(), EmptyOrchestrator(), RefExecutor(), RefVerifier(), store, "f1"
        )
    # the anomaly is recorded for traceability before raising
    assert any(e.payload.get("stage") == "decompose" for e in store.read("f1"))


def test_decompose_event_attributes_the_actual_orchestrator():
    # Swapping the Orchestrator must not misattribute the decomposition in the log.
    class TaggedOrchestrator:
        actor = ActorRef(role="Orchestrator", version="alt-orch-v9")

        def decompose(self, goal):
            return RefOrchestrator().decompose(goal)

    store = InMemoryEventStore()
    run_flow(
        _ticket(), RefDirector(), TaggedOrchestrator(), RefExecutor(), RefVerifier(), store, "f1"
    )
    event = next(e for e in store.read("f1") if e.payload.get("stage") == "decompose")
    assert event.actor == ActorRef(role="Orchestrator", version="alt-orch-v9")


def test_verdict_event_links_to_its_output_and_work_item():
    # The event log alone must let you reconstruct which artifact a verdict applied to.
    store = InMemoryEventStore()
    run_flow(_ticket(), RefDirector(), RefOrchestrator(), RefExecutor(), RefVerifier(), store, "f1")
    event = next(e for e in store.read("f1") if e.payload.get("stage") == "verify")
    assert "output_id" in event.payload and "work_item_id" in event.payload
