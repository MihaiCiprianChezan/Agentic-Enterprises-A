"""Observability plane — full-trace capture + cost attribution (M3).

Realizes Build-Spec §3. Every step emits a `TraceSpan` — a session-level trajectory, not a
log line (model §5) — carrying the cost attributable to it (Rule C1). A flow's running cost
is the sum of its records' cost, which is the data the budget cap (Rule C2 / R7) and the
Steward (M7) later read. M3 captures the trace and the cost so a completed run is fully
replayable; enforcing the cap is M5/M7.

The trace is recorded in-process here (the reference store), mirroring the event plane: a
durable/OTel backend implements the same surface without changing callers (invariant #1).
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Iterator, Literal, Optional, Protocol, runtime_checkable

from cell.domain.objects import ActorRef
from cell.planes.memory import CostDelta

SpanKind = Literal["tool_call", "decision", "verification", "steward_action", "handbrake"]
SpanStatus = Literal["ok", "error", "paused"]


@dataclass
class TraceSpan:
    """Build-Spec §3.1 — one step's trajectory with its attributable cost."""
    flow_id: str
    step: str
    actor: ActorRef
    kind: SpanKind
    input_digest: str
    output_digest: str
    cost: CostDelta
    started_at: datetime
    ended_at: datetime
    status: SpanStatus = "ok"
    parent_span: Optional[str] = None


@runtime_checkable
class TraceStore(Protocol):
    """The observability plane's contract. Callers bind to this, never to a concrete store
    (invariant #1), so a durable/OTel backend swaps in without touching the flow."""

    def record(self, span: TraceSpan) -> None: ...
    def spans(self, flow_id: str) -> list[TraceSpan]: ...


class InMemoryTraceStore:
    """Reference trace store. A durable/OTel backend implements the same surface."""

    def __init__(self) -> None:
        self._spans: dict[str, list[TraceSpan]] = {}

    def record(self, span: TraceSpan) -> None:
        self._spans.setdefault(span.flow_id, []).append(span)

    def spans(self, flow_id: str) -> list[TraceSpan]:
        return list(self._spans.get(flow_id, []))


def digest(obj: Any) -> str:
    """A content digest (Build-Spec §3.1: a digest, not necessarily the full payload)."""
    return hashlib.sha256(repr(obj).encode("utf-8")).hexdigest()


def total_cost(records: Iterable[Any]) -> CostDelta:
    """Rule C1: a running cost is the sum of its records' cost. Accepts anything carrying a
    `.cost` (a TraceSpan or an Event); a missing/None cost counts as zero. `human_time_ms`
    stays None unless at least one record reports it.

    Costs in different `units` cannot be summed — mixing them raises rather than silently
    returning an ambiguous total."""
    compute = 0.0
    wall_clock_ms = 0
    human_time_ms: Optional[int] = None
    units: Optional[str] = None
    for record in records:
        cost = getattr(record, "cost", None)
        if cost is None:
            continue
        if units is None:
            units = cost.units
        elif cost.units != units:
            raise ValueError(f"cannot sum costs across mixed units: {units!r} vs {cost.units!r}")
        compute += cost.compute
        wall_clock_ms += cost.wall_clock_ms
        if cost.human_time_ms is not None:
            human_time_ms = (human_time_ms or 0) + cost.human_time_ms
    return CostDelta(compute=compute, wall_clock_ms=wall_clock_ms,
                     human_time_ms=human_time_ms, units=units or "tokens")


CostModel = Callable[[str], CostDelta]
Clock = Callable[[], datetime]


def _zero_cost(_step: str) -> CostDelta:
    return CostDelta()


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SpanHandle:
    """Mutable handle yielded inside a span so the caller can set the output digest (and,
    if it wants, override the cost) once the step's result is known."""
    output_digest: str = ""
    cost: Optional[CostDelta] = None


class Tracer:
    """Records a `TraceSpan` per step. When `store` is None it is a no-op recorder but still
    runs the wrapped body, so a flow behaves identically with or without observability wired.
    """

    def __init__(self, store: Optional[TraceStore], flow_id: str,
                 cost_model: Optional[CostModel] = None, clock: Optional[Clock] = None) -> None:
        self.store = store
        self.flow_id = flow_id
        self.cost_model = cost_model or _zero_cost
        self.clock = clock or _now

    @contextmanager
    def span(self, step: str, actor: ActorRef, kind: SpanKind, *,
             input_digest: str = "") -> Iterator[SpanHandle]:
        started_at = self.clock()
        handle = SpanHandle()
        status: SpanStatus = "ok"
        try:
            yield handle
        except Exception:
            status = "error"
            raise
        finally:
            ended_at = self.clock()
            # Attribute the actual measured wall-clock onto the cost — the span IS the authority on
            # duration, so it replaces wall_clock_ms. `compute`/`units` come from the caller-set cost
            # (e.g. a runtime's token usage) or the cost_model fallback. Set on the handle so the
            # caller can read the measured cost for the event it appends (cost-into-events).
            base = handle.cost if handle.cost is not None else self.cost_model(step)
            elapsed_ms = max(0, round((ended_at - started_at).total_seconds() * 1000))
            handle.cost = replace(base, wall_clock_ms=elapsed_ms)
            if self.store is not None:
                self.store.record(TraceSpan(
                    flow_id=self.flow_id, step=step, actor=actor, kind=kind,
                    input_digest=input_digest, output_digest=handle.output_digest,
                    cost=handle.cost, started_at=started_at, ended_at=ended_at, status=status,
                ))
