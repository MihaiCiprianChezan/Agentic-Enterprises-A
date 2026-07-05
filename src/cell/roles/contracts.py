"""Role contracts as interfaces.

Realizes Role-Contracts.md (M2). The system binds to these Protocols, never to whether
an agent or a human implements them (invariant #1). Each method signature reflects the
role's inputs -> outputs from the contract doc. Bodies are implemented per role at M2;
these are the seams the rest of the cell depends on.

Deferred roles (Optimizer, Auditor) are intentionally absent (Constitution Art. 3.4).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from cell.domain.objects import Goal, Output, Ticket, Verdict, WorkItem


@runtime_checkable
class Director(Protocol):
    """Direction — turns a Ticket into a specified Goal under the constitution."""

    def specify(self, ticket: Ticket) -> Goal: ...


@runtime_checkable
class Orchestrator(Protocol):
    """Orchestration — decomposes a Goal into sequenced WorkItems with breakpoints."""

    def decompose(self, goal: Goal) -> list[WorkItem]: ...


@runtime_checkable
class Executor(Protocol):
    """Execution — produces the Output for a single WorkItem, within its authority class."""

    def execute(self, item: WorkItem) -> Output: ...


@runtime_checkable
class Verifier(Protocol):
    """Verification — independently scores an Output. R5: verified_by != produced_by."""

    def verify(self, output: Output, goal: Goal) -> Verdict: ...


@runtime_checkable
class Steward(Protocol):
    """System role — watches health; may quarantine/rollback. ZERO business authority.
    Maintains live instances; does NOT permanently replace an implementer (that is the Board)."""

    def quarantine(self, flow_id: str, reason: str) -> None: ...
    def rollback(self, flow_id: str, to_seq: int) -> None: ...
