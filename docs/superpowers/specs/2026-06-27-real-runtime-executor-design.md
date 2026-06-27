---
Title: Real-Runtime Executor (sub-project B) — Design Spec
Version: 0.1.0
Date: 27.06.2026
Status: Draft — awaiting review
Companion to: One-Cell-Build-Plan.md §7 · Component-Selection.md · Role-Contracts.md (Executor/Verifier)
---

# Real-Runtime Executor (sub-project B)

## 1. Purpose & context

Sub-project A proved the substrate composes on deterministic stubs and left a single seam:
`Cell.assemble(executor=…)`. Sub-project B binds a **real agentic runtime** into the Executor
seat to demonstrate the build-plan's §7 *real slice*: a ticket becomes a real code change,
which is verified by running real tests, and a **real pull request** is opened — with the
cell's M0 exactly-once guarantee proven on an actual irreversible side effect (never two PRs
across a kill/resume).

**Decisions carried from brainstorming:**
- **Runtime:** Claude Code CLI in headless mode (`claude -p`).
- **Target:** a fresh, minimal, disposable sandbox repo with one seeded failing test.
- **Realness:** a real PR is opened on the sandbox repo (the cell never merges — L0).
- **Approach 1 (faithful split):** the agent *produces the artifact*; the cell *performs the
  external effect* through `perform()`. The agent never touches git remotes.

**Overriding constraint — keep it thin.** No fat. The faithful design adds the *least*
possible code and **changes no existing component**: the `Cell`, `CellHandbrake`, planes, and
governance are used as-is. New code is a thin runtime adapter, a thin real verifier, a small
open-PR effect, and an opt-in live runner. Every adapter does exactly one thing.

