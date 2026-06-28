---
Title: M0 Implementation Notes — first Claude Code session
Version: 0.1.0
Date: 27.06.2026
Status: Historical playbook — M0 (and M0–M9) are complete
Companion to: Build-Spec.md §2, §4 · One-Cell-Build-Plan.md M0 · CLAUDE.md
---

> **Note (historical):** M0 is done — the durable event store and idempotent wrapper are
> implemented and the exactly-once / kill-and-resume tests pass (no skips remain). In fact the whole
> plan (M0–M9) is complete; see [`README.md`](../README.md). This page is retained as the original
> step-ordered M0 playbook; references below to M0/M1 as "next" are historical.

# M0 Implementation Notes

A concrete first-session playbook for building M0 in Claude Code. This is **guidance**, not
code — the implementation is owned in the repo. M0 has two deliverables and one acceptance
gate. Do them in this order; each builds on the last.

## Goal of M0 (one sentence)

Make the cell's external effects survive process death: kill the process mid-effect, restart,
and the effect ends up applied **exactly once** (reversible) or **at-most-once** (irreversible)
— never twice. Everything else in the model rests on this.

## Step 1 — Durable EventStore (Build-Spec §2)

`cell/planes/memory.py` defines the `EventStore` Protocol and a correct `InMemoryEventStore`
reference. Implement a durable sibling that satisfies the **same** Protocol.

- One append-only `events` table: `(flow_id, seq, prev_hash, hash, kind, actor, payload, cost, at)`.
  Primary key `(flow_id, seq)`; `seq` gap-free and monotonic per flow.
- One `checkpoints` table for `Checkpoint` (Build-Spec §2.2).
- `append()` must be **atomic** — compute `prev_hash` from the current tail and insert in one
  transaction, or two processes can fork the chain. Use a transaction + a unique constraint on
  `(flow_id, seq)` so a racing append fails rather than duplicates.
- `verify_chain()` recomputes hashes (reuse `compute_hash`) — keep the tamper-evidence test green.
- SQLite is enough for one cell (Component-Selection.md). Postgres if you already run one.

Acceptance: the three structural tests still pass against the durable store, and a process
restart re-reads the full history.

## Step 2 — The idempotency wrapper (Build-Spec §4)

`cell/effects/wrapper.py::perform()` is the core. It currently raises `NotImplementedError`.
Implement the §4.2 protocol against a **durable** effects ledger (same DB as the event store):

1. **Pre-check governance** (rule R6) via the injected `GovernanceCheck`. For M0 the
   `PermissiveGovernance` stub allows everything — that's fine; M5 swaps in the real rules.
2. **Look up `idempotency_key`** in the ledger:
   - `completed` → return the stored result, **do not execute** (the exactly-once guarantee).
   - `in_flight` → for `idempotent`/`compensable`, re-attempt is safe; for `irreversible`,
     **do not re-attempt** — raise for human resolution (at-most-once).
   - absent → insert an `in_flight` row (commit it **before** executing), then execute.
3. On success, mark `completed` with the result digest and append an `action` Event.
4. On failure, mark `failed`; `idempotent`/`compensable` may retry, `irreversible` escalates.

The subtlety that *is* M0: the `in_flight` row must be committed **before** the side effect
fires, so that a crash between "effect happened" and "result recorded" is recoverable — on
restart you see `in_flight`, and the recovery rule (re-attempt vs. escalate) is decided by
`effect_kind`, never by guessing.

## Step 3 — The acceptance gate

Remove the two `skip` marks in `tests/test_m0_idempotency.py` and make them pass. Then add the
real kill-and-resume test (Build-Spec §7, build-plan §7 item 3):

- Run a flow that performs one effect through a **durable** ledger.
- Kill the process after the `in_flight` row is committed but before `completed`.
- Restart; resume the flow.
- Assert the effect is applied exactly once (reversible) / at-most-once (irreversible) — and a
  second full re-run never produces a duplicate.

A practical way to force the crash window: an `execute` callable that writes its effect, then
`os._exit(1)` before returning, driven by a subprocess so the test harness survives.

## Pitfalls (learned the expensive way)

- **Idempotency key determinism.** `make_idempotency_key` must be stable across restarts for
  "the same effect" — don't fold timestamps or random ids into it. The provided helper hashes
  `(flow_id, step, sorted intent)`; keep it that way.
- **Commit ordering.** `in_flight` before the effect; `completed` after. Reversing these
  reintroduces the double-fire M0 exists to prevent.
- **Don't make the outside world idempotent.** For genuinely irreversible outside effects you
  guarantee at-most-once *attempts* plus compensation where one exists — not exactly-once. The
  wrapper must never claim otherwise (invariant #4).
- **Keep the Protocol.** The durable store and ledger implement the existing interfaces; nothing
  downstream should know which backend is running (invariant #1).

## When M0 is done

Both exactly-once tests pass against durable backends, and the kill-and-resume test is green.
That retires the model's #1 riskiest assumption on something real. Next milestone: M1 — charter
the Board and instantiate the constitution (`Cell-Constitution.md`) → then M2 role contracts.
(Adopting a durable-execution engine for checkpointer/replay is an optional enhancement to these
M0 foundations, not a milestone of its own; it most directly serves the M4 handbrake's replay.)
See `One-Cell-Build-Plan.md §6`.
