"""Event / memory plane — durable, append-only, hash-chained, resumable state.

Realizes Build-Spec.md §2. State lives outside the actor (invariant #5).
Everything resumable is reconstructed from the event log.

M0 target: a minimal, correct EventStore (append-only + hash chain + checkpoints).
The default backing store for one cell is SQLite or Postgres, one `events` table
(Component-Selection.md). This module defines the interface and an in-memory reference
implementation usable by tests; a durable backend implements the same Protocol.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Optional, Protocol, runtime_checkable

from cell.domain.objects import ActorRef

EventKind = Literal[
    "decision", "action", "state", "breakpoint",
    "injection", "verdict", "escalation", "governance",
]


@dataclass(frozen=True)
class CostDelta:
    compute: float = 0.0
    wall_clock_ms: int = 0
    human_time_ms: Optional[int] = None
    units: str = "tokens"


@dataclass(frozen=True)
class Event:
    """Append-only, hash-chained unit (Build-Spec §2.1). `hash` = H(prev_hash + payload)."""
    seq: int
    flow_id: str
    prev_hash: str
    hash: str
    kind: EventKind
    actor: ActorRef
    payload: dict[str, Any]
    at: datetime
    cost: Optional[CostDelta] = None


@dataclass
class Checkpoint:
    """Exact resumable state (Build-Spec §2.2)."""
    flow_id: str
    at_seq: int
    step: str
    state_snapshot: dict[str, Any]
    created_at: datetime
    pending_action: Optional[dict[str, Any]] = None


@dataclass
class Decision:
    """The 'why', not just the 'what' (Build-Spec §2.3)."""
    flow_id: str
    seq: int
    question: str
    chosen: str
    rationale: str
    confidence: float
    actor: ActorRef
    alternatives: list[str] = field(default_factory=list)


@dataclass
class VersionRecord:
    """Version-registry stub (Build-Spec §2.4). One active version per role in the MVP."""
    role: str
    version: str
    activated_at: datetime
    variant_of: Optional[str] = None
    status: Literal["active", "rolled_back"] = "active"


def compute_hash(prev_hash: str, payload: dict[str, Any]) -> str:
    """Tamper-evident chain link (Constitution Art. 10.3)."""
    blob = prev_hash + json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@runtime_checkable
class EventStore(Protocol):
    """The durable plane's contract. Any backend (SQLite, Postgres, durable engine)
    implements this. Guarantees: append-only, gap-free monotonic seq per flow,
    hash-chained, and resumable via checkpoints."""

    def append(self, flow_id: str, kind: EventKind, actor: ActorRef,
               payload: dict[str, Any], cost: Optional[CostDelta] = None) -> Event:
        """Append an event, computing seq and hash. MUST be atomic."""
        ...

    def read(self, flow_id: str) -> list[Event]:
        """Return the full ordered event history for a flow."""
        ...

    def verify_chain(self, flow_id: str) -> bool:
        """Recompute the hash chain; return False if any link is broken (Art. 10.3)."""
        ...

    def checkpoint(self, cp: Checkpoint) -> None:
        ...

    def latest_checkpoint(self, flow_id: str) -> Optional[Checkpoint]:
        ...


# --- in-memory reference implementation (for tests / the M0 spike) -----------
# A durable implementation (SQLite/Postgres) replaces this class but keeps the contract.

class InMemoryEventStore:
    """Reference EventStore. Correct, not durable. Good enough for the M0 test;
    swap for a persistent backend at M1 (Component-Selection.md)."""

    def __init__(self) -> None:
        self._events: dict[str, list[Event]] = {}
        self._checkpoints: dict[str, Checkpoint] = {}

    def append(self, flow_id, kind, actor, payload, cost=None) -> Event:
        log = self._events.setdefault(flow_id, [])
        prev_hash = log[-1].hash if log else "GENESIS"
        seq = len(log)
        h = compute_hash(prev_hash, payload)
        ev = Event(seq=seq, flow_id=flow_id, prev_hash=prev_hash, hash=h,
                   kind=kind, actor=actor, payload=payload, at=datetime.utcnow(), cost=cost)
        log.append(ev)
        return ev

    def read(self, flow_id) -> list[Event]:
        return list(self._events.get(flow_id, []))

    def verify_chain(self, flow_id) -> bool:
        prev = "GENESIS"
        for ev in self._events.get(flow_id, []):
            if ev.prev_hash != prev or ev.hash != compute_hash(prev, ev.payload):
                return False
            prev = ev.hash
        return True

    def checkpoint(self, cp: Checkpoint) -> None:
        self._checkpoints[cp.flow_id] = cp

    def latest_checkpoint(self, flow_id) -> Optional[Checkpoint]:
        return self._checkpoints.get(flow_id)