**Out of scope:** changing any existing module; production deployment; multi-ticket queues;
agent-authored git/PR operations (that would violate invariant #4); putting the live LLM run
in CI.

## 2. The faithful split (why nothing fat is needed)

| Responsibility | Who | Effect kind |
|---|---|---|
| Produce the code change (edit files on a working branch) | `RealExecutor` via `claude -p` | the cell's own artifact (reversible) |
| Score it (run the sandbox tests) | `RealVerifier` via `pytest` | read-only |
| Open the PR (the handback) **on a pass** | the cell's `perform()`, called by the live runner | irreversible-ish, governed, idempotent |

The agent edits files and commits to a local branch; it does **not** push or open PRs. The
"open PR" is the one external effect, and it goes through `perform()` against a **durable**
`SqliteEffectsLedger`, so a crash between the `gh pr create` and recording completion cannot
open a second PR. This is M0's guarantee demonstrated on a real GitHub side effect.

Because delivery is just "`perform()` the open-PR effect after a pass verdict," it lives in the
opt-in live runner — **the `Cell` needs no new parameter or seam.**

## 3. Components (each thin, each one responsibility)

### 3.1 Sandbox target repo
A fresh minimal Python package pushed to the user's GitHub: a stub function + a failing
`pytest` test that fully specifies it (the "ticket": *implement `slugify()` so its test
passes*). Disposable; the demo's blast radius is one PR on this repo.

### 3.2 `Runner` Protocol + two implementers (`src/cell/runtime/runner.py`)
- `Runner` Protocol: `run(prompt: str, cwd: str) -> RunResult` (invariant #1 — the executor
  binds to this, not to a concrete CLI).
- `ClaudeCodeRunner` — shells out to `claude -p <prompt>` in `cwd` (headless), returns its
  result. Thin: build argv, run, capture stdout/exit.
- `FakeRunner` — deterministic; writes a canned change into `cwd` and returns success. For
  offline unit tests.

### 3.3 `RealExecutor` (`src/cell/runtime/real_executor.py`) — implements `Executor`
`execute(item) -> Output`, and only: (1) build a prompt from `item.description` +
`item.acceptance_criteria`; (2) `runner.run(prompt, checkout_dir)`; (3) `git add -A &&
git commit` on a working branch; (4) capture `git diff`/branch ref as `artifact_ref`; (5)
return an `Output`. No git remote, no PR. Depends on: a `Runner`, the target checkout dir, a
branch name.

### 3.4 `RealVerifier` (`src/cell/runtime/real_verifier.py`) — implements `Verifier`
`verify(output, goal) -> Verdict`: run `pytest` in the checkout; `pass` if green, `return`
(with the failure tail as the reason) if red. `verified_by` is the Verifier identity (distinct
from the Executor — R5). Thin: run tests, map exit code to a verdict.

### 3.5 Open-PR effect (`src/cell/runtime/deliver.py`)
A small function `open_pr_effect(intent) -> str`: push the branch and `gh pr create`, returning
the PR URL. Plus `deliver_on_pass(cell, flow_id, output, branch)`: build an `ActionDescriptor`
(`CLASS_VISIBLE_OUTPUT`, L2, `compensable`, `idempotency_key = make_idempotency_key(flow_id,
"open_pr", {branch})`) and call `perform(action, actor, open_pr_effect, cell.ledger,
cell.governance)`. Idempotent by construction.

### 3.6 Live runner (`src/cell/live.py`, `python -m cell.live`)
Opt-in, env-gated (`CELL_LIVE=1`). Assembles the cell with the real executor/verifier and
**durable** backends, submits the sandbox ticket, and on a pass verdict calls
`deliver_on_pass`. Prints the trace, the verdict, and the PR URL. **Not** in the test suite.

## 4. Data flow

```
ticket (sandbox) → RefDirector → Goal → RefOrchestrator → one WorkItem (CLASS_OWN_WRITE, L2)
  → RealExecutor (claude -p edits the branch) → Output(diff, branch)
  → RealVerifier (pytest) → Verdict
      pass  → live runner: perform(open-PR) [durable, idempotent] → PR URL → hand to human review
      return→ stop (the demo reports the failing tests)
```

Director and Orchestrator stay the **reference** implementers (the ticket body is the task;
one work item). No new role code beyond Executor + Verifier.

The work item is `CLASS_OWN_WRITE` (L2) — writing the change to a working branch the cell owns
(reversible), so the routine path runs without a breakpoint. The handbrake's existing
per-work-item `perform()` therefore stays a no-op over the cell's own artifact; the **one
meaningful external effect** is the delivery open-PR, performed separately on a pass. Nothing
about the handbrake changes.

## 5. Safety & cost envelope

- The nested `claude -p` runs **only** in the sandbox checkout, edits-only; bound by `cwd`.
- The cell opens a PR but **never merges** (merge is L0 / out of scope).
- Durable ledger ⇒ resume never opens a second PR.
- Real token cost per run (one nested Claude Code session) and one real PR per live run — hence
  the run is opt-in and env-gated, on a disposable repo.

## 6. Testing

- **Offline, deterministic, in the suite:** `RealExecutor` against `FakeRunner` (prompt built,
  diff captured, branch committed, Output shape); `RealVerifier` against a tiny temp repo with a
  passing and a failing test; `deliver_on_pass` against a fake effect (asserts idempotency —
  a second call with the same key does not re-open). No LLM, no network, no real `gh`.
- **Opt-in, manual, not in CI:** `CELL_LIVE=1 python -m cell.live` performs the real slice and
  opens a real PR. The README/docstring documents how to run it.

The full existing suite stays green, deterministic, and offline.

## 7. Files

- **New:** `src/cell/runtime/__init__.py`, `runner.py`, `real_executor.py`, `real_verifier.py`,
  `deliver.py`; `src/cell/live.py`; `tests/test_runtime.py`; a sandbox-repo scaffold (created +
  pushed to GitHub at implementation time, tracked separately from this repo).
- **Modified:** none of the existing `cell/*` or planes — only additive doc notes
  (Component-Selection's runtime-seam paragraph already names this; add a one-line pointer to
  `cell/live.py`).

## 8. Success criteria

1. `Cell.assemble(executor=RealExecutor(...), verifier=RealVerifier(...), store=Durable…,
   ledger=Sqlite…)` runs unchanged — the seam holds.
2. Offline suite (FakeRunner) is green and deterministic; full repo suite stays green.
3. `CELL_LIVE=1 python -m cell.live` produces a real PR on the sandbox repo from a real
   `claude -p` change, verified by real tests, and a re-run/resume opens **no** second PR.
4. No existing component was modified to achieve it (thin: adapters only).

## 9. Anti-fat guardrails (explicit)

- `RealExecutor`/`RealVerifier`/`Runner` each do one thing; no options, modes, or speculative
  config beyond what §3 lists.
- No new `Cell`/handbrake seam — delivery is `perform()`-on-pass in the live runner.
- No retry/queue/scheduler/parallelism. One ticket, one run.
- If a piece starts growing, that is the signal it is doing too much — split or cut, do not fatten.
