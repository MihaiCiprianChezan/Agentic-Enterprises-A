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
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Literal, Optional, Protocol

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
    at: datetime = field(default_factory=datetime.utcnow)


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


def perform(
    action: ActionDescriptor,
    actor: Any,
    execute: Callable[[ActionDescriptor], str],
    ledger: EffectsLedger,
    governance: GovernanceCheck,
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

    NOTE: This is a SPEC-FAITHFUL SKELETON. The body is the M0 implementation task;
    it is left to Claude Code so the build is owned in the real repo. Raising here keeps
    the contract explicit and the M0 test red until implemented.
    """
    raise NotImplementedError(
        "M0: implement perform() per Build-Spec §4.2. "
        "See tests/test_m0_idempotency.py for the acceptance criteria."
    )


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
