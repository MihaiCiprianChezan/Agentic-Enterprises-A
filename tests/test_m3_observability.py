"""M3 — observability: full-trace capture + cost attribution (Build-Spec §3).

Acceptance (build-plan M3): you can replay a completed run and read its full decision/cost
trace. Every step emits a TraceSpan carrying the cost attributable to it (Rule C1); a flow's
running cost is the sum of its records' cost. Enforcing the cap (C2/R7) is M5 — here we only
capture the data so the run is replayable.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cell.domain.objects import ActorRef, Ticket
from cell.flow import run_flow
from cell.planes.memory import CostDelta, InMemoryEventStore
from cell.planes.observability import (
    InMemoryTraceStore,
    TraceSpan,
    digest,
    total_cost,
)
from cell.roles.reference import RefDirector, RefExecutor, RefOrchestrator, RefVerifier

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _ticket(tid: str = "t1") -> Ticket:
    return Ticket(id=tid, source="legacy", title="Add feature X",
                  body="Please add feature X", received_at=_T0)


_COSTS = {
    "specify": CostDelta(compute=10),
    "decompose": CostDelta(compute=5),
    "execute": CostDelta(compute=100),
    "verify": CostDelta(compute=20),
}


def _cost_model(stage: str) -> CostDelta:
    return _COSTS[stage]


def _run(recorder=None, cost_model=None, executor=None, verifier=None, flow_id="f1"):
    store = InMemoryEventStore()
    verdict = run_flow(_ticket(), RefDirector(), RefOrchestrator(),
                       executor or RefExecutor(), verifier or RefVerifier(), store, flow_id,
                       recorder=recorder, cost_model=cost_model)
    return store, verdict


# --- a span per step ---------------------------------------------------------

def test_a_span_is_recorded_for_every_step():
    rec = InMemoryTraceStore()
    _run(recorder=rec, cost_model=_cost_model)
    by_step = {(s.step, s.kind, s.status) for s in rec.spans("f1")}
    assert ("specify", "decision", "ok") in by_step
    assert ("decompose", "decision", "ok") in by_step
    assert ("execute", "tool_call", "ok") in by_step
    assert ("verify", "verification", "ok") in by_step


def test_each_span_has_timing_and_digests():
    rec = InMemoryTraceStore()
    _run(recorder=rec, cost_model=_cost_model)
    for s in rec.spans("f1"):
        assert isinstance(s, TraceSpan)
        assert s.started_at <= s.ended_at
        assert s.input_digest and s.output_digest  # content digests, not full payloads


# --- cost attribution (Rule C1) ----------------------------------------------

def test_cost_is_attributed_per_step_and_summed_on_spans():
    rec = InMemoryTraceStore()
    _run(recorder=rec, cost_model=_cost_model)
    assert total_cost(rec.spans("f1")).compute == 135  # 10 + 5 + 100 + 20


def test_running_cost_sums_the_event_records_too():
    # C1: a flow's running cost is the sum of its records' cost — events carry it as well.
    store, _ = _run(recorder=InMemoryTraceStore(), cost_model=_cost_model)
    assert total_cost(store.read("f1")).compute == 135


def test_total_cost_sums_all_fields():
    class R:
        def __init__(self, cost):
            self.cost = cost
    items = [R(CostDelta(compute=10, wall_clock_ms=100)),
             R(CostDelta(compute=5, wall_clock_ms=50, human_time_ms=30)),
             R(None)]
    t = total_cost(items)
    assert t.compute == 15
    assert t.wall_clock_ms == 150
    assert t.human_time_ms == 30


# --- error capture -----------------------------------------------------------

def test_a_failing_step_is_recorded_with_error_status():
    class BoomExecutor:
        actor = ActorRef(role="Executor", version="boom")

        def execute(self, item):
            raise RuntimeError("execution blew up")

    rec = InMemoryTraceStore()
    with pytest.raises(RuntimeError):
        _run(recorder=rec, cost_model=_cost_model, executor=BoomExecutor())
    execute_spans = [s for s in rec.spans("f1") if s.step == "execute"]
    assert execute_spans and execute_spans[-1].status == "error"


# --- replay (the acceptance) -------------------------------------------------

def test_replay_reads_the_full_ordered_cost_trace():
    rec = InMemoryTraceStore()
    _run(recorder=rec, cost_model=_cost_model)
    spans = rec.spans("f1")
    assert [s.step for s in spans] == ["specify", "decompose", "execute", "verify"]
    assert total_cost(spans).compute == 135


# --- the plane is optional (M2 back-compat) ----------------------------------

def test_observability_is_optional():
    store, verdict = _run()  # no recorder, no cost model
    assert verdict.decision == "pass"
    assert total_cost(store.read("f1")).compute == 0  # no cost wired -> zero


# --- digest helper -----------------------------------------------------------

def test_digest_is_stable_and_distinguishing():
    assert digest("abc") == digest("abc")
    assert digest("abc") != digest("abd")
