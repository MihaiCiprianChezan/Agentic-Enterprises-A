---
Title: The Handbrake — Control-Plane Interface (M4)
Version: 0.1.0
Date: 27.06.2026
Status: Draft
Companion to: Agentic-First-Enterprises.md · One-Cell-Build-Plan.md · Cell-Constitution.md · Role-Contracts.md
---

# The Handbrake

This document instantiates milestone **M4**: the interface a human uses to pause, inspect, adjust, and resume any flow in the cell. It is the control plane — the model's architectural centerpiece (§6) — and it is a **structural property of every flow**, not a feature some flows happen to support (invariant #3).

It is specified **tool-agnostic**: as operations and guarantees, not a particular UI or transport. The same interface can surface as a CLI, a web approval page, or a message in an inbox; the build plan's only open question (the surface form) is deliberately left to the implementer. What is *not* optional is the set of operations and the guarantees behind them.

A human acting through the Handbrake **assumes a Role** and is bound by that Role's authority and the constitution (Constitution Art. 9) — never their human-Office authority. The Handbrake lets humans operate *within* policy; changing policy is a constitutional amendment, not a keyboard action.

---

## 1. The five primitives as operations

Each primitive (model §6) maps to one or more operations. An operation names its inputs, its effect, and the guarantee that makes it safe.

### 1.1 Breakpoint — *declare where a flow may pause*

