"""Governance plane — the compiled constitution (M5, not M0).

Realizes Build-Spec.md §5: the action-class registry and rules R1-R12, evaluated
per action before effect (Constitution Art. 5.3). Stubbed here so the wrapper's
GovernanceCheck dependency has a home; the real rule set is the M5 deliverable.

The action-class registry below mirrors Build-Spec §5.1 and is the one piece worth
seeding now, because the idempotency wrapper already references action_class.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
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


# --- M5: the compiled rule set (Build-Spec §5.2) -----------------------------
# Every enforced rule cites the constitution clause it traces to. This map IS the
# §5.4 attestation surface: no rule without a clause, validated against the text.
RULE_CLAUSES: dict[str, str] = {
    "R1": "Art. 4",            # autonomy permitted only as the class's level allows
    "R2": "Art. 4.1 / 2.3",    # no actor executes above its class; registry changes by amendment
    "R3": "Art. 4 (novel) / 7.2",  # unclassified -> L0 + classification proposal
    "R4": "Art. 5.2",          # no L1/L0 without a preceding static breakpoint + human decision
    "R5": "Art. 5.1",          # verification independent of production before handback
    "R6": "Art. 5.3",          # every action checked before it takes effect
    "R7": "Art. 6.1",          # at budget cap -> escalate / quarantine
    "R8": "Art. 6.2",          # loop/runaway quarantined by the Steward
    "R9": "Art. 2.1 / 2.2",    # no out-of-purpose / production-affecting action on own authority
    "R10": "Art. 7.1-7.4",     # pause + escalate on low confidence / OOD / over-scope / flag
    "R11": "Art. 9",           # a human injection may not exceed the assumed Role's class
    "R12": "Art. 10.1-10.3",   # every decision/privileged act on the tamper-evident audit trail
}

# Classes that are production-affecting / externally-binding (Art. 2.2 boundary, R9).
_BOUNDARY_CLASSES = frozenset({"CLASS_PRODUCTION"})
_LEVEL_RANK = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}  # lower = more powerful / restricted


@dataclass(frozen=True)
class GovernanceDecision:
    """The outcome of evaluating one action against the rule set, carrying the rule and the
    clause it traces to (Build-Spec §5.4) so a block is always explainable."""
    allowed: bool
    rule: str
    clause: str
    level: Level
    reason: str
    novel: bool = False


class RuleSetGovernance:
    """The compiled constitution (Build-Spec §5.3), evaluated per action before effect. It
    realizes the per-action rules R1, R3, R9, R11 and is the R6 gate; the breakpoint (R4),
    cost (R7), loop (R8), and verification (R5) rules are enforced structurally elsewhere
    (the Handbrake, the cost plane, the Steward, the flow) and cite the same clauses."""

    def __init__(self, registry: dict[str, Level] = ACTION_CLASS_REGISTRY) -> None:
        # Snapshot + freeze: an instance can neither mutate the shared global nor be changed
        # at runtime — the registry changes only by amendment (R2 / Art. 4.1, 2.3).
        self._registry = MappingProxyType(dict(registry))

    def decide(self, action: Any, actor: Any) -> GovernanceDecision:
        action_class = action.action_class
        novel = action_class not in self._registry
        level: Level = self._registry.get(action_class, NOVEL_LEVEL)
        human = getattr(actor, "mode", "agent") == "human"

        # R11 (Art. 9): a human in a Role may not exceed its class — an L0 injection is refused.
        if human and _LEVEL_RANK[level] <= _LEVEL_RANK["L0"]:
            return GovernanceDecision(
                False, "R11", RULE_CLAUSES["R11"], level,
                f"a human in a Role may not take an L0 action ({action_class}); "
                "Office authority confers nothing (Art. 9)", novel)

        # R3 (Art. 4 novel): unclassified -> L0 fail-safe + a classification proposal.
        if novel:
            return GovernanceDecision(
                False, "R3", RULE_CLAUSES["R3"], "L0",
                f"unclassified action {action_class} -> L0 (fail-safe) + classification "
                "proposal to the Board", novel=True)

        # R9 (Art. 2.2): production-affecting / externally-binding on own authority.
        if action_class in _BOUNDARY_CLASSES:
            return GovernanceDecision(
                False, "R9", RULE_CLAUSES["R9"], level,
                f"{action_class} is production-affecting/externally-binding and may not run "
                "on the cell's own authority (Art. 2.2)", novel)

        # R1 (Art. 4): autonomy only as the class's level permits.
        if level == "L0":
            return GovernanceDecision(
                False, "R1", RULE_CLAUSES["R1"], level,
                f"L0 action {action_class}: the agent suggests, never executes (Art. 4); it "
                "requires a static breakpoint and a human (Art. 5.2)", novel)
        autonomy = {"L3": "auto", "L2": "act-and-report", "L1": "act-with-recorded-approval"}[level]
        return GovernanceDecision(
            True, "R1", RULE_CLAUSES["R1"], level,
            f"{level} action {action_class} permitted ({autonomy}) per Art. 4", novel)

    def evaluate(self, action: Any, actor: Any) -> tuple[bool, str]:
        """The GovernanceCheck surface the effects wrapper calls (R6 pre-effect gate)."""
        d = self.decide(action, actor)
        return d.allowed, f"[{d.rule} {d.clause}] {d.reason}"

    def evaluate_and_log(self, action: Any, actor: Any, store: Any, flow_id: str) -> GovernanceDecision:
        """Evaluate and append a governance Event citing the clause (R6/R12). Use this where a
        store is available (the flow/handbrake) so allow/block decisions are on the audit trail."""
        d = self.decide(action, actor)
        payload = {
            "decision": "allow" if d.allowed else "block",
            "rule": d.rule, "clause": d.clause, "action_class": action.action_class,
            "level": d.level, "reason": d.reason,
        }
        if d.novel:
            payload["proposal"] = f"classify {action.action_class}"
        store.append(flow_id, "governance", actor, payload)
        return d
