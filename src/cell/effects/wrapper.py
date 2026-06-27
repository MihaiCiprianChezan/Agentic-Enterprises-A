"""The idempotent-action wrapper — M0's core mechanic.

Realizes Build-Spec.md §4. No role performs an external side effect directly;
every effect goes through `perform()`. This is the guarantee the whole Handbrake
rests on (invariant #4): resume never re-fires a completed effect and never skips
one that did not happen.

Effect kinds (Build-Spec §4.2 step 3):
  - "idempotent"   : yours / reversible            -> exactly-once on resume
  - "compensable"  : reversible with effort        -> exactly-once + recorded compensation
  - "irreversible" : owned by a non-idempotent outsider -> AT-MOST-ONCE attempt + compensation
                     where one exists. The outside world is never assumed idempotent.

M0 deliverable: implement `perform()` against an effects ledger so that killing the
process at any point and re-running cannot double-fire an effect. The reference
ledger here is in-memory; a durable ledger (same table the EventStore uses) makes
it survive process death — that is the M0 acceptance test (tests/test_m0_idempotency.py).
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from os import PathLike
from typing import TYPE_CHECKING, Any, Callable, Literal, Optional, Protocol, Union

if TYPE_CHECKING:  # type-only; avoids a runtime import while binding to the contract (#1)
    from cell.planes.memory import EventStore

EffectKind = Literal["idempotent", "compensable", "irreversible"]


@dataclass(frozen=True)
class ActionDescriptor:
    """Build-Spec §4.1. `idempotency_key` is deterministic for 'the same effect'."""
    id: str
    action_class: str
    effect_kind: EffectKind
    idempotency_key: str
    intent: dict[str, Any]
    compensation: Optional[dict[str, Any]] = None


@dataclass
class EffectRecord:
    """Build-Spec §4.2. `attempts` exists for at-most-once accounting on irreversible effects."""
    idempotency_key: str
    status: Literal["in_flight", "completed", "failed"]
    attempts: int = 0
    result_digest: Optional[str] = None
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def make_idempotency_key(flow_id: str, step: str, intent: dict[str, Any]) -> str:
    """Deterministic key so the same logical effect maps to the same ledger row."""
    blob = f"{flow_id}|{step}|{sorted(intent.items())}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class EffectsLedger(Protocol):
    """Durable record of every external effect, keyed by idempotency_key."""

    def get(self, key: str) -> Optional[EffectRecord]: ...
    def put_in_flight(self, key: str) -> EffectRecord: ...
    def mark_completed(self, key: str, result_digest: str) -> None: ...
    def mark_failed(self, key: str) -> None: ...


class GovernanceCheck(Protocol):
    """Pre-effect governance evaluation (Build-Spec §5 / rule R6).
    Returns (allowed, reason). M5 implements the real rule set; for the M0 spike a
    permissive stub is injected."""

    def evaluate(self, action: ActionDescriptor, actor: Any) -> tuple[bool, str]: ...


class GovernanceBlocked(Exception):
    """Raised when the pre-effect governance check blocks an action (R6). The effect
    is never executed."""


class IrreversibleInFlight(Exception):
    """Raised when an `irreversible` effect is found already `in_flight` on resume.
    Re-attempting could double-fire an un-undoable outside effect, so the wrapper
    refuses and escalates for human resolution (at-most-once; invariant #4)."""


def perform(
    action: ActionDescriptor,
    actor: Any,
    execute: Callable[[ActionDescriptor], str],
    ledger: EffectsLedger,
    governance: GovernanceCheck,
    store: Optional["EventStore"] = None,
    flow_id: Optional[str] = None,
) -> str:
    """Execute an external effect exactly-once / at-most-once across resume.

    Protocol (Build-Spec §4.2):
      1. Pre-check governance (R6). If blocked -> raise, do not execute.
      2. Look up the idempotency key:
           completed -> return prior result, DO NOT re-execute   (the exactly-once guarantee)
           in_flight -> for idempotent/compensable, safe to re-attempt; for irreversible,
                        DO NOT re-attempt (at-most-once) -> raise for human resolution.
           absent    -> record in_flight, then execute.
      3. Record completion in the ledger.
      4. When a `store`/`flow_id` is wired, append one `action` Event (only on first
         completion, never on a cached resume).

    The load-bearing detail (M0-Implementation-Notes Step 2): the `in_flight` row is
    committed by the ledger BEFORE `execute` fires, and `completed` only AFTER it
    returns. A crash in between leaves an `in_flight` record, and recovery is decided
    by `effect_kind` — never by guessing whether the effect happened.
    """
    # 1. Pre-check governance (R6). Blocked -> do not execute.
    allowed, reason = governance.evaluate(action, actor)
    if not allowed:
        raise GovernanceBlocked(reason)

    key = action.idempotency_key

    # 2. Look up the idempotency key.
    rec = ledger.get(key)
    if rec is not None:
        if rec.status == "completed":
            # The exactly-once guarantee: never re-execute a completed effect.
            return rec.result_digest
        if rec.status == "in_flight":
            if action.effect_kind == "irreversible":
                # At-most-once: a prior attempt may have already fired an effect we
                # cannot un-send. Refuse and escalate rather than risk a double-fire.
                raise IrreversibleInFlight(
                    f"irreversible effect {key} is in_flight; refusing to re-attempt"
                )
            # idempotent / compensable: re-attempt is safe -> fall through to execute.
        elif rec.status == "failed" and action.effect_kind == "irreversible":
            # A failed irreversible attempt may still have taken effect outside; do
            # not retry blindly. Escalate.
            raise IrreversibleInFlight(
                f"irreversible effect {key} previously failed; refusing to re-attempt"
            )

    # 3. Record in_flight BEFORE executing (durably, so a crash is recoverable).
    ledger.put_in_flight(key)
    try:
        result = execute(action)
    except Exception:
        # idempotent/compensable may retry on a later resume; irreversible escalates.
        ledger.mark_failed(key)
        raise

    # 4. Record completion in the ledger and, when a store is wired, as an `action`
    #    Event on the event plane (Build-Spec §4.2 step 4 / §6). The Event is appended
    #    only on first completion — a cached resume returns above without re-appending,
    #    so exactly-once extends to the log too. (Cost attribution is M3.)
    ledger.mark_completed(key, result)
    if store is not None and flow_id is not None:
        store.append(flow_id, "action", actor, {
            "action_id": action.id,
            "action_class": action.action_class,
            "effect_kind": action.effect_kind,
            "idempotency_key": key,
            "result_digest": result,
        })
    return result


# --- in-memory reference ledger (for the M0 spike / tests) -------------------

class InMemoryEffectsLedger:
    """Correct, not durable. The M0 acceptance test must pass with a DURABLE ledger
    (survives process death); this in-memory one is for fast unit tests of the logic."""

    def __init__(self) -> None:
        self._records: dict[str, EffectRecord] = {}

    def get(self, key):
        return self._records.get(key)

    def put_in_flight(self, key):
        rec = self._records.get(key)
        if rec is None:
            rec = EffectRecord(idempotency_key=key, status="in_flight", attempts=0)
        rec.attempts += 1
        rec.status = "in_flight"
        self._records[key] = rec
        return rec

    def mark_completed(self, key, result_digest):
        rec = self._records[key]
        rec.status = "completed"
        rec.result_digest = result_digest

    def mark_failed(self, key):
        rec = self._records[key]
        rec.status = "failed"


# --- durable effects ledger (SQLite) -----------------------------------------
# The ledger the M0 acceptance gate runs against: it survives process death, so a
# crash between `in_flight` and `completed` is recoverable (M0-Implementation-Notes
# Step 2). Same EffectsLedger Protocol as the in-memory one (invariant #1).

_LEDGER_SCHEMA = """
CREATE TABLE IF NOT EXISTS effects (
    idempotency_key TEXT PRIMARY KEY,
    status          TEXT    NOT NULL,   -- in_flight | completed | failed
    attempts        INTEGER NOT NULL DEFAULT 0,
    result_digest   TEXT,
    at              TEXT    NOT NULL    -- ISO-8601
);
"""


class SqliteEffectsLedger:
    """Durable EffectsLedger. Each mutating call commits before returning, so an
    `in_flight` row recorded before a side effect survives a crash mid-effect."""

    def __init__(self, path: Union[str, PathLike]) -> None:
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_LEDGER_SCHEMA)
        self._conn.commit()

    def get(self, key: str) -> Optional[EffectRecord]:
        row = self._conn.execute(
            "SELECT * FROM effects WHERE idempotency_key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        return EffectRecord(
            idempotency_key=row["idempotency_key"], status=row["status"],
            attempts=row["attempts"], result_digest=row["result_digest"],
            at=datetime.fromisoformat(row["at"]),
        )

    def put_in_flight(self, key: str) -> EffectRecord:
        # Insert-or-bump in one committed transaction. The commit is what makes the
        # in-flight marker outlive a crash in the subsequent effect.
        now = datetime.now(timezone.utc).isoformat()
        with self._conn:
            self._conn.execute(
                "INSERT INTO effects (idempotency_key, status, attempts, at) "
                "VALUES (?, 'in_flight', 1, ?) "
                "ON CONFLICT(idempotency_key) DO UPDATE SET "
                "status = 'in_flight', attempts = attempts + 1",
                (key, now),
            )
        return self.get(key)

    def mark_completed(self, key: str, result_digest: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE effects SET status = 'completed', result_digest = ? "
                "WHERE idempotency_key = ?",
                (result_digest, key),
            )

    def mark_failed(self, key: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE effects SET status = 'failed' WHERE idempotency_key = ?", (key,)
            )

    def close(self) -> None:
        self._conn.close()
