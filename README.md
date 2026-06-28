# Agentic-Enterprises-A

One sovereign **cell** of the [Agent-Native Enterprise](docs/Agentic-First-Enterprises.md) model —
the smallest complete unit of the architecture, scoped around a software-delivery workflow:

> **intake a feature/bug request → produce a code change → verify it → hand the change back to
> the existing human review/merge process.**

It is **not** a federation; one cell first, by design. The cell runs operations at agent speed
under a human-authored **constitution** that compiles into runtime-enforced governance, and every
flow is interruptible through a structural **handbrake**.

> 📖 **New here? Read [Anatomy of a Run](docs/Anatomy-of-a-Run.md)** — one ticket → verified PR,
> role by role, with the real `observe` output of a live run. It's the fastest way to understand
> the whole machine.

## Status

The full one-cell build plan is implemented, reviewed, and merged — and **demonstrated live**: the
cell has driven a real CLI coding agent to take a ticket to a real pull request.

| Milestone | What it gives you |
|---|---|
| **M0** | durable, hash-chained event store + idempotent-action wrapper (exactly-once / at-most-once side effects across resume) |
| **M1** | the ratified one-page [constitution](docs/Cell-Constitution.md) |
| **M2** | the five role contracts (Director · Orchestrator · Executor · Verifier · Steward) + the flow that composes them |
| **M3** | observability — per-step trace + cost attribution |
| **M4** | the handbrake — breakpoint · inspect · inject · resume · replay |
| **M5** | governance compiled from the constitution (rules R1–R12, each tracing to a clause) |
| **M6** | autonomy graduation by Board-ratified amendment (never automatic) |
| **M7** | the Steward — drift/loop/cost quarantine + rollback |
| **M8** | the Optimizer — route each work item to the cheapest implementer that clears its constitutional capability floor, by attributed cost (auditable, recovered on resume) |
| **Versions** | first-class role versions — an event-sourced registry with status (active/rolled_back/suspended) + a per-version scorecard; the Optimizer never routes to a suspended version (the M9 Auditor precondition) |
| **M9** | the Auditor — Article 11 (suspension reserved for danger, 24h SLA), **rate + report** (per-role fitness leaderboard, regression/danger records), and the **suspend-and-escalate breaker** (`enforce`: suspend a dangerous version, rate-limited, 24h SLA → break-glass; never reinstates) |
| **Composition** | one assembled `Cell` that demonstrates the §7 definition of done on stubs |
| **Real runtime** | a real CLI coding agent (Claude Code by default) bound into the Executor seat |

## Install

Requires Python ≥ 3.11. No third-party runtime dependencies.

```bash
pip install -e ".[dev]"
```

## Run the tests

```bash
pytest            # the full deterministic, offline suite
```

## Watch it work (no LLM, no network)

The demo assembles a `Cell` and runs the five definition-of-done scenarios on deterministic
reference roles — routine autonomous, dramatic handbrake takeover, kill-and-resume exactly-once,
out-of-policy block, and a Steward loop quarantine:

```bash
python -m cell.demo
```

**[Demo-Walkthrough.md](docs/Demo-Walkthrough.md)** annotates each scenario's real output against the
flow — watch the happy path, a human takeover, a crash-and-resume, a policy block, and a quarantine.

## Use a cell in code

