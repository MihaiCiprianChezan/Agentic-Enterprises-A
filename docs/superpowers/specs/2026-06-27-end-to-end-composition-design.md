---
Title: End-to-End Composition Harness — Design Spec (sub-project A)
Version: 0.1.0
Date: 27.06.2026
Status: Draft — awaiting review
Companion to: One-Cell-Build-Plan.md §7 · Build-Spec.md §5–6 · Handbrake-Interface.md
---

# End-to-End Composition Harness (sub-project A)

## 1. Purpose & context

Milestones M0–M7 are built and merged: every plane and role exists and is unit-tested in
isolation. Nothing yet wires **all** of them into one coherent run, and the cell still
defaults to the `PermissiveGovernance` stub. This sub-project builds the **composition
harness**: one assembled cell that exercises every plane together, proving the build plan's
*definition of done* (§7) on the reference stubs.

This harness is the first half of a two-part effort the Board chose ("both, in sequence"):

- **A (this spec):** prove the substrate composes — deterministic, on stubs, no LLM/external
  systems.
- **B (later, its own spec):** swap the stub Executor for a real agentic role-runtime.

A is deliberately the *harness B plugs into*: the composition root is the single seam where a
real runtime later binds (invariant #1), so B changes one constructor argument, nothing else.

**Out of scope:** any real runtime, repo/sandbox/PR integration, network, or LLM (all of that
is B). The agentic role-runtime stays unbound and swappable.

## 2. Chosen approach

**Approach A — a thin `Cell` over `CellHandbrake`, with a live governance gate added to the
handbrake.** The handbrake (M4) already composes the roles + ledger + trace + pause/resume —
it is ~90% of the composition. We add one additive step: before a work item acts, the
handbrake evaluates the action through the `GovernanceCheck` Protocol and appends an allow/
block `governance` event (it already holds the store). With `RuleSetGovernance` wired in, R6
becomes a **live, traced** gate, which also yields the "out-of-policy blocked & traceable" DoD
for free.

Rejected alternatives: **B** (the `Cell` checks governance around an unchanged handbrake —
leaky, the handbrake produces work items internally so the Cell can't cleanly intercept them);
**C** (a new unified runner — duplicates M4's pause/resume, risks divergence, not YAGNI).

## 3. Components

### 3.1 Composition root — `src/cell/cell.py`
A `Cell` with an `assemble(...)` classmethod/factory wiring the defaults:

- roles: the reference Director/Orchestrator/Executor/Verifier (overridable);
- planes: `InMemoryEventStore`, `InMemoryTraceStore`;
- **governance: `RuleSetGovernance` — the live gate** (the cell default; `PermissiveGovernance`
  becomes dev-only);
- effects: `InMemoryEffectsLedger`;
- system role: `Steward`.

Operations (delegating, not reimplementing):

- `submit(ticket, flow_id) -> Verdict | Paused` → `CellHandbrake.start`;
- handbrake ops: `inspect`, `inject`, `resume`, `replay`, `set_breakpoint`/`list`/`clear`;
- `assess(flow_id) -> StewardAction` → the Steward against the goal's budget cap;
- read helpers for tests/demo: `trace(flow_id)`, `cost(flow_id)`, `governance_log(flow_id)`.

**The seam:** `Cell.assemble(executor=RealExecutor(...))` is all sub-project B changes.

### 3.2 Live governance gate — additive edit to `src/cell/handbrake.py`
When the flow first handles a work item (in `_advance`, **before** the pause-or-execute
decision), the handbrake builds the `ActionDescriptor`, calls `governance.evaluate(action,
actor)` (the Protocol surface), and appends a `governance` event recording `allow|block` with
the reason (the reason carries the clause for `RuleSetGovernance`; R12 logs allows *and*
blocks). A **block** (e.g. an L0 action under R1) raises `GovernanceBlocked` up front — the
agent never pauses for it or executes it. An **allow** proceeds to the normal logic: an **L1**
action is permitted (act-with-approval) and then hits its static breakpoint for the human
(R4); **L2/L3** execute. This cleanly separates the two gates — governance (R6) decides *may
this class act at all*, the breakpoint (R4) enforces *the human approval an L1 still needs*.
Bound to the `GovernanceCheck` Protocol, so behaviour under the permissive stub is unchanged
(it logs a permissive allow). `perform()` remains the effect-level guard behind it.

### 3.3 Demo CLI — `src/cell/demo.py` (`python -m cell.demo`)
Runs the five scenarios in sequence and prints them legibly — the trace, the takeover
briefing, the governance block + clause, the steward quarantine. In-memory planes only; no
external dependencies.

## 4. The five demonstrated scenarios

Each builds a `Cell` with scenario-appropriate roles (the Cell is parameterized by roles).

| # | DoD (§7) | Realization in the wired Cell | Key assertions |
|---|---|---|---|
| 1 | Routine path autonomous | L2 work item → no pause → governance **allows** → execute → verify **pass** → handed back | `Verdict.pass`, not `Paused`, a governance allow event, full trace, zero human calls |
| 2 | Dramatic path on demand | L1 work item → governance **allows** (act-with-approval) → **pause** at the breakpoint → `inspect` briefing → `inject` corrected output → `resume` uses it | resumed output is the injected one (human-produced), verdict pass |
| 3 | Kill-and-resume safe | pause → **fresh `Cell` on the same durable store + ledger** → `resume` | the external effect fires **exactly once** (re-exercises M0 at the cell level) |
| 4 | Out-of-policy blocked & traceable | L0 work item (`CLASS_HIGH_BLAST`) → governance gate **blocks up front (R1)** → never pauses or executes | `GovernanceBlocked`, a block event citing the clause, executor never called |
| 5 | Steward (M7) | always-return verifier + high revisions → repeated execute attempts → `assess` | **quarantine (R8)** with running cost still under the budget cap |

Scenario 3's true process-death kill is M0's already-proven subprocess gate; here it is
exercised in-process via a fresh controller over the shared durable plane (the doc marks #3
"shared with build-plan §7 item 3").

## 5. Documentation updates (amend first — concept ≡ implementation)

The cell's convention is that docs are authoritative; these edits land **before/with** the
code so the concepts never derail from the implementation.

| Doc | Change |
|---|---|
| `Build-Spec.md` | §5.3/§6: the R6 gate runs **at the action site** and logs **allow and block** (R12); the assembled cell uses `RuleSetGovernance`, not the stub |
| `Handbrake-Interface.md` | the handbrake **co-locates the governance gate** (R6) with the breakpoint — an action is governance-checked before it acts |
| `One-Cell-Build-Plan.md` | name the **Cell composition root**; §7 DoD is *demonstrated* end-to-end via the harness + demo; `PermissiveGovernance` is dev-only |
| `Component-Selection.md` | the composition root is the **wiring point where the agent runtime binds** (the runtime-agnostic seam) |
| `CLAUDE.md` | project layout (`cell.py`, `demo.py`, the e2e test) + the live-governance-default note |

**Left untouched on purpose:** `Agentic-First-Enterprises.md` (the model — governance-before-
effect is already in it; the composition root is an implementation detail) and
`Cell-Constitution.md` (the source that compiles *into* governance, not affected by it).

## 6. Testing

- `tests/test_e2e_composition.py` — the five scenarios as integration tests over the `Cell`.
- Existing per-milestone suites stay untouched; the full suite stays green (no warnings, no
  skips).
- TDD throughout: each scenario test is written and watched fail before the wiring exists.

## 7. Files

- **New:** `src/cell/cell.py`, `src/cell/demo.py`, `tests/test_e2e_composition.py`.
- **Modified:** `src/cell/handbrake.py` (the additive governance gate); the five docs in §5.

## 8. Success criteria (definition of done for sub-project A)

1. `Cell.assemble()` wires every plane with `RuleSetGovernance` as the live gate.
2. All five scenarios pass as integration tests; the full suite is green.
3. `python -m cell.demo` prints a legible end-to-end run of all five scenarios.
4. Every doc in §5 reflects the new concepts; no doc contradicts the implementation.
5. The composition root exposes a single executor seam ready for sub-project B.
