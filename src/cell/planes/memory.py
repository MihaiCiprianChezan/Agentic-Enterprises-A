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
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from os import PathLike
from typing import Any, Literal, Protocol, runtime_checkable

from cell.domain.objects import ActorRef

EventKind = Literal[
    "decision",
    "action",
    "state",
    "breakpoint",
    "injection",
    "verdict",
    "escalation",
    "governance",
    "version",
    "audit",
]


@dataclass(frozen=True)
class CostDelta:
    compute: float = 0.0
    wall_clock_ms: int = 0
    human_time_ms: int | None = None
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
    cost: CostDelta | None = None


@dataclass
class Checkpoint:
    """Exact resumable state (Build-Spec §2.2)."""

    flow_id: str
    at_seq: int
    step: str
    state_snapshot: dict[str, Any]
    created_at: datetime
    pending_action: dict[str, Any] | None = None


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
    variant_of: str | None = None
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

    def append(
        self,
        flow_id: str,
        kind: EventKind,
        actor: ActorRef,
        payload: dict[str, Any],
        cost: CostDelta | None = None,
    ) -> Event:
        """Append an event, computing seq and hash. MUST be atomic."""
        ...

    def read(self, flow_id: str) -> list[Event]:
        """Return the full ordered event history for a flow."""
        ...

    def all_events(self) -> list[Event]:
        """Every event across all flows — the cross-flow signal the Steward/Optimizer/Auditor read
        (model §5). Ordered by flow then seq."""
        ...

    def verify_chain(self, flow_id: str) -> bool:
        """Recompute the hash chain; return False if any link is broken (Art. 10.3)."""
        ...

    def checkpoint(self, cp: Checkpoint) -> None: ...

    def latest_checkpoint(self, flow_id: str) -> Checkpoint | None: ...


# --- in-memory reference implementation (for tests / the M0 spike) -----------
# A durable implementation (SQLite/Postgres) replaces this class but keeps the contract.


class InMemoryEventStore:
    """Reference EventStore. Correct, not durable. Good enough for the M0 test;
    swap for a persistent backend at M1 (Component-Selection.md)."""

    def __init__(self) -> None:
        self._events: dict[str, list[Event]] = {}
        self._checkpoints: dict[str, Checkpoint] = {}

    def append(
        self,
        flow_id: str,
        kind: EventKind,
        actor: ActorRef,
        payload: dict[str, Any],
        cost: CostDelta | None = None,
    ) -> Event:
        log = self._events.setdefault(flow_id, [])
        prev_hash = log[-1].hash if log else "GENESIS"
        seq = len(log)
        h = compute_hash(prev_hash, payload)
        ev = Event(
            seq=seq,
            flow_id=flow_id,
            prev_hash=prev_hash,
            hash=h,
            kind=kind,
            actor=actor,
            payload=payload,
            at=datetime.now(UTC),
            cost=cost,
        )
        log.append(ev)
        return ev

    def read(self, flow_id: str) -> list[Event]:
        return list(self._events.get(flow_id, []))

    def all_events(self) -> list[Event]:
        events = [ev for log in self._events.values() for ev in log]
        return sorted(
            events, key=lambda e: (e.flow_id, e.seq)
        )  # match the Protocol + durable order

    def verify_chain(self, flow_id: str) -> bool:
        prev = "GENESIS"
        for ev in self._events.get(flow_id, []):
            if ev.prev_hash != prev or ev.hash != compute_hash(prev, ev.payload):
                return False
            prev = ev.hash
        return True

    def checkpoint(self, cp: Checkpoint) -> None:
        self._checkpoints[cp.flow_id] = cp

    def latest_checkpoint(self, flow_id: str) -> Checkpoint | None:
        return self._checkpoints.get(flow_id)


