# End-to-End Composition Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire every plane (M0–M7) into one assembled `Cell` that demonstrates the build-plan §7 definition of done on stubs, with `RuleSetGovernance` as a live, traced gate.

**Architecture:** A thin `Cell` composition root delegates to `CellHandbrake` (which already composes roles + ledger + trace + pause/resume). One additive change gives the handbrake a live governance gate at the action site (R6). The `Cell.assemble(executor=…)` constructor is the single seam a real runtime later binds to.

**Tech Stack:** Python ≥3.11, stdlib only (no new dependencies), pytest. In-memory planes only.

## Global Constraints

- Python ≥ 3.11; **no new third-party dependencies** (stdlib only).
- Run tests with: `python -m pytest -o addopts="" -q` (the `-o addopts=""` overrides the repo's `-q` so `-v`/names show when needed).
- Bind to the Protocols, never concrete classes, for injected collaborators (invariant #1).
- `RuleSetGovernance` is the assembled cell's default gate; `PermissiveGovernance` is dev-only.
- TDD: write the failing test, watch it fail, minimal code, watch it pass, commit. Frequent commits.
- Do not modify existing per-milestone test files; the full suite must stay green (0 warnings, 0 skips).
- Branch: `feat/e2e-composition` (already created, holds the design spec).

---

### Task 1: Documentation updates (amend first)

Amend the docs so the new concepts (the Cell composition root, the live action-site governance gate, the end-to-end DoD demonstration) are authoritative before the code lands. Prose only — no tests.

**Files:**
- Modify: `docs/Build-Spec.md`
- Modify: `docs/Handbrake-Interface.md`
- Modify: `docs/One-Cell-Build-Plan.md`
- Modify: `docs/Component-Selection.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Build-Spec.md — note the live action-site gate**

Find the paragraph in §5.3 that begins `Verification (R5) runs as the inline gate`. Immediately **before** it, insert:

```markdown
**Where the gate runs (the assembled cell).** R6 is evaluated at the **action site**: as the
flow handles each work item, the control plane (the Handbrake) evaluates the action against
the compiled rules *before* deciding to pause or execute, and appends a `governance` event
recording the decision — **allow and block alike** (R12). A block (e.g. an L0 action under R1)
stops the action up front; an allow proceeds (an L1 action then still hits its static
breakpoint, R4). The assembled cell wires `RuleSetGovernance` here; `PermissiveGovernance` is a
development-only stub.
```

- [ ] **Step 2: Handbrake-Interface.md — co-locate the governance gate**

Find the line in §4 that reads `2. **Idempotent actions.**` and the item after it. After the numbered list in §4 (after item `3. **Universality.**`), insert a new paragraph:

```markdown
**The governance gate is co-located with the handbrake.** Because every action passes through
the control plane, the compiled-rule check (R6, Build-Spec §5.3) is evaluated here, at the
action site, before an action pauses or executes: governance decides *may this class act at
all* (an L0 action is blocked outright), and the breakpoint enforces *the human approval an L1
action still needs*. Both decisions land on the durable, tamper-evident trail.
```

- [ ] **Step 3: One-Cell-Build-Plan.md — name the composition root**

At the very end of section `## 7. Definition of done: what proves the cell works` (immediately before the `## 8.` heading that follows it), insert:

```markdown
### 7.1 The composition root and the demonstration

The cell is assembled at one **composition root** — a `Cell` that wires the planes, the four
operating roles, the live governance gate (`RuleSetGovernance`), the effects ledger, the trace
recorder, and the Steward into one object. The four proofs above are *demonstrated* end to end
over this root by a composition harness (integration tests) and a runnable demo, on
deterministic reference roles. `PermissiveGovernance` is development-only; the assembled cell
gates on the compiled rules.

The composition root is also the **single seam for the agentic role-runtime**: a real Executor
(or any role implementer) binds by passing it to the assembler, with nothing else changing
(invariant #1). Choosing and binding that runtime — to prove the routine path on a *real*
software-delivery slice — is the next step beyond this MVP, deliberately deferred until the
substrate is proven.
```

- [ ] **Step 4: Component-Selection.md — the binding seam**

Find the row in the "rest of the stack" table whose first cell is `**Agent runtime**`. Immediately **after** that table (before the `---` that follows it), insert:

```markdown
**The composition root is where the agent runtime binds.** The cell is assembled at one place
(`cell/cell.py`) that wires the planes, roles, governance gate, ledger, trace, and Steward. A
concrete agent runtime fills a Role by being passed to the assembler (e.g.
`Cell.assemble(executor=…)`); it is invisible to every other component (invariant #1). The
runtime choice is therefore deferred to that single seam, not threaded through the architecture.
```

- [ ] **Step 5: CLAUDE.md — layout + live-governance note**

In the `## Project layout` code block, find the line `  handbrake.py          # CellHandbrake — the five control primitives on the flow (M4)` and add, immediately after it:

```
  cell.py               # Cell — composition root; wires every plane + the live governance gate
  demo.py               # runnable end-to-end demo of the §7 definition of done (python -m cell.demo)
```

Then in the `## Conventions` section, after the `- **The docs are authoritative.**` bullet, add:

```markdown
- **The assembled cell gates on the compiled rules.** `Cell.assemble()` wires `RuleSetGovernance`
  as the live R6 gate at the action site; `PermissiveGovernance` is a dev-only stub. The
  composition root (`cell/cell.py`) is the single seam where a real role-runtime binds.
```

- [ ] **Step 6: Commit**

```bash
git add docs/Build-Spec.md docs/Handbrake-Interface.md docs/One-Cell-Build-Plan.md docs/Component-Selection.md CLAUDE.md
git commit -m "docs: name the Cell composition root + live action-site governance gate"
```

---

### Task 2: Live governance gate in the Handbrake

**Files:**
- Modify: `src/cell/handbrake.py`
- Test: `tests/test_m4_handbrake.py` (append two tests)

**Interfaces:**
- Consumes: `CellHandbrake.__init__(...)` (existing), `GovernanceCheck.evaluate(action, actor) -> (bool, str)`, `RuleSetGovernance` (M5), `GovernanceBlocked`, `ActionDescriptor`, `make_idempotency_key` (from `cell.effects.wrapper`).
- Produces: the handbrake appends a `governance` event with `payload["stage"]=="gate"` and `payload["decision"] in {"allow","block"}` for every work item, and raises `GovernanceBlocked` on a block before pausing or executing.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_m4_handbrake.py`:

```python
def test_governance_gate_blocks_an_l0_work_item_up_front():
    from cell.planes.governance import RuleSetGovernance
    from cell.effects.wrapper import GovernanceBlocked

    class L0Orchestrator:
        actor = ActorRef(role="Orchestrator", version="l0")

        def decompose(self, goal):
            return [WorkItem(id=f"wi-{goal.id}", goal_id=goal.id, description="push",
                             assigned_to=EXECUTOR, action_class="CLASS_HIGH_BLAST",
                             authority_level="L0", acceptance_criteria=list(goal.acceptance_criteria))]

    calls = {"n": 0}

    class CountingExecutor:
        actor = EXECUTOR

        def execute(self, item):
            calls["n"] += 1
            return RefExecutor().execute(item)

    store = InMemoryEventStore()
    hb = CellHandbrake(director=RefDirector(), orchestrator=L0Orchestrator(),
                       executor=CountingExecutor(), verifier=RefVerifier(), store=store,
                       governance=RuleSetGovernance())
    with pytest.raises(GovernanceBlocked):
        hb.start(_ticket(), "f1")
    assert calls["n"] == 0  # never executed
    gate = [e for e in store.read("f1") if e.payload.get("stage") == "gate"]
    assert gate and gate[-1].payload["decision"] == "block"
    assert "Art. 4" in gate[-1].payload["reason"]  # the clause travels in the reason


def test_governance_gate_allows_and_logs_an_l2_work_item():
    from cell.planes.governance import RuleSetGovernance
    store = InMemoryEventStore()
    hb = CellHandbrake(director=RefDirector(), orchestrator=RefOrchestrator(),
                       executor=RefExecutor(), verifier=RefVerifier(), store=store,
                       governance=RuleSetGovernance())
    verdict = hb.start(_ticket(), "f1")
    assert verdict.decision == "pass"
    gate = [e for e in store.read("f1") if e.payload.get("stage") == "gate"]
    assert gate and gate[-1].payload["decision"] == "allow"
```

Note: `RefOrchestrator`, `EXECUTOR`, `WorkItem` are already imported at the top of this test file from earlier tasks; if not, add `from cell.roles.reference import RefOrchestrator` and ensure `WorkItem` is imported from `cell.domain.objects`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_m4_handbrake.py::test_governance_gate_blocks_an_l0_work_item_up_front -o addopts="" -v`
Expected: FAIL — no `gate` event exists / no `GovernanceBlocked` raised (the gate isn't implemented yet).

- [ ] **Step 3: Add the import**

In `src/cell/handbrake.py`, find the import block:

```python
from cell.effects.wrapper import (
    ActionDescriptor,
    EffectsLedger,
    GovernanceCheck,
    InMemoryEffectsLedger,
    make_idempotency_key,
    perform,
)
```

Add `GovernanceBlocked,` to it (alphabetically after `EffectsLedger`):

```python
from cell.effects.wrapper import (
    ActionDescriptor,
    EffectsLedger,
    GovernanceBlocked,
    GovernanceCheck,
    InMemoryEffectsLedger,
    make_idempotency_key,
    perform,
)
```

- [ ] **Step 4: Add the gate and call it in `_advance`**

In `src/cell/handbrake.py`, find `_advance`:

```python
    def _advance(self, flow_id, ticket, goal, items, index) -> Union[Verdict, Paused]:
        verdict: Optional[Verdict] = None
        while index < len(items):
            item = items[index]
            if item.authority_level in ("L0", "L1") or self._adhoc_hit(flow_id, item):
                return self._pause(flow_id, ticket, index, item)
```

Replace the loop body's top so the gate runs first:

```python
    def _advance(self, flow_id, ticket, goal, items, index) -> Union[Verdict, Paused]:
        verdict: Optional[Verdict] = None
        while index < len(items):
            item = items[index]
            self._govern(flow_id, item)  # R6 gate at the action site (logs allow/block)
            if item.authority_level in ("L0", "L1") or self._adhoc_hit(flow_id, item):
                return self._pause(flow_id, ticket, index, item)
```

Then add the `_govern` helper next to the other internals (after `_adhoc_hit`):

```python
    def _govern(self, flow_id, item) -> None:
        """R6: evaluate the work item's action against the compiled rules before it pauses or
        executes, and log the allow/block decision (R12). A block stops it up front."""
        actor = _actor_of(self.executor, "Executor")
        action = ActionDescriptor(
            id=f"gate-{item.id}", action_class=item.action_class, effect_kind="compensable",
            idempotency_key=make_idempotency_key(flow_id, f"gate:{item.id}", {"wi": item.id}),
            intent={"work_item_id": item.id})
        allowed, reason = self.governance.evaluate(action, actor)
        self.store.append(flow_id, "governance", actor, {
            "stage": "gate", "decision": "allow" if allowed else "block",
            "action_class": item.action_class, "authority_level": item.authority_level,
            "reason": reason})
        if not allowed:
            raise GovernanceBlocked(reason)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_m4_handbrake.py -o addopts="" -q`
Expected: PASS (all M4 tests, including the two new ones).

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -o addopts="" -q`
Expected: PASS — all existing tests still green (the gate is additive; reference flows use L2 → allow).

- [ ] **Step 7: Commit**

```bash
git add src/cell/handbrake.py tests/test_m4_handbrake.py
git commit -m "feat(m4): live governance gate at the action site (R6/R12)"
```

---

### Task 3: The Cell composition root

**Files:**
- Create: `src/cell/cell.py`
- Test: `tests/test_e2e_composition.py` (create)

**Interfaces:**
- Consumes: `CellHandbrake`, `Steward`, `RuleSetGovernance`, `InMemoryEventStore`, `InMemoryEffectsLedger`, `InMemoryTraceStore`, the reference roles, `total_cost`.
- Produces: `Cell.assemble(*, director=None, orchestrator=None, executor=None, verifier=None, store=None, governance=None, ledger=None, recorder=None, loop_threshold=3, cost_model=None, max_revisions=2) -> Cell`; instance methods `submit`, `inspect`, `inject`, `resume`, `replay`, `set_breakpoint`, `assess`, `trace`, `cost`, `governance_log`, `events`; attributes `store`, `governance`, `ledger`, `recorder`, `steward`, `handbrake`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_e2e_composition.py`:

```python
"""End-to-end composition harness (sub-project A) — the assembled Cell demonstrates the
build-plan §7 definition of done over the reference roles, with RuleSetGovernance as the live
gate. See docs/superpowers/specs/2026-06-27-end-to-end-composition-design.md.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cell.cell import Cell
from cell.domain.objects import ActorRef, BudgetCap, CriterionScore, Output, Ticket, Verdict, WorkItem
from cell.planes.governance import RuleSetGovernance
from cell.planes.memory import CostDelta, InMemoryEventStore
from cell.effects.wrapper import GovernanceBlocked, InMemoryEffectsLedger
from cell.roles.reference import EXECUTOR, RefExecutor

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _ticket(tid: str = "t1") -> Ticket:
    return Ticket(id=tid, source="legacy", title="Add feature X",
                  body="Please add feature X", received_at=_T0)


def test_assemble_wires_the_live_governance_gate():
    cell = Cell.assemble()
    assert isinstance(cell.governance, RuleSetGovernance)
    assert cell.handbrake.governance is cell.governance
    assert cell.steward is not None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_e2e_composition.py::test_assemble_wires_the_live_governance_gate -o addopts="" -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cell.cell'`.

- [ ] **Step 3: Write the Cell**

Create `src/cell/cell.py`:

```python
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

from cell.domain.objects import Ticket, Verdict
from cell.effects.wrapper import EffectsLedger, GovernanceCheck, InMemoryEffectsLedger
from cell.handbrake import Briefing, CellHandbrake, Paused
from cell.planes.governance import RuleSetGovernance
from cell.planes.memory import EventStore, InMemoryEventStore
from cell.planes.observability import InMemoryTraceStore, TraceStore, total_cost
from cell.roles.contracts import Director, Executor, Orchestrator, Verifier
from cell.roles.reference import RefDirector, RefExecutor, RefOrchestrator, RefVerifier
from cell.steward import Steward, StewardAction


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
                 max_revisions: int = 2) -> "Cell":
        director = director or RefDirector()
        orchestrator = orchestrator or RefOrchestrator()
        executor = executor or RefExecutor()
        verifier = verifier or RefVerifier()
        store = store or InMemoryEventStore()
        governance = governance or RuleSetGovernance()  # the live gate; not the dev stub
        ledger = ledger or InMemoryEffectsLedger()
        recorder = recorder or InMemoryTraceStore()
        steward = Steward(store, loop_threshold=loop_threshold)
        handbrake = CellHandbrake(
            director=director, orchestrator=orchestrator, executor=executor,
            verifier=verifier, store=store, ledger=ledger, governance=governance,
            recorder=recorder, cost_model=cost_model, max_revisions=max_revisions)
        return cls(director, orchestrator, executor, verifier, store, governance,
                   ledger, recorder, steward, handbrake)

    # -- operations (delegate to the control plane / steward) -----------------

    def submit(self, ticket: Ticket, flow_id: str) -> Union[Verdict, Paused]:
        return self.handbrake.start(ticket, flow_id)

    def inspect(self, flow_id: str) -> Briefing:
        return self.handbrake.inspect(flow_id)

    def inject(self, flow_id: str, value: dict, actor) -> None:
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
        return [e for e in self.store.read(flow_id) if e.kind == "governance"]

    def events(self, flow_id: str):
        return self.store.read(flow_id)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_e2e_composition.py::test_assemble_wires_the_live_governance_gate -o addopts="" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cell/cell.py tests/test_e2e_composition.py
git commit -m "feat: Cell composition root wiring every plane + the live gate"
```

---

### Task 4: Scenarios 1 & 2 — routine autonomous + dramatic takeover

**Files:**
- Test: `tests/test_e2e_composition.py` (append)

**Interfaces:**
- Consumes: `Cell.assemble`, `Cell.submit/inspect/inject/resume`, `Briefing`, `Paused`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_e2e_composition.py`:

```python
class L1Orchestrator:
    """One L1 work item -> a static breakpoint precedes its action (the dramatic path)."""
    actor = ActorRef(role="Orchestrator", version="l1-orch")

    def decompose(self, goal):
        return [WorkItem(id=f"wi-{goal.id}", goal_id=goal.id, description="Comment on the issue",
                         assigned_to=EXECUTOR, action_class="CLASS_EXTERNAL_COMM",
                         authority_level="L1", acceptance_criteria=list(goal.acceptance_criteria))]


def test_routine_path_runs_autonomously_end_to_end():
    cell = Cell.assemble()  # reference roles -> an L2 work item -> no pause
    verdict = cell.submit(_ticket(), "f1")
    assert not isinstance(verdict, Paused)
    assert verdict.decision == "pass"
    # governance ran as the live gate and allowed it
    gate = [e for e in cell.governance_log("f1") if e.payload.get("stage") == "gate"]
    assert gate and gate[-1].payload["decision"] == "allow"
    # the run is fully traced
    assert {s.step for s in cell.trace("f1")} >= {"specify", "decompose", "execute", "verify"}


def test_dramatic_path_takeover_via_the_handbrake():
    cell = Cell.assemble(orchestrator=L1Orchestrator())
    paused = cell.submit(_ticket(), "f1")
    assert isinstance(paused, Paused)

    briefing = cell.inspect("f1")
    assert briefing.authority_level == "L1"
    assert "approve" in briefing.valid_moves and briefing.recent_decisions

    human = ActorRef(role="Executor", version="human:alice", mode="human")
    cell.inject("f1", {"type": "edited_output", "output_id": "corrected",
                       "artifact_ref": "branch://corrected"}, human)
    verdict = cell.resume("f1")
    assert verdict.decision == "pass"
    exec_event = next(e for e in cell.events("f1") if e.payload.get("stage") == "execute")
    assert exec_event.payload["artifact_ref"] == "branch://corrected"
    assert exec_event.actor == human
```

- [ ] **Step 2: Run the tests**

Run: `python -m pytest tests/test_e2e_composition.py -o addopts="" -q`
Expected: PASS (the Cell + gate from Tasks 2–3 already provide this behavior; these tests assert the composition).

If a test fails, fix the wiring in `src/cell/cell.py` or the gate in `src/cell/handbrake.py` — do not weaken the assertions.

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e_composition.py
git commit -m "test(e2e): routine-autonomous + dramatic-takeover scenarios"
```

---

### Task 5: Scenarios 3, 4 & 5 — kill-resume, policy block, steward loop

**Files:**
- Test: `tests/test_e2e_composition.py` (append)

**Interfaces:**
- Consumes: `Cell.assemble(store=…, ledger=…)` (shared durable plane), `Cell.assess`, `GovernanceBlocked`, `BudgetCap`, `CostDelta`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_e2e_composition.py`:

```python
class L0Orchestrator:
    actor = ActorRef(role="Orchestrator", version="l0-orch")

    def decompose(self, goal):
        return [WorkItem(id=f"wi-{goal.id}", goal_id=goal.id, description="push to main",
                         assigned_to=EXECUTOR, action_class="CLASS_HIGH_BLAST",
                         authority_level="L0", acceptance_criteria=list(goal.acceptance_criteria))]


class ReturnVerifier:
    """Always returns 'return' -> induces a produce->revise loop (the runaway signal)."""
    actor = ActorRef(role="Verifier", version="ref-v0")

    def verify(self, output, goal):
        return Verdict(id=f"v-{output.id}", output_id=output.id, decision="return",
                       scores=[CriterionScore(criterion_id="c", result="unclear")],
                       reason="needs revision", verified_by=self.actor, verified_at=_T0)


def test_kill_and_resume_is_safe_across_a_fresh_controller():
    store, ledger = InMemoryEventStore(), InMemoryEffectsLedger()
    calls = {"n": 0}

    class CountingExecutor:
        actor = EXECUTOR

        def execute(self, item):
            calls["n"] += 1
            return RefExecutor().execute(item)

    Cell.assemble(orchestrator=L1Orchestrator(), executor=CountingExecutor(),
                  store=store, ledger=ledger).submit(_ticket(), "f1")  # pauses at L1

    # a fresh cell over the SAME durable plane resumes from the checkpoint
    fresh = Cell.assemble(orchestrator=L1Orchestrator(), executor=CountingExecutor(),
                          store=store, ledger=ledger)
    verdict = fresh.resume("f1")
    assert verdict.decision == "pass"
    assert calls["n"] == 1  # the external effect ran exactly once


def test_out_of_policy_action_is_blocked_and_traceable():
    calls = {"n": 0}

    class CountingExecutor:
        actor = EXECUTOR

        def execute(self, item):
            calls["n"] += 1
            return RefExecutor().execute(item)

    cell = Cell.assemble(orchestrator=L0Orchestrator(), executor=CountingExecutor())
    with pytest.raises(GovernanceBlocked):
        cell.submit(_ticket(), "f1")
    assert calls["n"] == 0
    block = [e for e in cell.governance_log("f1") if e.payload.get("decision") == "block"]
    assert block and "Art. 4" in block[-1].payload["reason"]  # traces to a clause


def test_steward_quarantines_an_induced_loop_before_the_cap():
    cell = Cell.assemble(verifier=ReturnVerifier(), max_revisions=5, loop_threshold=3,
                         cost_model=lambda stage: CostDelta(compute=100))
    cell.submit(_ticket(), "f1")  # L2 item, loops on 'return' up to max_revisions
    budget = BudgetCap(compute=10_000, wall_clock_ms=15 * 60 * 1000)
    action = cell.assess("f1", budget)
    assert action.kind == "quarantine"
    assert action.rule == "R8"
    assert cell.cost("f1").compute < budget.compute  # quarantined before the cap
```

- [ ] **Step 2: Run the tests**

Run: `python -m pytest tests/test_e2e_composition.py -o addopts="" -q`
Expected: PASS. If `test_steward_quarantines_an_induced_loop_before_the_cap` fails because too few execute events accrued, confirm `max_revisions=5` yields 6 execute attempts (> `loop_threshold=3`).

- [ ] **Step 3: Run the full suite**

Run: `python -m pytest -o addopts="" -q`
Expected: PASS — everything green.

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_composition.py
git commit -m "test(e2e): kill-resume, policy-block, steward-loop scenarios"
```

---

### Task 6: The demo CLI

**Files:**
- Create: `src/cell/demo.py`
- Test: `tests/test_e2e_composition.py` (append a smoke test)

**Interfaces:**
- Consumes: `Cell`, the scenario role classes (re-declared in `demo.py` so it is self-contained), `main() -> None`.
- Produces: `python -m cell.demo` prints all five scenarios; `cell.demo.main()` returns `None` and raises nothing.

- [ ] **Step 1: Write the failing smoke test**

Append to `tests/test_e2e_composition.py`:

```python
def test_demo_runs_without_error(capsys):
    from cell import demo
    demo.main()
    out = capsys.readouterr().out
    assert "Routine" in out and "blocked" in out.lower() and "quarantine" in out.lower()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_e2e_composition.py::test_demo_runs_without_error -o addopts="" -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cell.demo'`.

- [ ] **Step 3: Write the demo**

Create `src/cell/demo.py`:

```python
"""Runnable end-to-end demo of the cell's §7 definition of done (python -m cell.demo).

Submits sample tickets through an assembled Cell and prints each scenario legibly. In-memory
planes only — no external systems, no LLM. Reference roles stand in for a real role-runtime.
"""

from __future__ import annotations

from datetime import datetime, timezone

from cell.cell import Cell
from cell.domain.objects import (ActorRef, BudgetCap, CriterionScore, Ticket, Verdict, WorkItem)
from cell.effects.wrapper import GovernanceBlocked
from cell.planes.memory import CostDelta, InMemoryEventStore
from cell.effects.wrapper import InMemoryEffectsLedger
from cell.roles.reference import EXECUTOR, RefExecutor

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _ticket(tid: str) -> Ticket:
    return Ticket(id=tid, source="legacy", title="Add feature X",
                  body="Please add feature X", received_at=_T0)


class _L1Orchestrator:
    actor = ActorRef(role="Orchestrator", version="l1")

    def decompose(self, goal):
        return [WorkItem(id=f"wi-{goal.id}", goal_id=goal.id, description="Comment externally",
                         assigned_to=EXECUTOR, action_class="CLASS_EXTERNAL_COMM",
                         authority_level="L1", acceptance_criteria=list(goal.acceptance_criteria))]


class _L0Orchestrator:
    actor = ActorRef(role="Orchestrator", version="l0")

    def decompose(self, goal):
        return [WorkItem(id=f"wi-{goal.id}", goal_id=goal.id, description="Push to main",
                         assigned_to=EXECUTOR, action_class="CLASS_HIGH_BLAST",
                         authority_level="L0", acceptance_criteria=list(goal.acceptance_criteria))]


class _ReturnVerifier:
    actor = ActorRef(role="Verifier", version="ref-v0")

    def verify(self, output, goal):
        return Verdict(id=f"v-{output.id}", output_id=output.id, decision="return",
                       scores=[CriterionScore(criterion_id="c", result="unclear")],
                       reason="needs revision", verified_by=self.actor, verified_at=_T0)


def _rule(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def main() -> None:
    # 1 — routine path, fully autonomous
    _rule("1. Routine path — autonomous (L2, no human)")
    cell = Cell.assemble()
    verdict = cell.submit(_ticket("t1"), "f1")
    print(f"verdict: {verdict.decision}")
    print(f"governance: {cell.governance_log('f1')[-1].payload['decision']}")
    print(f"cost: {cell.cost('f1').compute} | steps: {[s.step for s in cell.trace('f1')]}")

    # 2 — dramatic path, human takeover via the handbrake
    _rule("2. Dramatic path — handbrake takeover (L1)")
    cell = Cell.assemble(orchestrator=_L1Orchestrator())
    paused = cell.submit(_ticket("t2"), "f2")
    print(f"paused at: {paused.step} ({paused.reason})")
    briefing = cell.inspect("f2")
    print(f"briefing: role={briefing.role} moves={briefing.valid_moves}")
    human = ActorRef(role="Executor", version="human:alice", mode="human")
    cell.inject("f2", {"type": "edited_output", "output_id": "corrected",
                       "artifact_ref": "branch://corrected"}, human)
    verdict = cell.resume("f2")
    artifact = next(e for e in cell.events("f2") if e.payload.get("stage") == "execute").payload["artifact_ref"]
    print(f"resumed -> verdict: {verdict.decision} | used injection: {artifact}")

    # 3 — kill-and-resume is safe (exactly-once effect)
    _rule("3. Kill-and-resume — exactly-once across a fresh controller")
    store, ledger = InMemoryEventStore(), InMemoryEffectsLedger()
    calls = {"n": 0}

    class _CountingExecutor:
        actor = EXECUTOR

        def execute(self, item):
            calls["n"] += 1
            return RefExecutor().execute(item)

    Cell.assemble(orchestrator=_L1Orchestrator(), executor=_CountingExecutor(),
                  store=store, ledger=ledger).submit(_ticket("t3"), "f3")
    Cell.assemble(orchestrator=_L1Orchestrator(), executor=_CountingExecutor(),
                  store=store, ledger=ledger).resume("f3")
    print(f"effect executions across pause+restart+resume: {calls['n']} (exactly once)")

    # 4 — out-of-policy action blocked and traceable
    _rule("4. Out-of-policy — L0 action blocked and traced to a clause")
    cell = Cell.assemble(orchestrator=_L0Orchestrator())
    try:
        cell.submit(_ticket("t4"), "f4")
    except GovernanceBlocked as exc:
        print(f"blocked: {exc}")
    block = [e for e in cell.governance_log("f4") if e.payload.get("decision") == "block"][-1]
    print(f"audit: {block.payload['action_class']} -> block | reason: {block.payload['reason']}")

    # 5 — steward quarantines a runaway loop before the cap
    _rule("5. Steward — induced loop quarantined before the budget cap")
    cell = Cell.assemble(verifier=_ReturnVerifier(), max_revisions=5, loop_threshold=3,
                         cost_model=lambda stage: CostDelta(compute=100))
    cell.submit(_ticket("t5"), "f5")
    action = cell.assess("f5", BudgetCap(compute=10_000, wall_clock_ms=900_000))
    print(f"steward: {action.kind} ({action.rule}) | reason: {action.reason}")
    print(f"cost at quarantine: {cell.cost('f5').compute} (cap 10000)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the smoke test and the demo**

Run: `python -m pytest tests/test_e2e_composition.py::test_demo_runs_without_error -o addopts="" -v`
Expected: PASS.

Run: `python -m cell.demo`
Expected: five labelled sections print; scenario 3 reports exactly one execution; scenario 4 prints a block + clause; scenario 5 prints a quarantine.

- [ ] **Step 5: Commit**

```bash
git add src/cell/demo.py tests/test_e2e_composition.py
git commit -m "feat: runnable end-to-end demo of the §7 definition of done"
```

---

### Task 7: Final verification & PR

**Files:** none (verification + PR).

- [ ] **Step 1: Run the full suite**

Run: `python -m pytest -o addopts="" -q`
Expected: PASS — all tests green, 0 warnings, 0 skips.

- [ ] **Step 2: Run the demo end to end**

Run: `python -m cell.demo`
Expected: all five scenarios print correctly.

- [ ] **Step 3: Push and open the PR**

```bash
git push -u origin feat/e2e-composition
gh pr create --base main --head feat/e2e-composition \
  --title "Sub-project A: end-to-end composition harness + live governance gate" \
  --body "Wires every plane (M0-M7) into an assembled Cell that demonstrates the build-plan §7 definition of done on stubs, with RuleSetGovernance as a live action-site gate. Adds the Cell composition root (the runtime seam), the gate, five integration scenarios, a runnable demo, and the doc updates that keep concepts in lockstep. See docs/superpowers/specs/2026-06-27-end-to-end-composition-design.md."
```

- [ ] **Step 4: Address Augment review, then merge**

Wait for the Augment review, address valid findings (TDD), comment the resolution, and merge with `gh pr merge <n> --merge --delete-branch`.

---

## Notes for the implementer

- The reference roles are deterministic — `RefDirector` produces `goal.id == f"goal-{ticket.id}"`, `RefOrchestrator` an L2 `CLASS_OWN_WRITE` item `wi-goal-<tid>`, `RefExecutor` an `Output` `out-wi-goal-<tid>` with `artifact_ref f"branch://wi-goal-<tid>"`. The scenario orchestrators override `decompose` to set the authority class under test.
- The governance gate (Task 2) and the Cell (Task 3) are the only real new behavior; Tasks 4–5 are integration assertions that should pass once those land. If one fails, fix the wiring, never the assertion.
- `GovernanceBlocked` is raised by the gate (Task 2) before any pause/execute for an L0 action — that propagates out of `Cell.submit`.
- Keep everything behind the Protocols; do not import concrete planes into `handbrake.py` beyond what is already there.
