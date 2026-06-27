"""Domain objects — the wire schema between roles.

Direct realization of Build-Spec.md §1 (data objects) and §2 (event plane).
These are logical schemas; field names and types track the spec one-to-one so the
docs remain the source of truth. Nothing here performs behavior — these are data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Literal, Optional

if TYPE_CHECKING:  # CostDelta lives in planes.memory, which imports this module — avoid the cycle
    from cell.planes.memory import CostDelta

# --- shared -----------------------------------------------------------------

Level = Literal["L0", "L1", "L2", "L3"]


@dataclass(frozen=True)
class ActorRef:
    """Who/what acted. `version` is the version-registry stub (Build-Spec §1, §2.4)."""
    role: str
    version: str
    mode: Literal["agent", "human"] = "agent"
    office: Optional[str] = None  # set only when a human Office-holder is impersonating


@dataclass(frozen=True)
class Criterion:
    id: str
    statement: str
    kind: Literal["test", "lint", "review", "policy"]


@dataclass(frozen=True)
class RiskFlag:
    area: str
    action_class: str
    level: Level


@dataclass(frozen=True)
class BudgetCap:
    compute: float
    wall_clock_ms: int
    human_time_ms: Optional[int] = None
    units: str = "tokens"


# --- the five wire objects (Build-Spec §1) ----------------------------------

@dataclass
class Ticket:
    id: str
    source: str
    title: str
    body: str
    received_at: datetime
    raw_refs: list[str] = field(default_factory=list)


@dataclass
class Goal:
    id: str
    ticket_id: str
    outcome: str
    acceptance_criteria: list[Criterion]
    budget_cap: BudgetCap
    created_by: ActorRef
    created_at: datetime
    in_purpose: bool = True            # Director boundary check (Constitution Art. 1.3, 2.1)
    constraints: list[str] = field(default_factory=list)
    risk_flags: list[RiskFlag] = field(default_factory=list)


@dataclass(frozen=True)
class Breakpoint:
    id: str
    position: Literal["before", "after"]
    kind: Literal["static", "dynamic"]
    condition: Optional[str] = None


@dataclass
class WorkItem:
    id: str
    goal_id: str
    description: str
    assigned_to: ActorRef
    action_class: str
    authority_level: Level
    acceptance_criteria: list[Criterion]
    depends_on: list[str] = field(default_factory=list)
    breakpoints: list[Breakpoint] = field(default_factory=list)


@dataclass
class Output:
    id: str
    work_item_id: str
    artifact_ref: str                  # a handle to the artifact, never the live effect itself
    produced_by: ActorRef
    trace_ref: str
    produced_at: datetime
    side_effects: list[str] = field(default_factory=list)  # idempotency keys; see effects.wrapper
    cost: Optional["CostDelta"] = None   # what producing it cost (e.g. a runtime's token usage)


@dataclass(frozen=True)
class CriterionScore:
    criterion_id: str
    result: Literal["met", "unmet", "unclear"]
    note: Optional[str] = None


@dataclass
class Verdict:
    id: str
    output_id: str
    decision: Literal["pass", "return", "block"]
    scores: list[CriterionScore]
    reason: str
    verified_by: ActorRef              # R5 requires verified_by != Output.produced_by
    verified_at: datetime
