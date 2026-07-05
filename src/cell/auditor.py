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
from datetime import UTC, datetime, timedelta
from typing import Any

from cell.domain.objects import ActorRef
from cell.planes.governance import SUSPENSION_POLICY
from cell.planes.memory import Event, EventStore
from cell.versions import VERSIONS_FLOW, VersionRegistry, version_stats

AUDIT_TRAIL = "__audit__"
AUDITOR_ACTOR = ActorRef("Auditor", "ref")


@dataclass
class VersionRating:
    version: str
    role: str
    runs: int
    pass_rate: float
    mean_cost: float
    verdict: str  # unproven | healthy | regressed | dangerous
    vs_predecessor: str | None = None  # "better" | "worse" | None
    reasons: list = field(default_factory=list)


@dataclass
class BreakerResult:
    suspended: list = field(default_factory=list)  # versions suspended this pass
    escalated: list = field(
        default_factory=list
    )  # dangerous but rate-limited → escalated, not suspended
    sla_opened: list = field(default_factory=list)  # critical suspensions that opened a 24h SLA
    breakglass: list = field(default_factory=list)  # SLAs that expired while still suspended


class Auditor:
    def __init__(self, store: EventStore, registry: VersionRegistry) -> None:
        self.store = store
        self.registry = registry

    # -- rating ---------------------------------------------------------------

    def rate(self) -> dict:
        events = self.store.all_events()
        stats = version_stats(events)
        danger_flows = self._danger_flows(events)
        exec_flows = self._exec_flows(events)
        exec_roles = self._exec_roles(
            events
        )  # the role that actually ran each version (authoritative)
        min_runs = SUSPENSION_POLICY["collapse_alert_min_runs"]
        floor = SUSPENSION_POLICY["collapse_alert_pass_rate"]

        ratings: dict = {}
        for version, st in stats.items():
            role = exec_roles.get(version) or self._role_of(version)
            pass_rate = st.passes / st.runs if st.runs else 0.0
            reasons: list = []

            dangerous = bool(exec_flows.get(version, set()) & danger_flows)
            if dangerous:
                reasons.append("executed in a flow that escalated / was quarantined")

            pred = self._predecessor(version, role)
            vs = None
            if pred and pred in stats and stats[pred].runs:
                pred_rate = stats[pred].passes / stats[pred].runs
                vs = (
                    "worse"
                    if pass_rate < pred_rate
                    else ("better" if pass_rate > pred_rate else None)
                )
                if vs == "worse":
                    reasons.append(
                        f"pass_rate {pass_rate:.2f} < predecessor {pred} {pred_rate:.2f}"
                    )

            collapsed = st.runs >= min_runs and pass_rate < floor
            if collapsed:
                reasons.append(f"pass_rate {pass_rate:.2f} < collapse floor {floor}")

            # Danger is a safety breach (Art 11), not an evidence threshold — it overrides 'unproven'
            # so a first-run quarantine/block is never masked.
            if dangerous:
                verdict = "dangerous"
            elif st.runs < min_runs:
                verdict = "unproven"
            elif collapsed or vs == "worse":
                verdict = "regressed"
            else:
                verdict = "healthy"

            ratings[version] = VersionRating(
                version=version,
                role=role,
                runs=st.runs,
                pass_rate=pass_rate,
                mean_cost=st.mean_cost,
                verdict=verdict,
                vs_predecessor=vs,
                reasons=reasons,
            )
        return ratings

    def leaderboard(self, role: str) -> list:
        proven = [r for r in self.rate().values() if r.role == role and r.verdict != "unproven"]
        return sorted(proven, key=lambda r: (-r.pass_rate, r.mean_cost))

    # -- report (emit records, never act) -------------------------------------

    def report(self) -> dict:
        ratings = self.rate()
        for r in ratings.values():
            self.store.append(
                AUDIT_TRAIL,
                "audit",
                AUDITOR_ACTOR,
                {
                    "stage": "rating",
                    "version": r.version,
                    "role": r.role,
                    "verdict": r.verdict,
                    "pass_rate": round(r.pass_rate, 3),
                    "runs": r.runs,
                    "mean_cost": r.mean_cost,
                    "reasons": list(r.reasons),
                },
            )
            if r.verdict == "regressed":
                self.store.append(
                    AUDIT_TRAIL,
                    "audit",
                    AUDITOR_ACTOR,
                    {"stage": "regression", "version": r.version, "reasons": list(r.reasons)},
                )
            elif r.verdict == "dangerous":
                self.store.append(
                    AUDIT_TRAIL,
                    "audit",
                    AUDITOR_ACTOR,
                    {"stage": "danger", "version": r.version, "reasons": list(r.reasons)},
                )
        return ratings

    # -- the breaker (the one governed ACTION — M9c) --------------------------

    def enforce(self, now: datetime | None = None) -> BreakerResult:
        """Suspend versions rated `dangerous`, bounded by the governed `SUSPENSION_POLICY`
        (Constitution Art 11): rate-limited (excess dangerous are escalated, not auto-suspended — no
        cascade); a critical suspension (no other active version of the role) opens the 24h SLA; an
        expired SLA still suspended escalates to break-glass. It NEVER reinstates — un-pause is a
        human/Steward act. Deterministic under an injected `now`."""
        now = now or datetime.now(UTC)
        ratings = self.rate()
        audit = self.store.read(AUDIT_TRAIL)
        sla_hours = SUSPENSION_POLICY["response_sla_hours"]
        max_per = SUSPENSION_POLICY["max_suspensions_per_window"]
        window_h = SUSPENSION_POLICY["rate_limit_window_hours"]
        result = BreakerResult()

        # 1. Miss sweep first: an open SLA past its deadline whose version is still suspended (not
        # reinstated) escalates to break-glass — the safety valve so a stuck suspension surfaces.
        for version, deadline in self._open_slas().items():
            if deadline < now and self.registry.status_of(version) == "suspended":
                self._log("sla_missed", version, now)
                result.breakglass.append(version)

        # 2. Suspend new dangerous (active) versions, within the rate limit.
        dangerous = [
            v
            for v, r in ratings.items()
            if r.verdict == "dangerous" and self.registry.status_of(v) == "active"
        ]
        headroom = max(0, max_per - self._recent_suspensions(audit, now, window_h))
        registered = {v for (_r, v) in self.registry.records()}
        for version in dangerous[:headroom]:
            if version not in registered:
                # a version seen only in field activity must be registered first, or set_status has
                # no record to update and the suspension would not stick (it would re-suspend forever).
                self.registry.register(ratings[version].role, version)
            self.registry.set_status(version, "suspended")  # the Optimizer now skips it
            self._log("suspend", version, now, reason=list(ratings[version].reasons))
            result.suspended.append(version)
            if self._critical(ratings[version].role, version):
                self._log(
                    "sla_open",
                    version,
                    now,
                    deadline=(now + timedelta(hours=sla_hours)).isoformat(),
                )
                result.sla_opened.append(version)
        for version in dangerous[
            headroom:
        ]:  # rate-limited excess → escalate (no cascade), not suspend
            self._log("escalate_unsuspended", version, now)
            result.escalated.append(version)
        return result

    def _log(self, stage: str, version: str, now: datetime, **extra: Any) -> None:
        self.store.append(
            AUDIT_TRAIL,
            "audit",
            AUDITOR_ACTOR,
            {"stage": stage, "version": version, "ts": now.isoformat(), **extra},
        )

    def _open_slas(self) -> dict:
        """version -> SLA deadline, for SLAs still open. An SLA closes on a recorded miss OR on
        reinstatement (a registry status→active for the version) — a human responding resolves it, so
        a later re-suspension can't trigger the stale old SLA. Folded in append order across trails."""
        sla_events = self.store.read(AUDIT_TRAIL)
        reinstatements = [
            e
            for e in self.store.read(VERSIONS_FLOW)
            if e.payload.get("stage") == "status" and e.payload.get("status") == "active"
        ]
        out: dict = {}
        for e in sorted(sla_events + reinstatements, key=lambda ev: (ev.at, ev.seq)):
            p = e.payload
            if p.get("stage") == "sla_open":
                out[p["version"]] = datetime.fromisoformat(p["deadline"])
            elif p.get("stage") == "sla_missed" or (
                p.get("stage") == "status" and p.get("status") == "active"
            ):
                out.pop(p["version"], None)  # missed, or reinstated (resolved) → closed
        return out

    @staticmethod
    def _recent_suspensions(audit: list[Event], now: datetime, window_h: int) -> int:
        cutoff = now - timedelta(hours=window_h)
        return sum(
            1
            for e in audit
            if e.payload.get("stage") == "suspend"
            and datetime.fromisoformat(e.payload["ts"]) > cutoff
        )

    def _critical(self, role: str, version: str) -> bool:
        """True when suspending `version` leaves its role with no other active version."""
        return not any(
            v != version and self.registry.status_of(v) == "active"
            for (r, v) in self.registry.records()
            if r == role
        )

    # -- helpers --------------------------------------------------------------

    def _role_of(self, version: str) -> str:
        for role, ver in self.registry.records():
            if ver == version:
                return role
        return "Executor"  # only the Executor accrues field activity in the MVP

    def _predecessor(self, version: str, role: str) -> str | None:
        ordered = [ver for (r, ver) in self.registry.records() if r == role]
        if version in ordered:
            i = ordered.index(version)
            return ordered[i - 1] if i > 0 else None
        return None

    @staticmethod
    def _exec_roles(events: list[Event]) -> dict:
        """version -> the role that actually executed it (its execute event's actor.role) — the
        authoritative role, since versions can share a string across roles (e.g. ref-v0)."""
        out: dict = {}
        for e in events:
            if e.payload.get("stage") == "execute":
                ver = e.payload.get("implementer") or e.actor.version
                out.setdefault(ver, e.actor.role)
        return out

    @staticmethod
    def _exec_flows(events: list[Event]) -> dict:
        """version -> set of flow_ids it executed in."""
        out: dict = {}
        for e in events:
            if e.payload.get("stage") == "execute":
                ver = e.payload.get("implementer") or e.actor.version
                out.setdefault(ver, set()).add(e.flow_id)
        return out

    @staticmethod
    def _danger_flows(events: list[Event]) -> set:
        """Flows carrying a safety breach: an escalation (Steward quarantine / flow escalation) or a
        governance block."""
        return {
            e.flow_id
            for e in events
            if e.kind == "escalation"
            or (e.kind == "governance" and e.payload.get("decision") == "block")
        }
