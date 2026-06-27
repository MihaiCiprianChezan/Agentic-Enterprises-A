"""Read-only observability inspector for a finished run.

`python -m cell.observe <state_db> [flow_id] [--full]` reads a run's durable event plane and
prints its trajectory (timeline + verdict summary), so a manual/live run can be inspected after
the fact to confirm the cell behaved as expected. Post-hoc only — the event plane is durable, so
nothing is lost by reading after the process exits.

It is a pure interpretation layer over existing read APIs (`DurableEventStore.read`,
`compute_hash`, `total_cost`, the effects ledger). It changes no cell/plane/governance code, and
reads the durable event plane — NOT the in-memory trace store, which does not survive the process.
"""
from __future__ import annotations

import json
import os
import pathlib
import sqlite3
import sys
from dataclasses import dataclass
from typing import Callable, Optional

from cell.planes.memory import CostDelta, DurableEventStore, Event, compute_hash
from cell.planes.observability import total_cost


@dataclass
class EffectView:
    """One performed external effect, as seen from the event plane."""
    label: str
    effect_kind: str
    result: Optional[str]
    once_confirmed: Optional[bool]   # None when no ledger was consulted


@dataclass
class RunSummary:
    flow_id: str
    verdict: str                     # PASS | RETURN | BLOCKED | PAUSED | UNKNOWN
    execute_attempts: int
    rederivations: int               # specify→decompose→govern rounds (count of specify decisions)
    gov_allow: int
    gov_block: int
    effects: list
    total_cost: CostDelta
    window: tuple
    chain_intact: bool
    chain_broken_at: Optional[int]
    actors: list
    event_count: int


# -- chain integrity ----------------------------------------------------------

def verify_chain(events) -> tuple:
    """Recompute every link with the store's own hash function — a true tamper-evidence check.
    Returns (intact, first_broken_seq)."""
    prev = "GENESIS"
    for ev in events:
        if ev.prev_hash != prev or ev.hash != compute_hash(prev, ev.payload):
            return (False, ev.seq)
        prev = ev.hash
    return (True, None)


# -- interpretation -----------------------------------------------------------

def _is_execute(ev: Event) -> bool:
    return ev.kind == "action" and "artifact_ref" in ev.payload


def _is_effect(ev: Event) -> bool:
    return ev.kind == "action" and "effect_kind" in ev.payload


def _verdict(events) -> str:
    verdicts = [e for e in events if e.kind == "verdict"]
    if verdicts:
        d = str(verdicts[-1].payload.get("decision", "")).lower()
        return {"pass": "PASS", "return": "RETURN"}.get(d, d.upper() or "UNKNOWN")
    if any(e.kind == "governance" and e.payload.get("decision") == "block" for e in events):
        return "BLOCKED"
    if events and events[-1].kind == "breakpoint":
        return "PAUSED"
    return "UNKNOWN"


def _actors(events) -> list:
    seen = []
    for e in events:
        label = e.actor.role if e.actor.version == "ref" else f"{e.actor.role}({e.actor.version})"
        if label not in seen:
            seen.append(label)
    return seen


def summarize(events, confirm_once: Optional[Callable[[str], Optional[bool]]] = None) -> RunSummary:
    """Derive the at-a-glance run summary from the durable events. `confirm_once`, if given, maps an
    effect's idempotency key to its exactly-once status (True/False), or None if unknown."""
    flow_id = events[0].flow_id if events else ""
    gov = [e for e in events if e.kind == "governance"]
    effects = []
    for e in events:
        if _is_effect(e):
            key = e.payload.get("idempotency_key")
            once = confirm_once(key) if (confirm_once is not None and key is not None) else None
            effects.append(EffectView(
                label=e.payload.get("action_class") or e.payload.get("action_id") or "effect",
                effect_kind=e.payload.get("effect_kind", ""),
                result=e.payload.get("result_digest"),
                once_confirmed=once))
    chain_ok, broken_at = verify_chain(events)
    return RunSummary(
        flow_id=flow_id,
        verdict=_verdict(events),
        execute_attempts=sum(1 for e in events if _is_execute(e)),
        rederivations=sum(1 for e in events
                          if e.kind == "decision" and e.payload.get("stage") == "specify"),
        gov_allow=sum(1 for e in gov if e.payload.get("decision") == "allow"),
        gov_block=sum(1 for e in gov if e.payload.get("decision") == "block"),
        effects=effects,
        total_cost=total_cost(events),
        window=(events[0].at, events[-1].at) if events else (None, None),
        chain_intact=chain_ok,
        chain_broken_at=broken_at,
        actors=_actors(events),
        event_count=len(events),
    )