# --- durable implementation (SQLite) -----------------------------------------
# Same Protocol as InMemoryEventStore (invariant #1); history survives process
# death (M0-Implementation-Notes Step 1). One append-only `events` table, one
# `checkpoints` table. SQLite is enough for one cell (Component-Selection.md).

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    flow_id   TEXT    NOT NULL,
    seq       INTEGER NOT NULL,
    prev_hash TEXT    NOT NULL,
    hash      TEXT    NOT NULL,
    kind      TEXT    NOT NULL,
    actor     TEXT    NOT NULL,   -- JSON(ActorRef)
    payload   TEXT    NOT NULL,   -- JSON, canonical (sort_keys) so the hash chain reproduces
    cost      TEXT,               -- JSON(CostDelta) or NULL
    at        TEXT    NOT NULL,   -- ISO-8601
    PRIMARY KEY (flow_id, seq)    -- gap-free monotonic seq; racing append fails, not forks
);
CREATE TABLE IF NOT EXISTS checkpoints (
    flow_id        TEXT    NOT NULL,
    at_seq         INTEGER NOT NULL,
    step           TEXT    NOT NULL,
    state_snapshot TEXT    NOT NULL,   -- JSON
    pending_action TEXT,               -- JSON or NULL
    created_at     TEXT    NOT NULL    -- ISO-8601
);
"""


class DurableEventStore:
    """SQLite-backed EventStore. Correct AND durable: a fresh instance on the same
    DB re-reads the full hash-chained history. Implements the EventStore Protocol."""

    def __init__(self, path: str | PathLike) -> None:
        self._path = str(path)
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # -- EventStore Protocol --------------------------------------------------

    def append(
        self,
        flow_id: str,
        kind: EventKind,
        actor: ActorRef,
        payload: dict[str, Any],
        cost: CostDelta | None = None,
    ) -> Event:
        # The contract takes an ActorRef; require it so the returned Event.actor and the
        # reloaded read() actor are the same type (asdict raises on anything else).
        actor_json = json.dumps(asdict(actor))
        payload_json = json.dumps(payload, sort_keys=True, default=str)
        cost_json = None if cost is None else json.dumps(asdict(cost))
        at = datetime.now(UTC)
        # Atomic: read the tail and insert in one transaction. The (flow_id, seq)
        # unique key means a concurrent append on the same tail fails rather than
        # forking the chain (M0-Implementation-Notes Step 1).
        with self._conn:
            row = self._conn.execute(
                "SELECT seq, hash FROM events WHERE flow_id = ? ORDER BY seq DESC LIMIT 1",
                (flow_id,),
            ).fetchone()
            if row is None:
                seq, prev_hash = 0, "GENESIS"
            else:
                seq, prev_hash = row["seq"] + 1, row["hash"]
            h = compute_hash(prev_hash, json.loads(payload_json))
            self._conn.execute(
                "INSERT INTO events (flow_id, seq, prev_hash, hash, kind, actor, payload, cost, at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    flow_id,
                    seq,
                    prev_hash,
                    h,
                    kind,
                    actor_json,
                    payload_json,
                    cost_json,
                    at.isoformat(),
                ),
            )
        return Event(
            seq=seq,
            flow_id=flow_id,
            prev_hash=prev_hash,
            hash=h,
            kind=kind,
            actor=actor,
            payload=json.loads(payload_json),
            at=at,
            cost=cost,
        )

    def read(self, flow_id: str) -> list[Event]:
        rows = self._conn.execute(
            "SELECT * FROM events WHERE flow_id = ? ORDER BY seq", (flow_id,)
        ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def all_events(self) -> list[Event]:
        rows = self._conn.execute("SELECT * FROM events ORDER BY flow_id, seq").fetchall()
        return [self._row_to_event(r) for r in rows]

    def verify_chain(self, flow_id: str) -> bool:
        prev = "GENESIS"
        for ev in self.read(flow_id):
            if ev.prev_hash != prev or ev.hash != compute_hash(prev, ev.payload):
                return False
            prev = ev.hash
        return True

    def checkpoint(self, cp: Checkpoint) -> None:
        created = cp.created_at or datetime.now(UTC)
        with self._conn:
            self._conn.execute(
                "INSERT INTO checkpoints (flow_id, at_seq, step, state_snapshot, pending_action, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    cp.flow_id,
                    cp.at_seq,
                    cp.step,
                    json.dumps(cp.state_snapshot, default=str),
                    None
                    if cp.pending_action is None
                    else json.dumps(cp.pending_action, default=str),
                    created.isoformat(),
                ),
            )

    def latest_checkpoint(self, flow_id: str) -> Checkpoint | None:
        row = self._conn.execute(
            "SELECT * FROM checkpoints WHERE flow_id = ? ORDER BY rowid DESC LIMIT 1",
            (flow_id,),
        ).fetchone()
        if row is None:
            return None
        return Checkpoint(
            flow_id=row["flow_id"],
            at_seq=row["at_seq"],
            step=row["step"],
            state_snapshot=json.loads(row["state_snapshot"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            pending_action=None
            if row["pending_action"] is None
            else json.loads(row["pending_action"]),
        )

    def close(self) -> None:
        self._conn.close()

    # -- helpers --------------------------------------------------------------

    @staticmethod
    def _row_to_event(r: sqlite3.Row) -> Event:
        return Event(
            seq=r["seq"],
            flow_id=r["flow_id"],
            prev_hash=r["prev_hash"],
            hash=r["hash"],
            kind=r["kind"],
            actor=ActorRef(**json.loads(r["actor"])),
            payload=json.loads(r["payload"]),
            at=datetime.fromisoformat(r["at"]),
            cost=None if r["cost"] is None else CostDelta(**json.loads(r["cost"])),
        )
