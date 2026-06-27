"""The version layer (Build-Spec §2.4) — the M9 Auditor precondition.

Role versions are first-class: a **VersionRegistry** event-sourced on a reserved `__versions__`
flow records each version and its status; **version_stats** scores each version from field activity
(runs, pass/return/block, mean cost). The Optimizer respects status (it never routes to a non-active
version — see handbrake._assign). The Auditor (M9) will rate versions from this signal and set
status; this module supplies the substrate, not the ratings.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

VERSIONS_FLOW = "__versions__"   # reserved flow: the registry lives in the event plane (invariant #5)

VersionStatus = Literal["active", "rolled_back", "suspended"]

# the system actor that writes registry events (a human/Board/Auditor acts through it later)
from cell.domain.objects import ActorRef  # noqa: E402

REGISTRY_ACTOR = ActorRef("Registry", "ref")


@dataclass(frozen=True)
class VersionRecord:
    role: str
    version: str
    status: VersionStatus
    variant_of: Optional[str] = None


class VersionRegistry:
    """Event-sourced registry of role versions and their status, on the reserved `__versions__`
    flow — durable and auditable like any other plane state."""

    def __init__(self, store) -> None:
        self.store = store

    def register(self, role: str, version: str, variant_of: Optional[str] = None) -> None:
        self.store.append(VERSIONS_FLOW, "version", REGISTRY_ACTOR,
                          {"stage": "register", "role": role, "version": version,
                           "variant_of": variant_of, "status": "active"})

    def set_status(self, version: str, status: VersionStatus) -> None:
        self.store.append(VERSIONS_FLOW, "version", REGISTRY_ACTOR,
                          {"stage": "status", "version": version, "status": status})

    def records(self) -> dict[str, VersionRecord]:
        """Current state folded from the `__versions__` events (latest wins)."""
        out: dict[str, VersionRecord] = {}
        for e in self.store.read(VERSIONS_FLOW):
            p, v = e.payload, e.payload.get("version")
            if v is None:
                continue
            if p.get("stage") == "register":
                out[v] = VersionRecord(role=p.get("role", "?"), version=v,
                                       status=p.get("status", "active"), variant_of=p.get("variant_of"))
            elif p.get("stage") == "status":
                prev = out.get(v)
                role = prev.role if prev else "?"
                variant = prev.variant_of if prev else None
                out[v] = VersionRecord(role=role, version=v, status=p["status"], variant_of=variant)
        return out

    def status_of(self, version: str) -> VersionStatus:
        """The folded status; `active` for a version that has run but was never registered (field
        activity is ground truth — the Auditor can register/suspend it later)."""
        rec = self.records().get(version)
        return rec.status if rec is not None else "active"


@dataclass
class VersionStat:
    runs: int = 0
    passes: int = 0
    returns: int = 0
    blocks: int = 0
    mean_cost: float = 0.0


def _version_of(execute_event) -> str:
    p = execute_event.payload
    return p.get("implementer") or execute_event.actor.version


def version_stats(events) -> dict[str, VersionStat]:
    """Per-version scorecard from field activity — the raw signal the Auditor rates. Joins each
    `verdict` to the version that produced its output (the `execute` event's version, by output_id)
    and folds cost."""
    by_output: dict[str, str] = {}            # output_id -> version that produced it
    costs: dict[str, list[float]] = {}        # version -> execute compute samples
    for e in events:
        if e.payload.get("stage") == "execute":
            ver = _version_of(e)
            oid = e.payload.get("output_id")
            if oid is not None:
                by_output[oid] = ver
            if e.cost is not None:
                costs.setdefault(ver, []).append(e.cost.compute)

    stats: dict[str, VersionStat] = {ver: VersionStat() for ver in costs}
    for ver in costs:
        stats[ver].runs = len(costs[ver])
        stats[ver].mean_cost = sum(costs[ver]) / len(costs[ver]) if costs[ver] else 0.0

    for e in events:
        p = e.payload
        if e.kind == "verdict":
            ver = by_output.get(p.get("output_id"))
            if ver is None:
                continue
            st = stats.setdefault(ver, VersionStat())
            if p.get("decision") == "pass":
                st.passes += 1
            elif p.get("decision") == "return":
                st.returns += 1
        elif e.kind == "governance" and p.get("decision") == "block":
            ver = by_output.get(p.get("output_id"))
            if ver is not None:
                stats.setdefault(ver, VersionStat()).blocks += 1
    return stats
