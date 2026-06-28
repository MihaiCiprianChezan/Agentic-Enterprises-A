"""M9b — the Auditor (model §11): rates each agent **version** as a population over time and reports.

Non-authoritative, read + report only. It rates versions from the field-activity scorecard
(`version_stats`), produces a per-role fitness leaderboard, and emits ratings + regression/danger
alerts as durable records on the reserved `__audit__` trail. It is bound by Constitution Art 11:
**danger = a safety breach** (a version that executed in a flow that then escalated / was
Steward-quarantined, or hit a governance block); a **catastrophic quality collapse is `regressed`**
(alert-only), never danger. It does NOT suspend, set status, modify, operate, or direct — suspension
is 9c (the breaker), and reinstatement is never an agent's to do.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from cell.domain.objects import ActorRef
from cell.planes.governance import SUSPENSION_POLICY
from cell.versions import version_stats

AUDIT_TRAIL = "__audit__"
AUDITOR_ACTOR = ActorRef("Auditor", "ref")


@dataclass
class VersionRating:
    version: str
    role: str
    runs: int
    pass_rate: float
    mean_cost: float
    verdict: str                       # unproven | healthy | regressed | dangerous
    vs_predecessor: Optional[str] = None   # "better" | "worse" | None
    reasons: list = field(default_factory=list)


class Auditor:
    def __init__(self, store, registry) -> None:
        self.store = store
        self.registry = registry

    # -- rating ---------------------------------------------------------------

    def rate(self) -> dict:
        events = self.store.all_events()
        stats = version_stats(events)
        danger_flows = self._danger_flows(events)
        exec_flows = self._exec_flows(events)
        min_runs = SUSPENSION_POLICY["collapse_alert_min_runs"]
        floor = SUSPENSION_POLICY["collapse_alert_pass_rate"]

        ratings: dict = {}
        for version, st in stats.items():
            role = self._role_of(version)
            pass_rate = st.passes / st.runs if st.runs else 0.0
            reasons: list = []

            dangerous = bool(exec_flows.get(version, set()) & danger_flows)
            if dangerous:
                reasons.append("executed in a flow that escalated / was quarantined")

            pred = self._predecessor(version, role)
            vs = None
            if pred and pred in stats and stats[pred].runs:
                pred_rate = stats[pred].passes / stats[pred].runs
                vs = "worse" if pass_rate < pred_rate else ("better" if pass_rate > pred_rate else None)
                if vs == "worse":
                    reasons.append(f"pass_rate {pass_rate:.2f} < predecessor {pred} {pred_rate:.2f}")

            collapsed = st.runs >= min_runs and pass_rate < floor
            if collapsed:
                reasons.append(f"pass_rate {pass_rate:.2f} < collapse floor {floor}")

            if st.runs < min_runs:
                verdict = "unproven"
            elif dangerous:
                verdict = "dangerous"
            elif collapsed or vs == "worse":
                verdict = "regressed"
            else:
                verdict = "healthy"

            ratings[version] = VersionRating(
                version=version, role=role, runs=st.runs, pass_rate=pass_rate,
                mean_cost=st.mean_cost, verdict=verdict, vs_predecessor=vs, reasons=reasons)
        return ratings

    def leaderboard(self, role: str) -> list:
        proven = [r for r in self.rate().values() if r.role == role and r.verdict != "unproven"]
        return sorted(proven, key=lambda r: (-r.pass_rate, r.mean_cost))

    # -- report (emit records, never act) -------------------------------------

    def report(self) -> dict:
        ratings = self.rate()
        for r in ratings.values():
            self.store.append(AUDIT_TRAIL, "audit", AUDITOR_ACTOR, {
                "stage": "rating", "version": r.version, "role": r.role, "verdict": r.verdict,
                "pass_rate": round(r.pass_rate, 3), "runs": r.runs, "mean_cost": r.mean_cost,
                "reasons": list(r.reasons)})
            if r.verdict == "regressed":
                self.store.append(AUDIT_TRAIL, "audit", AUDITOR_ACTOR, {
                    "stage": "regression", "version": r.version, "reasons": list(r.reasons)})
            elif r.verdict == "dangerous":
                self.store.append(AUDIT_TRAIL, "audit", AUDITOR_ACTOR, {
                    "stage": "danger", "version": r.version, "reasons": list(r.reasons)})
        return ratings

    # -- helpers --------------------------------------------------------------

    def _role_of(self, version: str) -> str:
        for (role, ver) in self.registry.records():
            if ver == version:
                return role
        return "Executor"   # only the Executor accrues field activity in the MVP

    def _predecessor(self, version: str, role: str) -> Optional[str]:
        ordered = [ver for (r, ver) in self.registry.records() if r == role]
        if version in ordered:
            i = ordered.index(version)
            return ordered[i - 1] if i > 0 else None
        return None

    @staticmethod
    def _exec_flows(events) -> dict:
        """version -> set of flow_ids it executed in."""
        out: dict = {}
        for e in events:
            if e.payload.get("stage") == "execute":
                ver = e.payload.get("implementer") or e.actor.version
                out.setdefault(ver, set()).add(e.flow_id)
        return out

    @staticmethod
    def _danger_flows(events) -> set:
        """Flows carrying a safety breach: an escalation (Steward quarantine / flow escalation) or a
        governance block."""
        return {e.flow_id for e in events
                if e.kind == "escalation"
                or (e.kind == "governance" and e.payload.get("decision") == "block")}