def key_fact(ev: Event) -> str:
    """A one-line, kind-specific summary of an event's payload."""
    p, k = ev.payload, ev.kind
    if k == "decision":
        stage = p.get("stage")
        if stage == "specify":
            tail = " (in_purpose)" if p.get("in_purpose") else ""
            return f"specify · goal {p.get('goal_id', '?')}{tail}"
        if stage == "decompose":
            wi = p.get("work_items")
            n = len(wi) if isinstance(wi, list) else (wi or 0)
            return f"decompose · {n} work item" + ("" if n == 1 else "s")
        if stage == "route":
            return f"route → {p.get('chosen', '?')} (floor {p.get('floor')})"
        return stage or "decision"
    if k == "governance":
        lvl = p.get("authority_level", p.get("level"))  # handbrake gate vs RuleSetGovernance
        lvl_s = f"{lvl}" if str(lvl).upper().startswith("L") else f"L{lvl}"  # "L2" or int 2 → "L2"
        out = f"{str(p.get('decision', '')).upper()} {lvl_s} {p.get('action_class', '')}".strip()
        if p.get("decision") == "block" and p.get("reason"):
            out += f" · {p['reason']}"
        return out
    if k == "action":
        if _is_execute(ev):
            return f"execute → {p['artifact_ref']}"
        if _is_effect(ev):
            label = p.get("action_class") or p.get("action_id") or "effect"
            out = f"perform {label} [{p.get('effect_kind', '')}]"
            key = p.get("idempotency_key", "")
            if key:
                out += f" key=…{key[-6:]}"
            if p.get("result_digest"):
                out += f" → {p['result_digest']}"
            return out
        return p.get("stage", "action")
    if k == "verdict":
        d = str(p.get("decision", "")).upper()
        if d == "RETURN" and p.get("reason"):
            return f"RETURN · {p['reason']}"
        return d or "verdict"
    if k == "version":
        if p.get("stage") == "register":
            return f"register {p.get('role', '?')} {p.get('version', '?')} ({p.get('status', 'active')})"
        if p.get("stage") == "status":
            return f"status {p.get('version', '?')} → {p.get('status', '?')}"
        return p.get("stage", "version")
    return f"{k} · {','.join(list(p.keys())[:3])}"


# -- formatting ---------------------------------------------------------------

def _fmt_cost(c: CostDelta) -> str:
    out = f"{c.compute:.0f} {c.units}, {c.wall_clock_ms}ms wall"
    if c.human_time_ms is not None:
        out += f", {c.human_time_ms}ms human"
    return out


def format_header(s: RunSummary, db: str) -> str:
    w0, w1 = s.window
    window = "—"
    if w0 and w1:
        window = f"{w0.strftime('%H:%M:%S')} → {w1.strftime('%H:%M:%S')} ({(w1 - w0).total_seconds():.0f}s)"
    chain = "✓ intact" if s.chain_intact else f"✗ BROKEN at seq {s.chain_broken_at}"
    return (f"flow: {s.flow_id}     db: {db}\n"
            f"actors: {' · '.join(s.actors)}\n"
            f"events: {s.event_count}     window: {window}     chain: {chain}")


def format_timeline(events) -> str:
    if not events:
        return "(no events)"
    t0 = events[0].at
    lines = ["  seq  kind         actor          key fact"]
    for e in events:
        dt = (e.at - t0).total_seconds()
        lines.append(f"  {e.seq:3d}  {e.kind:11s}  {e.actor.role:13s}  {key_fact(e)}   +{dt:.1f}s")
    return "\n".join(lines)