The cell is assembled at one composition root, `Cell.assemble(...)`. Everything is wired with sane
defaults (reference roles, in-memory planes, the live `RuleSetGovernance` gate, the Steward); pass
your own implementer to swap any role behind its contract (invariant #1):

```python
from datetime import datetime, timezone
from cell.cell import Cell
from cell.domain.objects import Ticket

cell = Cell.assemble()  # swap a role: Cell.assemble(executor=MyExecutor(), ...)
ticket = Ticket(id="t1", source="tracker", title="Add slugify()",
                body="Implement slugify() so its tests pass.",
                received_at=datetime.now(timezone.utc))

verdict = cell.submit(ticket, flow_id="t1")   # -> Verdict | Paused
```

If the flow hits a static breakpoint before an L1/L0 action it returns `Paused`; a human then
drives the handbrake and resumes:

```python
briefing = cell.inspect("t1")                 # a legible takeover briefing, not a state dump
cell.inject("t1", {"type": "edited_output",   # supply a correction (authority-checked, R11)
                   "output_id": "fix", "artifact_ref": "branch://fix"}, human_actor)
verdict = cell.resume("t1")                    # continues from the exact step, consuming the injection
cell.replay("t1")                              # read-only reconstruction of the run
cell.assess("t1", goal.budget_cap)             # the Steward's health check
```

## Run the real slice (a real agent → a real PR)

A real CLI coding agent can fill the Executor seat and open an actual pull request. This performs
real external actions (a real agent run, a real PR) and costs real tokens, so it is **opt-in and
never part of the test suite**. See the runbook: [`src/cell/runtime/README.md`](src/cell/runtime/README.md).

```bash
CELL_LIVE=1 \
  CELL_TARGET_DIR=/path/to/a/sandbox/checkout \
  CELL_TASK="Implement slugify() in slug.py so that test_slug.py passes." \
  python -m cell.live
```

Claude Code is the default runtime; Codex / Gemini / Pi ship as selectable presets behind the same
`Runner` seam (a CLI flag may need a tweak as those tools evolve).

## Observing a run

Every flow records its whole trajectory to the durable, hash-chained event plane, so a finished
run — manual, live, or a crash — can be read back after the fact to confirm the cell behaved:

```bash
python -m cell.observe <state_db> [flow_id]   # omit flow_id to list the flows in the DB
```

It prints a scannable timeline plus a verdict summary — the bottom line at a glance:

```
VERDICT: PASS
execute attempts: 1   ·   re-derivations: 1 (specify→decompose→govern)
governance: 1 allow · 0 block
effects: irreversible CLASS_VISIBLE_OUTPUT → https://github.com/…/pull/1  (exactly-once ✓)
total cost: 4096 tokens, 1300ms wall
chain: ✓ intact (tamper-evident)
```

Cost is **real** — every step records its measured wall-clock, and the execute step also carries the
runtime's reported token usage (claude). It reads the **durable event plane** (not the in-memory trace, which doesn't survive the process),
verifies the hash chain (tamper-evidence), and surfaces a tampered record loudly rather than
hiding it. `--full` dumps complete event payloads. See **[docs/Using-a-Cell.md](docs/Using-a-Cell.md)**.

## Read the design (the source of truth)

**New here? Start with [`docs/Anatomy-of-a-Run.md`](docs/Anatomy-of-a-Run.md)** — it walks one
ticket → verified PR, role by role, with the exact `observe` output of a real run.

The docs are authoritative — if code and a doc disagree, the doc wins (or the doc is amended first).

1. [`Agentic-First-Enterprises.md`](docs/Agentic-First-Enterprises.md) — the model; the 11 design invariants are non-negotiable.
2. [`One-Cell-Build-Plan.md`](docs/One-Cell-Build-Plan.md) — the build plan and milestone order (M0–M9; §6 lists the core M0–M7 sequence, with M8–M9 built past the MVP).
3. [`Cell-Constitution.md`](docs/Cell-Constitution.md) — the constitution this cell runs under (Articles 1–10).
4. [`Role-Contracts.md`](docs/Role-Contracts.md) — the five role interfaces.
5. [`Handbrake-Interface.md`](docs/Handbrake-Interface.md) — the control plane.
6. [`Build-Spec.md`](docs/Build-Spec.md) — schemas, the trace/cost rules, the idempotency contract, and governance rules R1–R12.
7. [`Component-Selection.md`](docs/Component-Selection.md) — capability → tool mapping; what's needed vs. deferred.

**Using & operating the cell:** [`Using-a-Cell.md`](docs/Using-a-Cell.md) — start-to-finish usage guide
(install → demo → assemble → drive → observe). **Milestone notes:** [`M0-Implementation-Notes.md`](docs/M0-Implementation-Notes.md)
— the step-ordered M0 playbook (durable store → wrapper → kill-and-resume gate).

`CLAUDE.md` is the orientation file for an agent picking up the repo.

## Deliberately not built yet (and that is correct)

Per the build plan and invariant #8 (add a tier only when its precondition exists):

- **A second cell · federation · the supra-constitution** — the only thing past M9 (M0–M9 are complete). The model
  defines the supra-constitution's *slot and precedence rule* (a cell enrolls by its own Board
  amendment); the federation layer itself is future work, meaningful only when there is more than
  one cell to coordinate.

## About

A reference implementation, built milestone by milestone (M0–M9 complete) and meant to be argued
with and corrected where it meets reality.
