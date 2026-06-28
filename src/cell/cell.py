"""The Cell — composition root (sub-project A).

Assembles every plane and role into one object and exposes the cell's operations by delegating
to CellHandbrake (the control plane) and the Steward. This is the single seam where a real
role-runtime binds: Cell.assemble(executor=RealExecutor(...)) changes one argument, nothing
else (invariant #1). The assembled cell gates on the compiled rules (RuleSetGovernance);
PermissiveGovernance is dev-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Union

from cell.domain.objects import ActorRef, Ticket, Verdict
from cell.effects.wrapper import EffectsLedger, GovernanceCheck, InMemoryEffectsLedger
from cell.flow import _actor_of
from cell.handbrake import Briefing, CellHandbrake, Paused
from cell.planes.governance import RuleSetGovernance
from cell.planes.memory import EventStore, InMemoryEventStore
from cell.planes.observability import InMemoryTraceStore, TraceStore, total_cost
from cell.roles.contracts import Director, Executor, Orchestrator, Verifier
from cell.roles.reference import RefDirector, RefExecutor, RefOrchestrator, RefVerifier
from cell.auditor import Auditor
from cell.steward import Steward, StewardAction
from cell.versions import VersionRegistry, version_stats


@dataclass
class Cell:
    """The wired cell. Build it with `Cell.assemble(...)`."""
    director: Director
    orchestrator: Orchestrator
    executor: Executor
    verifier: Verifier
    store: EventStore
    governance: GovernanceCheck
    ledger: EffectsLedger
    recorder: TraceStore
    steward: Steward
    handbrake: CellHandbrake
    registry: Any = None
    auditor: Any = None

    @classmethod
    def assemble(cls, *, director: Optional[Director] = None,
                 orchestrator: Optional[Orchestrator] = None,
                 executor: Optional[Executor] = None,
                 verifier: Optional[Verifier] = None,
                 store: Optional[EventStore] = None,
                 governance: Optional[GovernanceCheck] = None,
                 ledger: Optional[EffectsLedger] = None,
                 recorder: Optional[TraceStore] = None,
                 loop_threshold: int = 3, cost_model: Any = None,
                 max_revisions: int = 2, clock: Any = None,
                 optimizer: Any = None, implementers: Any = None) -> "Cell":
        director = director or RefDirector()
        orchestrator = orchestrator or RefOrchestrator()
        executor = executor or RefExecutor()
        verifier = verifier or RefVerifier()
        store = store or InMemoryEventStore()
        governance = governance or RuleSetGovernance()  # the live gate; not the dev stub
        ledger = ledger or InMemoryEffectsLedger()
        recorder = recorder or InMemoryTraceStore()
        steward = Steward(store, loop_threshold=loop_threshold)
        registry = VersionRegistry(store)
        # Register the running versions as active so the Auditor (M9) sees the full set: the four
        # operating roles, plus each routable implementer (an Executor variant).
        for role in (director, orchestrator, executor, verifier):
            actor = _actor_of(role, "")
            registry.register(actor.role, actor.version)   # by role name, matching execute-event roles
        for im in (implementers or []):
            registry.register("Executor", im.id)
        handbrake = CellHandbrake(
            director=director, orchestrator=orchestrator, executor=executor,
            verifier=verifier, store=store, ledger=ledger, governance=governance,
            recorder=recorder, cost_model=cost_model, max_revisions=max_revisions, clock=clock,
            optimizer=optimizer, implementers=implementers, registry=registry)
        auditor = Auditor(store, registry)
        return cls(director, orchestrator, executor, verifier, store, governance,
                   ledger, recorder, steward, handbrake, registry, auditor)

    # -- operations (delegate to the control plane / steward) -----------------

    def submit(self, ticket: Ticket, flow_id: str) -> Union[Verdict, Paused]:
        return self.handbrake.start(ticket, flow_id)

    def inspect(self, flow_id: str) -> Briefing:
        return self.handbrake.inspect(flow_id)

    def inject(self, flow_id: str, value: dict, actor: ActorRef) -> None:
        return self.handbrake.inject(flow_id, value, actor)

    def resume(self, flow_id: str) -> Union[Verdict, Paused]:
        return self.handbrake.resume(flow_id)

    def replay(self, flow_id: str, to_step: Optional[str] = None) -> list[dict]:
        return self.handbrake.replay(flow_id, to_step)

    def set_breakpoint(self, flow_id: str, step: str, kind: str = "static",
                       condition: Optional[str] = None) -> str:
        return self.handbrake.set_breakpoint(flow_id, step, kind, condition)

    def assess(self, flow_id: str, budget_cap) -> StewardAction:
        return self.steward.assess(flow_id, budget_cap)

    # -- read helpers (for tests / the demo) ----------------------------------

    def trace(self, flow_id: str):
        return self.recorder.spans(flow_id)

    def cost(self, flow_id: str):
        return total_cost(self.store.read(flow_id))

    def governance_log(self, flow_id: str):
        """All governance-plane events for the flow — both the _govern action-site gate decisions and any R11 injection blocks."""
        return [e for e in self.store.read(flow_id) if e.kind == "governance"]

    def events(self, flow_id: str):
        return self.store.read(flow_id)

    def versions(self):
        """The registered role versions and their status (the Auditor's set, M9)."""
        return self.registry.records()

    def version_stats(self):
        """Per-version field scorecard (runs / pass / return / mean cost)."""
        return version_stats(self.store.all_events())

    def audit(self):
        """Run the Auditor: rate every version, emit audit records, and return the ratings (M9b).
        Read + report only — it never suspends or modifies anything (that is 9c)."""
        return self.auditor.report()