def format_summary(s: RunSummary) -> str:
    lines = [
        f"VERDICT: {s.verdict}",
        f"execute attempts: {s.execute_attempts}   ·   re-derivations: {s.rederivations} "
        f"(specify→decompose→govern)",
        f"governance: {s.gov_allow} allow · {s.gov_block} block",
    ]
    if s.effects:
        for ef in s.effects:
            once = ""
            if ef.once_confirmed is True:
                once = "  (exactly-once ✓)"
            elif ef.once_confirmed is False:
                once = "  (not confirmed in ledger)"
            res = f" → {ef.result}" if ef.result else ""
            lines.append(f"effects: {ef.effect_kind} {ef.label}{res}{once}")
    else:
        lines.append("effects: none")
    lines.append(f"total cost: {_fmt_cost(s.total_cost)}")
    lines.append("chain: " + ("✓ intact (tamper-evident)"
                              if s.chain_intact else f"✗ BROKEN at seq {s.chain_broken_at}"))
    return "\n".join(lines)


# -- CLI ----------------------------------------------------------------------

def _connect_ro(db: str) -> sqlite3.Connection:
    """Open the state DB strictly read-only — a tamper-evidence inspector must never write to (or
    even create schema in) the file it is auditing. Raises sqlite3.Error if it cannot open."""
    uri = pathlib.Path(db).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _read_events(conn: sqlite3.Connection, flow_id: str) -> list:
    rows = conn.execute(
        "SELECT * FROM events WHERE flow_id = ? ORDER BY seq", (flow_id,)).fetchall()
    return [DurableEventStore._row_to_event(r) for r in rows]


def _list_flows(conn: sqlite3.Connection) -> list:
    rows = conn.execute("SELECT DISTINCT flow_id FROM events ORDER BY flow_id").fetchall()
    return [r[0] for r in rows]


def _effect_confirmed(conn: sqlite3.Connection, key: str) -> Optional[bool]:
    try:
        row = conn.execute(
            "SELECT status FROM effects WHERE idempotency_key = ?", (key,)).fetchone()
    except sqlite3.Error:
        return None   # no effects ledger in this DB — degrade gracefully
    return None if row is None else (row["status"] == "completed")


def main(argv=None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # keep ✓/→ safe on a Windows console
        except Exception:
            pass
    full = "--full" in raw
    args = [a for a in raw if a != "--full"]
    if not args:
        print("usage: python -m cell.observe <state_db> [flow_id] [--full]", file=sys.stderr)
        return 2
    db = args[0]
    if not os.path.exists(db):
        print(f"state DB not found: {db}", file=sys.stderr)
        return 2
    try:
        conn = _connect_ro(db)
    except sqlite3.Error as exc:
        print(f"cannot open state DB read-only: {db} ({exc})", file=sys.stderr)
        return 2
    try:
        try:
            if len(args) < 2:
                flows = _list_flows(conn)
                if not flows:
                    print(f"no flows found in {db}")
                    return 0
                print(f"flows in {db}:")
                for f in flows:
                    print(f"  {f}")
                return 0
            flow_id = args[1]
            events = _read_events(conn, flow_id)
        except sqlite3.Error as exc:
            print(f"not a readable cell state DB: {db} ({exc})", file=sys.stderr)
            return 2

        if not events:
            print(f"no events for flow '{flow_id}'", file=sys.stderr)
            flows = _list_flows(conn)
            if flows:
                print("available flows: " + ", ".join(flows), file=sys.stderr)
            return 2

        s = summarize(events, lambda key: _effect_confirmed(conn, key))
        print(format_header(s, os.path.basename(db)))
        print()
        print(format_timeline(events))
        print()
        print(format_summary(s))
        if full:
            print("\n--- full payloads ---")
            for e in events:
                print(f"#{e.seq} {e.kind}: "
                      + json.dumps(e.payload, indent=2, sort_keys=True, default=str))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
