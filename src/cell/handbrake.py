"""The Handbrake — control plane (M4).

Realizes Handbrake-Interface.md: the five primitives (breakpoint, inspect, inject, resume,
replay) on the one flow. The handbrake is *structural*, not a feature (invariant #3): the
flow checkpoints durably at a static breakpoint before any L1/L0 action (Constitution
Art. 5.2), hands control to a human, and `resume` continues from the exact step — consuming
any injection, never re-deciding, never restarting from the top.

It composes the earlier milestones: the durable checkpoint/event plane (M0), the role
contracts and flow (M2), the trace/cost plane (M3), and the idempotent-action wrapper (M0)
so resume is exactly-once on the external effect.

Resumability without a durable-execution engine: the checkpoint stores the Ticket and the
position, and resume rebuilds the deterministic prefix (specify → decompose) from the plane,
then continues. State lives outside the actor (invariant #5). A production cell with
non-deterministic role agents would persist the produced Goal/WorkItems into the plane rather
than recompute them; the seam is identical.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Union

from cell.domain.objects import ActorRef, BudgetCap, Output, Ticket, Verdict, WorkItem
from cell.effects.wrapper import (
    ActionDescriptor,
    EffectsLedger,
    GovernanceCheck,
    InMemoryEffectsLedger,
    make_idempotency_key,
    perform,
)
from cell.flow import NonIndependentVerification, _actor_of
from cell.planes.governance import PermissiveGovernance, level_for
from cell.planes.memory import Checkpoint, CostDelta, EventStore
from cell.planes.observability import TraceStore, Tracer, total_cost
from cell.roles.contracts import Director, Executor, Orchestrator, Verifier

_RANK = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}  # lower = more powerful / more restricted


@dataclass
class Paused:
    """Returned by start/resume when the flow hit a breakpoint and checkpointed."""
    flow_id: str
    step: str
    reason: str
    pending_action: dict[str, Any] = field(default_factory=dict)


@dataclass
class Briefing:
    """The takeover briefing `inspect` returns (Handbrake §2) — legible reasoning, not a
    raw state dump."""
    flow_id: str
    role: str
    step: str
    why: str
    pending_action: dict[str, Any]
    authority_level: str
    recent_decisions: list[dict[str, Any]]
    cost: CostDelta
    budget_cap: Optional[BudgetCap]
    valid_moves: list[str]


class InjectionRefused(Exception):
    """An injection the assumed Role is not authorized to make (Constitution Art. 9 / R11)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ticket_to_dict(t: Ticket) -> dict[str, Any]:
    return {"id": t.id, "source": t.source, "title": t.title, "body": t.body,
            "received_at": t.received_at.isoformat(), "raw_refs": list(t.raw_refs)}


def _ticket_from_dict(d: dict[str, Any]) -> Ticket:
    return Ticket(id=d["id"], source=d["source"], title=d["title"], body=d["body"],
                  received_at=datetime.fromisoformat(d["received_at"]),
                  raw_refs=list(d.get("raw_refs", [])))


_CONTROL = ActorRef(role="Handbrake", version="control")  # attribution for ad-hoc breakpoints


