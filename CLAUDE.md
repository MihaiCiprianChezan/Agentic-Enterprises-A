# CLAUDE.md — Agent-Native Cell

Context for Claude Code (or any agent) picking up this repo. Read this first.

## What this is

One sovereign **cell** of the Agent-Native Enterprise model — the smallest complete unit
of the architecture, scoped around a **software-delivery workflow**: intake a feature/bug
request → produce a code change → verify it → hand the change back to the existing human
review/merge process. It is **not** a federation; one cell first, by design.

The full design lives in `docs/` and is the source of truth. Code must conform to it.

## Read the design before coding (in this order)

1. `docs/Agentic-First-Enterprises.md` — the model. The 11 design invariants in §1 are non-negotiable.
2. `docs/One-Cell-Build-Plan.md` — the MVP plan and milestone order (M0–M7).
3. `docs/Cell-Constitution.md` — the constitution this cell runs under (Articles 1–10).
4. `docs/Role-Contracts.md` — the five role interfaces (M2).
5. `docs/Handbrake-Interface.md` — the control plane (M4).
6. `docs/Build-Spec.md` — **the spec code is built against**: schemas (§1–2), trace/cost (§3),
   the idempotency wrapper (§4), and the governance rule set R1–R12 (§5).
7. `docs/Component-Selection.md` — capability → tool mapping; what M0 needs vs. what to defer.

## The invariants that constrain every line of code

- **#1** Depend on the contract, not the implementer. Bind to the Protocols in `cell/roles/contracts.py`.
- **#3** Every flow has a handbrake (pause/inspect/inject/resume/replay). Structural, not a feature.
- **#4** Side effects are safe to retry: exactly-once for reversible, **at-most-once** for irreversible.
  The outside world is never assumed idempotent. All effects go through `cell/effects/wrapper.py`.
- **#5** State lives outside the actor. Nothing durable in an agent's memory — it goes to the event plane.
- **#9** A human who takes over a Role is bound by that Role's authority, not their human Office.
- **#10** Governance is compiled from the constitution; agents never author their own rules.

## Current target: M0 — the two seams

M0 proves the mechanic everything else rests on. Two deliverables:

1. **Durable event store** — make `cell/planes/memory.py`'s `EventStore` persistent
   (SQLite or Postgres, one append-only hash-chained `events` table + a `checkpoints` table).
   The `InMemoryEventStore` is the reference; a durable class implements the same Protocol.
2. **Idempotent-action wrapper** — implement `cell/effects/wrapper.py::perform()` per
   Build-Spec §4.2 against a **durable** effects ledger, so killing the process mid-effect
   and re-running cannot double-fire.

**Definition of done (Build-Spec §7, build-plan §7 item 3):** kill the process after an
effect is recorded in-flight but before completion; on restart, the flow resumes and the
effect ends up applied exactly once (reversible) or at-most-once (irreversible) — never twice.

The acceptance tests are in `tests/test_m0_idempotency.py`. The structural tests
(event chain, tamper-evidence, key determinism) pass now; the two exactly-once tests are
`skip`-marked — implement `perform()`, remove the skips, and they become the real M0 gate.

**Start here:** `docs/M0-Implementation-Notes.md` is the step-ordered playbook for this
milestone (durable store → wrapper → kill-and-resume gate), with the commit-ordering and
idempotency-key pitfalls called out.

## Project layout

```
src/cell/
  domain/objects.py     # wire schema: Ticket, Goal, WorkItem, Output, Verdict (Build-Spec §1)
  roles/contracts.py    # the five role Protocols (M2)
  roles/reference.py    # reference implementers of the operating roles (M2)
  flow.py               # run_flow — composes the role contracts + traces them (M2/M3)
  handbrake.py          # CellHandbrake — the five control primitives on the flow (M4)
  runtime/              # bind a real CLI coding agent to the Executor seat (sub-project B)
  live.py               # opt-in live real-slice runner (CELL_LIVE=1 python -m cell.live)
  cell.py               # Cell — composition root; wires every plane + the live governance gate
  demo.py               # runnable end-to-end demo of the §7 definition of done (python -m cell.demo)
  autonomy.py           # AutonomyBoard — Board-ratified ceiling amendments (M6)
  steward.py            # Steward — drift/loop/cost quarantine + rollback (M7)
  optimize.py           # Optimizer — capability/cost-aware implementer routing (M8)
  observe.py            # read-only run inspector over the durable event plane (python -m cell.observe)
  planes/
    memory.py           # event/memory plane — EventStore + Event/Checkpoint/Decision (M0)
    observability.py    # observability plane — TraceSpan + cost attribution (M3)
    governance.py       # action-class registry + RuleSetGovernance R1–R12 (M5)
    control.py          # the Handbrake Protocol — interface for M4 (impl in handbrake.py)
  effects/wrapper.py    # the idempotency wrapper — M0 CORE
tests/                  # one suite per milestone (M0–M7)
```

## Conventions

- **The docs are authoritative.** If code and a doc disagree, the doc wins — or amend the doc
  first (it is a living constitution; changes are tracked, per Build-Spec §5.4).
- **The assembled cell gates on the compiled rules.** `Cell.assemble()` wires `RuleSetGovernance`
  as the live R6 gate at the action site; `PermissiveGovernance` is a dev-only stub. The
  composition root (`cell/cell.py`) is the single seam where a real role-runtime binds.
- **Trace every claim to a clause.** Governance rules and gates cite a constitution Article;
  keep that traceability when you implement them (Build-Spec §5.4 validation/attestation).
- **YAGNI / invariant #8.** Do not build the Optimizer, the Auditor, a message broker, or a
  second cell. They are deferred until their precondition exists (Constitution Art. 3.4).
- **Tool-agnostic until it isn't.** Pick concrete tools per `Component-Selection.md`; keep them
  behind the interfaces so they stay swappable (invariant #1).

## How to run

```bash
pip install -e ".[dev]"
pytest            # structural tests pass; the two exactly-once tests xfail until perform() lands
```

## Build order after M0

M1 charter the Board & write the constitution (instantiate `docs/Cell-Constitution.md`) →
M2 role contracts → M3 observability → M4 handbrake on the one flow →
M5 compile governance (R1–R12) → M6 graduate autonomy → M7 minimal Steward.
See `docs/One-Cell-Build-Plan.md §6` (the authoritative milestone order).

> Note: adopting a durable-execution engine (checkpointer/replay) is a **tooling choice**
> that implements the M0 checkpointer and the M4 handbrake replay — not a milestone of its
> own. The M0 foundations already externalize state into the durable event store + ledger.
