"""The version layer (Build-Spec §2.4) — the M9 Auditor precondition.

Role versions are first-class: a **VersionRegistry** event-sourced on a reserved `__versions__`
flow records each version and its status; **version_stats** scores each version from field activity
(runs, pass/return/block, mean cost). The Optimizer respects status (it never routes to a non-active
version — see handbrake._assign). The Auditor (M9) will rate versions from this signal and set
status; this module supplies the substrate, not the ratings.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

VERSIONS_FLOW = (
    "__versions__"  # reserved flow: the registry lives in the event plane (invariant #5)
)

VersionStatus = Literal["active", "rolled_back", "suspended"]

# the system actor that writes registry events (a human/Board/Auditor acts through it later)
from cell.domain.objects import ActorRef  # noqa: E402

REGISTRY_ACTOR = ActorRef("Registry", "ref")


@dataclass(frozen=True)
class VersionRecord:
    role: str
    version: str
    status: VersionStatus
    variant_of: str | None = None


class VersionRegistry:
    """Event-sourced registry of role versions and their status, on the reserved `__versions__`
    flow — durable and auditable like any other plane state."""

    def __init__(self, store) -> None:
        self.store = store

    def register(self, role: str, version: str, variant_of: str | None = None) -> None:
        self.store.append(
            VERSIONS_FLOW,
            "version",
            REGISTRY_ACTOR,
            {
                "stage": "register",
                "role": role,
                "version": version,
                "variant_of": variant_of,
                "status": "active",
            },
        )

    def set_status(self, version: str, status: VersionStatus) -> None:
        self.store.append(
            VERSIONS_FLOW,
            "version",
            REGISTRY_ACTOR,
            {"stage": "status", "version": version, "status": status},
        )

    def records(self) -> dict:
        """Current state folded from the `__versions__` events (latest wins). Keyed by
        `(role, version)` — distinct roles may share a version string (e.g. the reference roles all
        use `ref-v0`) and must not collapse."""
        out: dict = {}
        for e in self.store.read(VERSIONS_FLOW):
            p, v = e.payload, e.payload.get("version")
            if v is None:
                continue
            if p.get("stage") == "register":
                key = (p.get("role", "?"), v)
                out[key] = VersionRecord(
                    role=key[0],
                    version=v,
                    status=p.get("status", "active"),
                    variant_of=p.get("variant_of"),
                )
            elif p.get("stage") == "status":  # applies to every record sharing this version
                for key, rec in list(out.items()):
                    if rec.version == v:
                        out[key] = replace(rec, status=p["status"])
        return out

    def status_of(self, version: str) -> VersionStatus:
        """The folded status of a version; `active` for one that has run but was never registered
        (field activity is ground truth — the Auditor can register/suspend it later). Routable
        implementer versions are unique, so a version lookup is unambiguous there."""
        for rec in self.records().values():
            if rec.version == version:
                return rec.status
        return "active"


@dataclass
class VersionStat:
    runs: int = 0
    passes: int = 0
    returns: int = 0
    mean_cost: float = (
        0.0  # mean execute `compute` over the runs that reported cost (0 if none did)
    )


def _version_of(execute_event) -> str:
    p = execute_event.payload
    return p.get("implementer") or execute_event.actor.version


def version_stats(events) -> dict[str, VersionStat]:
    """Per-version scorecard from field activity — the raw signal the Auditor rates. Counts each
    `execute` as a run for its version, joins each `verdict` to the version that produced its output,
    and folds the execute `compute` cost. (No per-version block count: a gate block prevents the
    version from running, so it cannot be attributed to one.)"""
    by_output: dict[str, str] = {}  # output_id -> version that produced it
    costs: dict[str, list[float]] = {}  # version -> execute compute samples (cost-bearing runs)
    stats: dict[str, VersionStat] = {}
    for e in events:
        if e.payload.get("stage") == "execute":
            ver = _version_of(e)
            stats.setdefault(ver, VersionStat()).runs += 1  # every execute is a run, cost or not
            oid = e.payload.get("output_id")
            if oid is not None:
                by_output[oid] = ver
            if e.cost is not None:
                costs.setdefault(ver, []).append(e.cost.compute)

    for ver, samples in costs.items():
        stats[ver].mean_cost = sum(samples) / len(samples)

    for e in events:
        if e.kind == "verdict":
            ver = by_output.get(e.payload.get("output_id"))
            if ver is None:
                continue
            if e.payload.get("decision") == "pass":
                stats[ver].passes += 1
            elif e.payload.get("decision") == "return":
                stats[ver].returns += 1
    return stats