class CellHandbrake:
    """Concrete Handbrake over the one flow. Implements the five control primitives
    (Handbrake §1) — including the ad-hoc breakpoint operations of the control.Handbrake
    Protocol — plus `start` to open a flow. `inspect`/`resume` intentionally return richer,
    typed results (`Briefing`, `Verdict | Paused`) than the placeholder Protocol's loose
    `dict` / `None`, so callers get legible structures rather than untyped maps."""

    def __init__(self, *, director: Director, orchestrator: Orchestrator,
                 executor: Executor, verifier: Verifier, store: EventStore,
                 ledger: Optional[EffectsLedger] = None,
                 governance: Optional[GovernanceCheck] = None,
                 recorder: Optional[TraceStore] = None, cost_model=None,
                 max_revisions: int = 2) -> None:
        self.director = director
        self.orchestrator = orchestrator
        self.executor = executor
        self.verifier = verifier
        self.store = store
        self.ledger = ledger or InMemoryEffectsLedger()
        self.governance = governance or PermissiveGovernance()
        self.recorder = recorder
        self.cost_model = cost_model
        self.max_revisions = max_revisions

    # -- primitives -----------------------------------------------------------

    def set_breakpoint(self, flow_id: str, step: str, kind: str = "static",
                       condition: Optional[str] = None) -> str:
        """Declare an ad-hoc breakpoint (Handbrake §1.1) — a human may add one to any flow
        at any time. A breakpoint whose `step` matches an item's pre-execute point pauses it
        even if its authority class would not (static breakpoints already cover L1/L0)."""
        existing = [e for e in self.store.read(flow_id)
                    if e.payload.get("stage") == "set_breakpoint"]
        bp_id = f"bp-{len(existing) + 1}"
        self.store.append(flow_id, "breakpoint", _CONTROL,
                          {"stage": "set_breakpoint", "bp_id": bp_id, "step": step,
                           "kind": kind, "condition": condition})
        return bp_id

    def list_breakpoints(self, flow_id: str) -> list[dict[str, Any]]:
        active: dict[str, dict[str, Any]] = {}
        for e in self.store.read(flow_id):
            p = e.payload
            if p.get("stage") == "set_breakpoint":
                active[p["bp_id"]] = {"id": p["bp_id"], "step": p["step"], "kind": p["kind"]}
            elif p.get("stage") == "clear_breakpoint":
                active.pop(p["bp_id"], None)
        return list(active.values())

    def clear_breakpoint(self, flow_id: str, bp_id: str) -> None:
        self.store.append(flow_id, "breakpoint", _CONTROL,
                          {"stage": "clear_breakpoint", "bp_id": bp_id})

    def start(self, ticket: Ticket, flow_id: str) -> Union[Verdict, Paused]:
        tracer = self._tracer(flow_id)
        with tracer.span("specify", _actor_of(self.director, "Director"), "decision"):
            goal = self.director.specify(ticket)
        self.store.append(flow_id, "decision", goal.created_by,
                          {"stage": "specify", "goal_id": goal.id, "in_purpose": goal.in_purpose},
                          cost=self._ecost("specify"))
        orch = _actor_of(self.orchestrator, "Orchestrator")
        with tracer.span("decompose", orch, "decision"):
            items = self.orchestrator.decompose(goal)
        self.store.append(flow_id, "decision", orch,
                          {"stage": "decompose", "work_items": [i.id for i in items]},
                          cost=self._ecost("decompose"))
        return self._advance(flow_id, ticket, goal, items, 0)

    def inspect(self, flow_id: str) -> Briefing:
        cp = self._require_checkpoint(flow_id)
        ticket = _ticket_from_dict(cp.state_snapshot["ticket"])
        index = cp.state_snapshot["index"]
        goal = self.director.specify(ticket)
        item = self.orchestrator.decompose(goal)[index]
        events = self.store.read(flow_id)
        recent = [{"step": e.payload.get("stage"), "detail": e.payload}
                  for e in events if e.kind == "decision"]
        return Briefing(
            flow_id=flow_id, role=item.assigned_to.role, step=cp.step,
            why=cp.pending_action.get("reason", "static breakpoint"),
            pending_action=cp.pending_action, authority_level=item.authority_level,
            recent_decisions=recent, cost=total_cost(events), budget_cap=goal.budget_cap,
            valid_moves=self._moves(item.authority_level),
        )

    def inject(self, flow_id: str, value: dict[str, Any], actor: ActorRef) -> None:
        cp = self._require_checkpoint(flow_id)
        seat_level = cp.pending_action.get("authority_level", "L0")
        # R11 (Art. 9): an injection may not exceed the assumed Role's class.
        action_class = value.get("action_class")
        if action_class is not None:
            injected_level = level_for(action_class)
            if _RANK.get(injected_level, 0) < _RANK.get(seat_level, 3):
                self.store.append(flow_id, "governance", actor,
                                  {"decision": "block", "rule": "R11", "clause": "Art.9",
                                   "reason": f"injected {action_class} ({injected_level}) exceeds "
                                             f"seat {seat_level}"})
                raise InjectionRefused(
                    f"{action_class} ({injected_level}) exceeds the assumed Role's seat ({seat_level})"
                )
        # Recorded as a tracked variant of the run (model §5), scoped to the paused work
        # item so a later pause never consumes a stale injection. `stage`/`work_item_id`
        # are set last so a crafted payload cannot override them.
        self.store.append(flow_id, "injection", actor,
                          {**value, "stage": "inject",
                           "work_item_id": cp.pending_action.get("work_item_id")})

    def resume(self, flow_id: str) -> Union[Verdict, Paused]:
        cp = self._require_checkpoint(flow_id)
        ticket = _ticket_from_dict(cp.state_snapshot["ticket"])
        index = cp.state_snapshot["index"]
        goal = self.director.specify(ticket)
        items = self.orchestrator.decompose(goal)
        self.store.append(flow_id, "decision", _actor_of(self.orchestrator, "Orchestrator"),
                          {"stage": "resume", "index": index})
        item = items[index]
        verdict = self._do_item(flow_id, item, goal, self._latest_injection(flow_id, item.id))
        if verdict.decision != "pass" or index + 1 >= len(items):
            return verdict
        return self._advance(flow_id, ticket, goal, items, index + 1)

    def replay(self, flow_id: str, to_step: Optional[str] = None) -> list[dict[str, Any]]:
        # Read-only reconstruction from the durable trail; never re-performs effects.
        steps = []
        for e in self.store.read(flow_id):
            stage = e.payload.get("stage")
            if stage is None:
                continue
            steps.append({"seq": e.seq, "stage": stage, "actor": e.actor.role, "payload": e.payload})
            if to_step is not None and stage == to_step:
                break
        return steps

    # -- internals ------------------------------------------------------------

    def _advance(self, flow_id, ticket, goal, items, index) -> Union[Verdict, Paused]:
        verdict: Optional[Verdict] = None
        while index < len(items):
            item = items[index]
            if item.authority_level in ("L0", "L1") or self._adhoc_hit(flow_id, item):
                return self._pause(flow_id, ticket, index, item)
            verdict = self._do_item(flow_id, item, goal, None)
            if verdict.decision != "pass":
                return verdict
            index += 1
        assert verdict is not None  # an empty item list never reaches here (flow.py guards it)
        return verdict

    def _pause(self, flow_id, ticket, index, item) -> Paused:
        reason = f"static breakpoint before {item.authority_level} action (Art. 5.2)"
        pending = {"kind": "execute", "work_item_id": item.id, "action_class": item.action_class,
                   "authority_level": item.authority_level, "reason": reason}
        bp_event = self.store.append(flow_id, "breakpoint", item.assigned_to,
                                     {"stage": "breakpoint", "work_item_id": item.id, "reason": reason})
        self.store.checkpoint(Checkpoint(
            flow_id=flow_id, at_seq=bp_event.seq,
            step=f"pre-execute:{item.id}",
            state_snapshot={"ticket": _ticket_to_dict(ticket), "index": index},
            created_at=_now(), pending_action=pending,
        ))
        return Paused(flow_id=flow_id, step=f"pre-execute:{item.id}", reason=reason,
                      pending_action=pending)

    def _do_item(self, flow_id, item, goal, injection) -> Verdict:
        existing = self._existing_verdict(flow_id, item)
        if existing is not None:
            return existing  # idempotent resume: already executed, do not re-run

        tracer = self._tracer(flow_id)
        if injection is not None and injection["value"].get("type") == "edited_output":
            v = injection["value"]
            output = Output(id=v["output_id"], work_item_id=item.id,
                            artifact_ref=v["artifact_ref"], produced_by=injection["actor"],
                            trace_ref="trace://injected", produced_at=_now())
        else:
            with tracer.span("execute", _actor_of(self.executor, "Executor"), "tool_call"):
                output = self.executor.execute(item)

        # The external L1/L2 action goes through the idempotency wrapper — exactly-once on
        # resume, never re-fired after completion (invariant #4 / M0).
        key = make_idempotency_key(flow_id, f"execute:{item.id}", {"output_id": output.id})
        action = ActionDescriptor(id=f"act-{item.id}", action_class=item.action_class,
                                  effect_kind="compensable", idempotency_key=key,
                                  intent={"output_id": output.id})
        perform(action, _actor_of(self.executor, "Executor"),
                lambda _a: output.artifact_ref, self.ledger, self.governance,
                store=self.store, flow_id=flow_id)

        self.store.append(flow_id, "action", output.produced_by,
                          {"stage": "execute", "output_id": output.id,
                           "work_item_id": output.work_item_id, "artifact_ref": output.artifact_ref},
                          cost=self._ecost("execute"))

        with tracer.span("verify", _actor_of(self.verifier, "Verifier"), "verification"):
            verdict = self.verifier.verify(output, goal)
        if verdict.verified_by == output.produced_by:
            raise NonIndependentVerification(
                f"verified_by {verdict.verified_by} must differ from produced_by {output.produced_by}"
            )
        self.store.append(flow_id, "verdict", verdict.verified_by,
                          {"stage": "verify", "verdict_id": verdict.id, "decision": verdict.decision,
                           "output_id": output.id, "work_item_id": output.work_item_id},
                          cost=self._ecost("verify"))
        return verdict

    def _existing_verdict(self, flow_id, item) -> Optional[Verdict]:
        events = self.store.read(flow_id)
        verify = next((e for e in events if e.payload.get("stage") == "verify"
                       and e.payload.get("work_item_id") == item.id), None)
        if verify is None:
            return None
        p = verify.payload
        return Verdict(id=p["verdict_id"], output_id=p["output_id"], decision=p["decision"],
                       scores=[], reason="(reconstructed from the durable trail)",
                       verified_by=verify.actor, verified_at=verify.at)

    def _latest_injection(self, flow_id, work_item_id) -> Optional[dict[str, Any]]:
        # Only an injection made against *this* work item is consumed (never a stale one
        # from an earlier pause).
        for e in reversed(self.store.read(flow_id)):
            if e.kind == "injection" and e.payload.get("work_item_id") == work_item_id:
                value = {k: v for k, v in e.payload.items()
                         if k not in ("stage", "work_item_id")}
                return {"value": value, "actor": e.actor}
        return None

    def _adhoc_hit(self, flow_id, item) -> bool:
        targets = {f"pre-execute:{item.id}", "pre-execute"}
        return any(bp["step"] in targets for bp in self.list_breakpoints(flow_id))

    def _moves(self, level: str) -> list[str]:
        if level == "L0":
            return ["suggest", "reject_escalate"]
        moves = ["approve", "edit_output", "add_context", "reject_escalate"]
        if level in ("L2", "L3"):
            moves.insert(3, "override")
        return moves

    def _require_checkpoint(self, flow_id) -> Checkpoint:
        cp = self.store.latest_checkpoint(flow_id)
        if cp is None:
            raise KeyError(f"no checkpoint for flow {flow_id!r}; nothing is paused")
        return cp

    def _tracer(self, flow_id) -> Tracer:
        return Tracer(self.recorder, flow_id, self.cost_model)

    def _ecost(self, stage: str):
        return self.cost_model(stage) if self.cost_model else None
