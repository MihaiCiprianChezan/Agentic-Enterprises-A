# Using a Cell

A start-to-finish guide to running and operating one cell. Brief by design — for the *why*, read
the design docs linked from the [README](../README.md); this is the *how*.

A cell intakes a request, produces a code change, verifies it, and hands the change back to the
human review/merge process — under a compiled constitution, with a structural handbrake on every
flow. You can drive it three ways: the **demo** (no LLM), **in code** (your own roles/ticket), or
the **live slice** (a real CLI agent opening a real PR). Then you **observe** any run.

## 1. Install

Python ≥ 3.11, no third-party runtime dependencies.

```bash
pip install -e ".[dev]"
pytest                      # the full deterministic, offline suite should pass
```

## 2. Watch the demo (no LLM, no network)

The fastest way to see a whole cell work. It runs the five definition-of-done scenarios on
deterministic reference roles:

```bash
python -m cell.demo
```

You'll see a routine autonomous run, a handbrake takeover, a kill-and-resume that stays
exactly-once, an out-of-policy block, and a Steward loop quarantine.

## 3. Drive a cell in code

`Cell.assemble(...)` wires everything with sane defaults (reference roles, in-memory planes, the
live `RuleSetGovernance` gate, the Steward). Pass your own implementer to swap any role behind its
contract — the cell depends on the contract, not the implementer (invariant #1).

```python
from datetime import datetime, timezone
from cell.cell import Cell
from cell.domain.objects import Ticket

cell = Cell.assemble()                      # or Cell.assemble(executor=MyExecutor(), store=…)
ticket = Ticket(id="t1", source="tracker", title="Add slugify()",
                body="Implement slugify() so its tests pass.",
                received_at=datetime.now(timezone.utc))

verdict = cell.submit(ticket, flow_id="t1")  # -> Verdict | Paused
```

### Driving the handbrake

If a flow hits a static breakpoint before an L1/L0 action, `submit` returns `Paused`. A human then
takes over and resumes — bound by the Role's authority, not their human office (invariant #9):

```python
briefing = cell.inspect("t1")               # a legible takeover briefing, not a state dump
cell.inject("t1", {"type": "edited_output", # supply a correction (authority-checked, R11)
                   "output_id": "fix", "artifact_ref": "branch://fix"}, human_actor)
verdict = cell.resume("t1")                 # continue from the exact step, consuming the injection
cell.replay("t1")                           # read-only reconstruction of the run
cell.assess("t1", goal.budget_cap)          # the Steward's health check
```

### Durable backends

For state that survives the process, pass durable planes:

```python
from cell.planes.memory import DurableEventStore
from cell.effects.wrapper import SqliteEffectsLedger

cell = Cell.assemble(store=DurableEventStore("run.db"), ledger=SqliteEffectsLedger("run.db"))
```

## 4. Run the live slice (a real agent → a real PR)

A real CLI coding agent fills the Executor seat and opens an actual pull request. This performs
real external actions and costs real tokens, so it is **opt-in, env-gated, and never in the test
suite**. Full runbook: [`../src/cell/runtime/README.md`](../src/cell/runtime/README.md).

```bash
CELL_LIVE=1 \
  CELL_TARGET_DIR=/path/to/a/sandbox/checkout \
  CELL_TASK="Implement slugify() in slug.py so that test_slug.py passes." \
  python -m cell.live
```

The agent edits files on a working branch and commits; the cell verifies with real `pytest`; on a
pass the cell opens the PR through the idempotent effect wrapper (exactly-once — never two PRs
across a crash/resume). The cell **never merges** — handback to humans is the boundary.

## 5. Observe a run

Every flow records its whole trajectory to the durable, hash-chained event plane, so any finished
run can be read back afterwards — to confirm it behaved, or to debug one that didn't.

```bash
python -m cell.observe <state_db> [flow_id]    # omit flow_id to list the flows in the DB
python -m cell.observe run.db t1 --full        # --full also dumps every event payload
```

The live runner writes its state DB next to the target checkout (`<target>.cell-state.db`); an
in-code run writes wherever you pointed `DurableEventStore`. The inspector prints:

- a **header** — flow id, the actors involved, the time window, and whether the hash chain is intact;
- a **timeline** — one line per event (seq · kind · actor · the key fact · elapsed);
- a **verdict summary** — PASS/RETURN/BLOCKED/PAUSED, execute attempts, governance allow/block
  tally, each performed effect with its result (and exactly-once confirmation from the ledger), the
  total cost, and the chain-integrity verdict.

The **total cost is real**: every step records its measured wall-clock, and the execute step also
carries the runtime's reported token usage when it provides it (claude reports tokens via
`--output-format json`; other CLI presets report wall-clock only until a usage parser is added).

It reads the **durable event plane**, not the in-memory trace store (which doesn't survive the
process), and a tampered record is surfaced loudly (`chain: ✗ BROKEN at seq N`) rather than hidden.

Re-running a `flow_id` is safe — `cell.submit` on an existing flow **resumes** it (a completed flow
returns its recorded verdict and adds nothing; a crashed one continues from where it stopped without
duplicating its plan).

## Where to go next

- The authoritative design and the milestone order: the [README](../README.md) "Read the design" list.
- What's deliberately deferred (Optimizer, Auditor, federation, the supra-constitution): the
  README "Deliberately not built yet" section.
