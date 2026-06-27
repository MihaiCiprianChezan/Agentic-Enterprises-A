"""Governance plane — the compiled constitution (M5, not M0).

Realizes Build-Spec.md §5: the action-class registry and rules R1-R12, evaluated
per action before effect (Constitution Art. 5.3). Stubbed here so the wrapper's
GovernanceCheck dependency has a home; the real rule set is the M5 deliverable.

The action-class registry below mirrors Build-Spec §5.1 and is the one piece worth
seeding now, because the idempotency wrapper already references action_class.
"""

from __future__ import annotations

from typing import Any

from cell.domain.objects import Level

# Build-Spec §5.1 — coarse, governed classification. Each entry traces to Constitution Art. 4.
ACTION_CLASS_REGISTRY: dict[str, Level] = {
    "CLASS_READ": "L3",            # read repo/files/ticket/state
    "CLASS_SANDBOX": "L3",         # run tests/build/lint/dry-run
    "CLASS_OWN_WRITE": "L2",       # write to the cell's own working branch
    "CLASS_VISIBLE_OUTPUT": "L2",  # open/update a pull request
    "CLASS_EXTERNAL_COMM": "L1",   # comment on an externally visible issue
    "CLASS_HIGH_BLAST": "L0",      # push to a shared/protected branch
    "CLASS_PRODUCTION": "L0",      # merge to main / trigger deploy (or out of scope)
    # anything absent -> CLASS_NOVEL, treated as L0 + classification proposal (R3)
}

NOVEL_LEVEL: Level = "L0"


def level_for(action_class: str) -> Level:
    """R3: unknown class -> L0 (fail-safe) and (caller should) emit a classification proposal."""
    return ACTION_CLASS_REGISTRY.get(action_class, NOVEL_LEVEL)


class PermissiveGovernance:
    """M0-only stub: allows everything so the wrapper can be exercised in isolation.
    DO NOT ship. Replaced by the real R1-R12 evaluator at M5 (Build-Spec §5.2-5.3)."""

    def evaluate(self, action: Any, actor: Any) -> tuple[bool, str]:
        return True, "permissive-stub (M0 only)"


# M5 TODO: implement RuleSetGovernance.evaluate() applying R1-R12 in the §5.3 order,
# each block citing its source constitution clause, appending a governance Event (R6/R12).
