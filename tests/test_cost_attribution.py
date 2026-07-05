"""Cost-into-events: events carry real measured cost (wall-clock + reported tokens), and start()
re-entry reuses a recorded flow instead of re-emitting its prefix.

Deterministic and offline: a fixed clock makes measured wall-clock exact; a fake executor reports
token cost; no LLM, no network.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from cell.cell import Cell
from cell.domain.objects import ActorRef, Ticket
from cell.planes.memory import CostDelta, InMemoryEventStore
from cell.planes.observability import InMemoryTraceStore, Tracer

_T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _clock(*offsets_ms):
    """A deterministic clock returning _T0 + each offset (ms) in turn — one call per span edge."""
    times = iter([_T0 + timedelta(milliseconds=o) for o in offsets_ms])
    return lambda: next(times)


def _ticking_clock(step_ms=10):
    """A monotonic clock advancing step_ms per call, so each span (two calls) measures step_ms."""
    n = {"i": 0}

    def clock():
        t = _T0 + timedelta(milliseconds=step_ms * n["i"])
        n["i"] += 1
        return t

    return clock


def _ticket(tid="t1"):
    return Ticket(id=tid, source="x", title="t", body="b", received_at=_T0)


def test_span_attributes_measured_wall_clock_to_handle_and_span():
    store = InMemoryTraceStore()
    tr = Tracer(store, "f", clock=_clock(0, 250))  # started, ended
    with tr.span("execute", ActorRef("Executor", "ref"), "tool_call") as h:
        pass
    assert h.cost.wall_clock_ms == 250  # readable by the handbrake for the event
    assert store.spans("f")[0].cost.wall_clock_ms == 250  # and recorded on the span


def test_span_merges_caller_reported_compute_with_measured_wall_clock():
    store = InMemoryTraceStore()
    tr = Tracer(store, "f", clock=_clock(0, 100))
    with tr.span("execute", ActorRef("Executor", "ref"), "tool_call") as h:
        h.cost = CostDelta(compute=1234)  # the executor's token cost
    assert h.cost.compute == 1234
    assert h.cost.wall_clock_ms == 100  # wall-clock folded in, compute preserved


def test_handbrake_events_carry_measured_wall_clock():
    # The execute event (and every traced step) records the span's measured wall-clock, not the
    # _ecost stub. A monotonic +10ms clock makes each span measure exactly 10ms.
    cell = Cell.assemble(clock=_ticking_clock(10))
    cell.submit(_ticket(), "f")
    execs = [e for e in cell.events("f") if e.payload.get("stage") == "execute"]
    assert execs and execs[0].cost is not None
    assert execs[0].cost.wall_clock_ms == 10


class _TokenExecutor:
    """A fake executor that reports a runtime's token cost on its Output."""

    def execute(self, item):
        from cell.domain.objects import Output

        return Output(
            id=f"out-{item.id}",
            work_item_id=item.id,
            artifact_ref="branch:x",
            produced_by=ActorRef("Executor", "fake"),
            trace_ref="trace://x",
            produced_at=_T0,
            cost=CostDelta(compute=4096),
        )


def test_execute_event_carries_executor_reported_tokens_plus_wall_clock():
    cell = Cell.assemble(executor=_TokenExecutor(), clock=_ticking_clock(10))
    cell.submit(_ticket(), "f")
    ev = [e for e in cell.events("f") if e.payload.get("stage") == "execute"][0]
    assert ev.cost.compute == 4096  # the runtime's tokens
    assert ev.cost.wall_clock_ms == 10  # merged with the span's measured wall-clock


# --- start() re-entry --------------------------------------------------------


def test_reentry_of_a_completed_flow_returns_the_verdict_and_adds_no_events():
    cell = Cell.assemble()
    v1 = cell.submit(_ticket(), "f")
    n1 = len(cell.events("f"))
    v2 = cell.submit(_ticket(), "f")  # re-invoke the same flow_id
    assert v2.decision == v1.decision
    assert len(cell.events("f")) == n1  # idempotent: zero new events


class _BoomExecutor:
    def execute(self, item):
        raise RuntimeError("boom")  # crash after the prefix, before the execute marker


def test_reentry_of_a_crashed_flow_reuses_the_prefix_without_duplicating_it():
    store = InMemoryEventStore()
    with pytest.raises(RuntimeError):
        Cell.assemble(store=store, executor=_BoomExecutor()).submit(_ticket(), "f")
    assert len([e for e in store.read("f") if e.payload.get("stage") == "specify"]) == 1

    v = Cell.assemble(store=store).submit(_ticket(), "f")  # re-enter with a working executor
    assert v.decision == "pass"
    assert (
        len([e for e in store.read("f") if e.payload.get("stage") == "specify"]) == 1
    )  # not duplicated
    assert len([e for e in store.read("f") if e.payload.get("stage") == "execute"]) == 1


def test_start_after_a_prestart_breakpoint_runs_the_fresh_prefix_not_reentry():
    # A breakpoint set BEFORE start() writes an event, but the flow has not started — start() must
    # still emit the fresh specify/decompose prefix, not mistake it for a re-entry.
    store = InMemoryEventStore()
    cell = Cell.assemble(store=store)
    cell.handbrake.set_breakpoint("f", "pre-execute:other-item")  # event exists before start
    cell.submit(_ticket(), "f")
    assert len([e for e in store.read("f") if e.payload.get("stage") == "specify"]) == 1
