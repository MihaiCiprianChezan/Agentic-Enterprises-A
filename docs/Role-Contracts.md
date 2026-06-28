---
Title: Cell Role Contracts (M2)
Version: 0.1.0
Date: 27.06.2026
Status: Draft
Companion to: Agentic-First-Enterprises.md · One-Cell-Build-Plan.md · Cell-Constitution.md
---

# Role Contracts

This document instantiates milestone **M2** of the build plan: the explicit interface for each role the cell binds to. The system depends on these contracts, never on whether an agent or a human implements them (invariant #1). Each contract uses the model's standard shape (§2): responsibility, inputs, outputs, authority scope, acceptance criteria, escalation rule, observability hooks.

These are written **generically**, matching the constitution. The `«placeholders»` are the only workflow-specific parts. Seven contracts: four operating roles (Director, Orchestrator, Executor, Verifier) and three system roles (Steward; the Optimizer — instantiated at M8; and the Auditor — instantiated at M9b for **rate + report**, bound by Constitution Article 11). The Auditor's **suspend-and-escalate breaker** (M9c) is the only remaining piece — it acts on the Auditor's `dangerous` ratings.

All five share these **invariants** (do not repeat them per role):

- **Mode.** Agent by default; any role may be assumed by a human through the Handbrake at any time (Constitution Art. 3.3). A human in the seat is bound by the same authority scope and constitution as the agent (Art. 9).
- **State is external.** No role holds durable state in its own memory. Progress, decisions, and artifacts live in the memory/event plane so any implementer can take over mid-flow (invariant #5).
- **Governance is upstream.** Every action a role takes is checked against the compiled rules before it takes effect (Constitution Art. 5.3). A role never raises its own authority (Art. 4.1).
- **Everything is traced.** Every step, decision, tool call, and cost is emitted to the Observability plane (Art. 10.1).

The data objects passed between roles:

- **Ticket** — the raw intake from the downstream/legacy process.
- **Goal** — a specified unit of work: ticket + acceptance criteria + risk flags + constraints.
- **Work item** — a sequenced, assigned sub-task of a Goal, with its breakpoints declared.
- **Output** — the produced work product (the change/artifact) plus its trace.
- **Verdict** — Verification's pass / block / return decision with reasons.

---

## Contract 1 — Director *(Direction)*

| Field | Specification |
|---|---|
| **Responsibility** | Owns *what and why*. Converts an incoming Ticket into a well-specified Goal under the constitution. One Goal, clearly bounded, with acceptance criteria and any risk flags. |
| **Inputs** | A **Ticket** from the downstream/legacy intake. The constitution (purpose, boundary, authority ceilings). |
| **Outputs** | A **Goal** → to the Orchestrator: the outcome, explicit acceptance criteria, constraints, and a **risk flag** marking any part touching a higher authority class (L1/L0) or an unclassified action. |
| **Authority scope** | May accept, clarify, or **reject** a Ticket as out-of-purpose (Constitution Art. 1.3, 2.1). May set acceptance criteria. May **not** authorize any L0/L1 action itself, change priorities outside the constitution, or modify the constitution. |
| **Acceptance criteria** | The emitted Goal is in-purpose, has testable acceptance criteria, and every part that is irreversible/externally-visible/novel is flagged with its authority class. |
| **Escalation rule** | Escalates to a human when: the Ticket is ambiguous or out-of-distribution (Art. 7.2); it appears to fall outside the cell's purpose/boundary but the call is unclear; or specifying it would require authority the Director lacks (Art. 7.3). |
| **Observability hooks** | Emits: the received Ticket, the derived Goal, the acceptance criteria, every risk flag with its rationale, and any reject/escalate decision with reasons. |

## Contract 2 — Orchestrator *(Orchestration)*

| Field | Specification |
|---|---|
| **Responsibility** | Owns *who does what, and when*. Decomposes a Goal into sequenced Work items, assigns Executors, declares the breakpoints, and decides retry / escalate / proceed on exceptions. Does not do the work and does not set strategy. |
| **Inputs** | A **Goal** from the Director. The authority ceilings (Constitution Art. 4) and required gates (Art. 5). |
| **Outputs** | **Work items** → to Executors: each sequenced, with its declared **breakpoints** (static before any L1/L0 action per Art. 5.2; dynamic on low confidence per Art. 7.1). Exception and routing decisions. The assembled result → to Verification. |
| **Authority scope** | May sequence, assign, retry, and route. May decide to proceed or escalate on an exception. May **not** perform Execution work, approve outputs (that is Verification), exceed the Goal's authority envelope, or set strategy. Kept thin and restartable from state (build plan §2; model §14 supervisor-as-SPOF). |
| **Acceptance criteria** | Every Work item is assigned, sequenced with dependencies respected, and carries the correct breakpoints for its authority class. No high-blast action is left without a static breakpoint. The Orchestrator can be killed and restarted from checkpointed state without losing or duplicating work. |
| **Escalation rule** | Escalates when: an exception exceeds its retry policy or budget cap (Art. 6); a Work item's action class is unclassified (→ L0 by default, Art. 4); or a dependency cannot be satisfied within the Goal's envelope (Art. 7.3). |
| **Observability hooks** | Emits: the decomposition, every assignment and sequence decision, each declared breakpoint, every retry/escalate/proceed decision with reasons, and running cost against the budget cap. |

## Contract 3 — Executor *(Execution)*

| Field | Specification |
|---|---|
| **Responsibility** | Owns *how*. Produces the actual work product for a single Work item using its tools, within that item's authority class. Narrow, deep, replaceable. Knows its task and tools, not the global plan. |
| **Inputs** | One **Work item** with its acceptance criteria, authority class, and breakpoints. Read access to the inputs/artifacts the item needs. |
| **Outputs** | An **Output**: the produced change/artifact for that item, plus its full trace, handed back to the Orchestrator (and onward to Verification). May report `Output.cost` — what producing it cost (e.g. a runtime's token usage) — which the handbrake attributes onto the execute event (Build-Spec §3). |
| **Authority scope** | Acts **only within its Work item** and **only up to that item's authority class** (Constitution Art. 4): L3 for reversible/sandboxed/read actions; L2 for writes to cell-owned artifacts (act and report); pauses at the breakpoint for L1; produces a suggestion only for L0. Every external side effect is performed through the idempotent wrapper (invariant #4; build plan §0). May **not** act outside the item, escalate its own authority, or touch anything the item did not scope. |
| **Acceptance criteria** | The Output meets the Work item's stated acceptance criteria; no action exceeded the item's authority class; every side effect was idempotent (resume/retry did not duplicate it). |
| **Escalation rule** | Pauses and requests a human when: confidence falls below the item's threshold (Art. 7.1); the situation is out-of-distribution (Art. 7.2); or completing the item would require exceeding its authority class (Art. 7.3) — including hitting a novel/unclassified action (→ L0, Art. 4). |
| **Observability hooks** | Emits: every tool call and decision, the produced Output, cost for the item, and any pause/escalation with the triggering condition. |

## Contract 4 — Verifier *(Verification)*

| Field | Specification |
|---|---|
| **Responsibility** | Owns *is it correct and within policy*. Independently scores an Output against its acceptance criteria, quality, and conformance **before it takes effect**. The checker is never the producer (independence is the point). The single inline gate. |
| **Inputs** | An **Output** plus the Goal's acceptance criteria and the relevant constitution clauses (gates, boundary, authority). |
| **Outputs** | A **Verdict**: **pass** (output may be handed back to the downstream process), **return** (send back to Execution with specific reasons to revise), or **block** (a policy/boundary violation; stop and log). |
| **Authority scope** | May pass, return, or block an Output. Its block is binding — nothing proceeds past a failed gate (Constitution Art. 5.1). May **not** produce or edit the work itself, set acceptance criteria (the Director's job), or waive a constitution boundary. |
| **Acceptance criteria** | Every Output is scored against explicit criteria; the Verdict cites the specific criterion or clause behind a return/block; no Output reaches the downstream process without a pass. The Verifier runs independently of the Executor that produced the Output. |
| **Escalation rule** | Escalates to a human when: the Output is borderline against criteria and confidence is low (Art. 7.1); the criteria themselves appear ambiguous or insufficient (Art. 7.2); or it detects a policy boundary the compiled rules did not catch (Art. 7.4). |
| **Observability hooks** | Emits: the score against each acceptance criterion, the Verdict with its cited reason, and any escalation. Forms the produce → score → revise loop with Execution. |

## Contract 5 — Steward *(system role — no business authority)*

| Field | Specification |
|---|---|
| **Responsibility** | Owns *are the role-holders themselves healthy and behaving normally*. Watches the live roles for drift, hallucination, looping, runaway cost, and policy violation; quarantines a misbehaving flow and rolls it back to a known-good checkpoint. |
| **Inputs** | The Observability plane's traces and cost signals; loop/anomaly detection; budget-cap state (Constitution Art. 6). |
| **Outputs** | Health alerts; a **quarantine** action (pause a drifting flow) and a **rollback** to a known-good checkpoint; a flag for human takeover when needed. |
| **Authority scope** | Full **technical** capability over the operating roles — pause/quarantine, roll back, restart from checkpoint, retune, swap a misbehaving live instance for a known-good version. **Zero business-decision authority** (Constitution Art. 3.2): may **not** make or change any decision, priority, or strategy; approve work products or act in place of Verification; override the Governance plane; or **permanently replace the implementer** behind a Role (that is a Board decision, Constitution Art. 8). The Steward maintains instances; it does not retire them. |
| **Acceptance criteria** | A drift/loop/cost-spiral condition is detected and the flow is quarantined before it breaches the budget cap or causes harm (build plan M7); rollback restores a known-good checkpoint without losing the decision trail; no Steward action altered a business decision or a work product. |
| **Escalation rule** | Escalates to a human when: a quarantined flow cannot be safely restored from a checkpoint; drift recurs after rollback; or the condition is outside its technical remit (e.g. it looks like purpose drift, which is the Board's domain, not the Steward's). |
| **Observability hooks** | Emits: every health signal it acted on, each quarantine/rollback with the triggering condition and the checkpoint restored, and every human flag — to its own trail, distinct from the operating roles' trails. |

## Contract 6 — Optimizer *(system role — no business authority)*

Instantiated at **M8** now its precondition holds (cost is attributed and there is capability/cost spread across implementers; Constitution Art. 3.4). Sibling to the Steward: the Steward optimizes for reliability, the Optimizer for efficiency/capability-fit.

| Field | Specification |
|---|---|
| **Responsibility** | Owns *which implementer does each task*. Matches a Work item to the **minimum-capability implementer that still clears the task's risk/quality floor**, minimizing cost only *beneath* that floor. **Selection only** — capability-to-task matching, no business/priority decision (model §10/§4.6). |
| **Inputs** | The Work item and its `action_class`; the candidate implementers (capability tier + cost); the **attributed cost** per implementer from the Observability plane (nominal fallback at cold-start). |
| **Outputs** | A routing decision → the chosen implementer, recorded as an auditable `route` event (chosen id, the floor, the costs compared). The Orchestrator's assignment carries it to the worker. |
| **Authority scope** | **Zero business authority.** May only minimize cost *beneath* a floor it **does not set**: the risk→capability floor is **constitutional input** (`CAPABILITY_FLOOR`, governance registry), never an Optimizer judgment — a role that both classified risk and optimized against it could lower the floor to save cost. May **not** route a task below its floor, change priorities, or make strategy. |
| **Acceptance criteria** | The chosen implementer clears the task's capability floor; among those, cost is minimized using attributed cost; nothing clears the floor → escalates (never routes below). The decision is auditable and reused on resume/retry. |
| **Escalation rule** | No candidate clears the floor (`NoCapableImplementer`) → escalate to a human; the Optimizer never relaxes the floor to proceed. |
| **Placement (YAGNI)** | Inserted only where the cost/capability spread pays for the routing — engaged with ≥2 candidates; a uniform pipeline gets no router (model §10). |
| **Version status** | Routes only to `active` versions (the version registry, Build-Spec §2.4); a `rolled_back`/`suspended` version is never chosen — so the Auditor's suspension (M9) takes effect through the Optimizer. |

## Contract 7 — Auditor *(system role — no business authority)*

Instantiated at **M9b** (rate + report). Its object is the **version, as a population over time** — distinct from the Verifier (one output) and the Steward (one live instance). Bound by Constitution Article 11.

| Field | Specification |
|---|---|
| **Responsibility** | Owns *is this version getting better, worse, or dangerous*. Rates every version from accumulated field activity (`version_stats`) — quality, cost, regression-vs-predecessor — into a per-role **fitness leaderboard**; flags regressions and danger. **Audits, rates, reports** — does not operate, steward, or direct. |
| **Inputs** | The Observability plane: the per-version scorecard, the version registry, and safety signals (escalation / Steward quarantine / governance block). The governed `SUSPENSION_POLICY` (Art. 11). |
| **Outputs** | Durable **audit records** on the `__audit__` trail: a rating per version, a **regression alert** (for the Steward/Optimizer), and a **danger flag** (for humans / the 9c breaker). Signals, not actions. |
| **Authority scope** | **Zero authority over the world in 9b.** May **not** suspend, reinstate, modify/retune a version (that is the Steward), dismiss/retire one (Board), or make any business decision. **Danger is governed**, not improvised: only a **safety breach** (Art. 11) — never a mere quality regression — is rated `dangerous`. Suspension itself is the 9c breaker; reinstatement is never an agent's. |
| **Acceptance criteria** | Each version is rated faithfully to Art. 11 (danger = safety breach; collapse = `regressed`/alert-only); the leaderboard ranks by fitness; every rating/alert is on the audit trail; the Auditor changes no version status or work product. |
| **Escalation rule** | A `dangerous` rating is reported (danger flag) for the breaker/human; the Auditor itself takes no action on it in 9b. |

---

## Wiring (how the contracts compose)

```
Downstream intake ──Ticket──▶ DIRECTOR ──Goal──▶ ORCHESTRATOR ──Work items──▶ EXECUTOR ──Output──▶ VERIFIER
                                                       ▲                          │                   │
                                                       └─────── retry / return ───┘                   │
                                                                                                       │
                                              pass ──▶ hand back to downstream review/merge ◀──────────┘
                                              block ──▶ stop + log
STEWARD ── watches all live roles ──▶ quarantine / rollback (technical only, no business decisions)
HANDBRAKE ── any human may assume any Role at any breakpoint, bound by the same constitution
```

Every arrow is an asynchronous, durable handoff through the memory/event plane (build plan §3.1), not a blocking call — so a waiting human holds up only the work that genuinely depends on their output (model §7).

## What is intentionally absent

- **No Optimizer arrow.** Uniform low-stakes pipeline; no capability spread to route (Constitution Art. 3.4). When variance appears, the Optimizer slots between Orchestrator→Executor.
- **No Auditor.** One version per role in the MVP; nothing to compare. The version-registry field exists in the trace so the Auditor can be added without rewiring.
- **No Director-to-Director port.** One cell; federation is out of scope.
