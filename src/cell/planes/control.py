"""Control plane — the Handbrake (M4, not M0).

Realizes Handbrake-Interface.md: the five primitives as operations. Stubbed here to
fix the seam; the operations and guarantees are the M4 deliverable. The surface form
(CLI / web / inbox) is deliberately undecided (Handbrake §6); this interface is fixed.
"""

from __future__ import annotations

from typing import Any, Protocol


class Handbrake(Protocol):
    """The five primitives (Handbrake §1). Present on EVERY flow (invariant #3)."""

    def set_breakpoint(
        self, flow_id: str, step: str, kind: str, condition: str | None = None
    ) -> str: ...
    def inspect(self, flow_id: str) -> dict[str, Any]:
        """Returns a takeover BRIEFING (Handbrake §2), not raw state: where/why it paused,
        the pending action + authority class, recent decision trail (with rationale),
        cost so far, and the menu of valid moves pre-checked against the assumed Role."""
        ...

    def inject(self, flow_id: str, value: dict[str, Any], actor: Any) -> None:
        """Record a correction. R11: checked against the assumed Role's authority; an
        out-of-policy injection is refused and logged (Constitution Art. 9)."""
        ...

    def resume(self, flow_id: str) -> None:
        """Continue from the exact paused step, consuming any injection. Exactly-once /
        at-most-once via the effects wrapper (Build-Spec §4) — never restarts from the top."""
        ...

    def replay(self, flow_id: str, to_step: str | None = None) -> list[dict[str, Any]]:
        """Reconstruct a past run step by step WITHOUT re-performing side effects."""
        ...