| | |
|---|---|
| **Operations** | `set_breakpoint(flow, step, kind)` · `list_breakpoints(flow)` · `clear_breakpoint(...)` |
| **Kinds** | **static** — always pause here (mandatory before any L1/L0 action, Constitution Art. 5.2); **dynamic** — pause only when a condition holds (e.g. confidence < threshold, Art. 7.1). |
| **Who** | Static breakpoints are declared by the Orchestrator per the authority class of each Work item (Role-Contracts §2). A human may add an ad-hoc breakpoint to any flow at any time. |
| **Guarantee** | Every L1 and L0 action has a static breakpoint *before* it by construction; the system refuses to execute such an action without one. A flow that lacks a handbrake, or whose handbrake can be bypassed, is non-compliant and does not ship (invariant #3). |

### 1.2 Inspect — *read the paused state as a briefing, not a dump*

| | |
|---|---|
| **Operations** | `inspect(flow)` → returns a **takeover briefing** (§2 below). |
| **Effect** | Read-only. Returns recent activity, the exact decision point, what was decided and why, cost so far, and the pending action awaiting the human. |
| **Guarantee** | The briefing is legible: a human can understand what they are looking at without reading raw state (model §6.2). It is reconstructed from the durable event/decision trail, so it is the same whoever opens it. |

### 1.3 Inject — *supply a correction the flow will consume*

| | |
|---|---|
| **Operations** | `inject(flow, value)` where `value` is one of: an **edited output**, **missing context**, a **corrected decision**, or a **direct instruction** overriding the pending action. |
| **Effect** | The injected value is recorded as the resolution of the current decision point. It does **not** execute yet — it becomes the value `resume` will consume. |
| **Authority** | The injection is checked against the constitution exactly as an agent action would be (Constitution Art. 5.3, Art. 9). A human cannot inject an action the assumed Role is not authorized to take; that would require an amendment. |
| **Guarantee** | Injection is recorded in the audit trail as a **tracked variant** of the run, never an untracked change (model §5). When the human is the Board, Board-acts and Role-acts go to separate trails (Constitution Art. 10.2). |

### 1.4 Resume — *continue from the exact point, consuming the injection*

| | |
|---|---|
| **Operations** | `resume(flow)` |
| **Effect** | The flow continues **from the exact paused step**, consuming the injected value instead of re-deciding. It does not restart from the top. If no injection was made, it proceeds as the agent would have (e.g. a plain L1 approval). |
| **Guarantee** | Resume is exactly-once with respect to side effects: because every external action is idempotent (invariant #4; build plan §0), resuming never re-fires an effect that already happened, and never skips one that did not. This is the guarantee the whole Handbrake rests on. |

### 1.5 Replay — *reconstruct a past run to find the bad decision*

| | |
|---|---|
| **Operations** | `replay(flow_or_run, to_step?)` → steps through the recorded trajectory. |
| **Effect** | Read-only reconstruction ("time-travel debugging"): walk any past run step by step to locate where a decision went wrong. Side effects are **not** re-executed during replay. |
| **Guarantee** | Deterministic reconstruction from the durable trace; replay observes effects, never re-performs them. |

---

## 2. The takeover briefing (what `inspect` returns)

The briefing is the interface's most important payload — a clean handover depends on legible *reasoning*, not stored state (model §5). It contains:

1. **Where** — flow id, the Role being assumed, the exact step, and why it paused (which breakpoint / which escalation condition from Constitution Art. 7).
2. **The pending action** — what the agent is about to do, its authority class (L0–L3), and its blast radius.
3. **Recent decision trail** — the last N decisions: what was decided, why, and the alternatives considered — not just what changed.
4. **Cost so far** — against the Goal's budget cap (Constitution Art. 6).
5. **What's expected of the human** — the menu of valid moves here (approve / edit output / add context / correct decision / override / reject-and-escalate), each pre-checked against the assumed Role's authority so an out-of-policy move is not even offered.

---

## 3. The standard takeover sequence

```
flow hits a breakpoint  ──▶  flow CHECKPOINTS (durable, exact state)
        │
        ▼
   notify a human  ──▶  human calls inspect(flow)  ──▶  reads the takeover briefing
        │
        ▼
   human chooses a move ──┬── approve            ──▶ resume(flow)
                          ├── inject(edited output / context / correction / override) ──▶ resume(flow)
                          └── reject + escalate   ──▶ flow stays paused, routed up
        │
        ▼
   resume continues from the EXACT step, consuming the injection (no re-fire, no restart)
        │
        ▼
   human hands the Role back to the agent  (or stays in the seat for the duration)
```

Every step here is captured in the Observability and audit trails (Constitution Art. 10.1). A flow waiting on a human is a paused, checkpointed flow — not a running thread — so it can wait minutes or days at no cost (model §7).

---

## 4. Hard requirements (the interface is only as real as these)

From model §6, restated as build acceptance conditions:

1. **Durable checkpointer.** Exact state is persisted at every meaningful step, or pause/resume is impossible. (Provided by the memory plane, build plan §3.1.)
2. **Idempotent actions.** Every tool/side effect is safe to retry, or resume re-fires it. (Build plan §0, invariant #4.)
3. **Universality.** The Handbrake is present on **every** flow, callable by any authorized human at any time — not a special path. A flow that cannot be paused, inspected, adjusted, and resumed is non-compliant and does not ship.

**The governance gate is co-located with the handbrake.** Because every action passes through
the control plane, the compiled-rule check (R6, Build-Spec §5.3) is evaluated here, at the
action site, before an action pauses or executes: governance decides *may this class act at
all* (an L0 action is blocked outright), and the breakpoint enforces *the human approval an L1
action still needs*. Both decisions land on the durable, tamper-evident trail.

---

## 5. Acceptance test for M4

The Handbrake is done when, on the cell's real flow:

- A human can `inspect` at the pre-output (L1) breakpoint and receive a legible briefing — recent decisions with reasons, the pending action, cost, and a menu of valid moves.
- The human can `inject` a corrected output and `resume`, and the resumed run **uses the injection** rather than re-deciding.
- Killing the process mid-flow and restarting **resumes from the last checkpoint** and **does not duplicate** the external side effect (shared with build plan §7 item 3).
- An attempted injection that the assumed Role is not authorized to make is **refused** and logged, not silently executed (Constitution Art. 9).
- `replay` reconstructs a completed run step by step without re-performing its side effects.

Passing these exercises the two riskiest assumptions in the model on something real: durable resume with exactly-once side effects, and policy-bound human takeover.

---

## 6. Deliberately out of scope (MVP)

- **No surface-form commitment.** Whether this is a CLI, a web page, or an inbox is an implementation choice; the operations and guarantees above are what's fixed.
- **No high-throughput takeover.** The Handbrake guarantees a human can always *stop and inspect* any role; it does **not** guarantee a human can *run* a high-fan-out role at native throughput (model §7). The MVP flow is low-fan-out, so this does not bite — but it is not designed as if solved.
- **No multi-human concurrency model.** One human assumes one Role at a time in the MVP; contention resolution is deferred.
