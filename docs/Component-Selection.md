---
Title: Component Selection — From the Tool-Agnostic Spec to a Concrete Stack
Version: 0.1.0
Date: 27.06.2026
Status: Draft
Companion to: Build-Spec.md · One-Cell-Build-Plan.md
---

# Component Selection

The spec is deliberately tool-agnostic. This guide is where that ends: it maps each required *capability* to a shopping category, names representative options, and gives a recommended default for a first cell. **You do not need most of this to start.** M0 needs exactly two of these components; the rest can be chosen later, as their milestones arrive.

Tool names are examples as of writing and move fast — treat the **capability column** as the contract and the tools as interchangeable implementations that satisfy it. The recommended default in each row optimizes for "smallest thing that meets the guarantee for one cell," not for scale.

---

## What M0 actually needs (just these two)

| Spec requirement | Capability to shop for | Representative options | Default for one cell |
|---|---|---|---|
| **Event/memory plane** (Build-Spec §2) — durable, append-only, hash-chained, resumable state | An append-only, queryable, durable store you can content-hash | A single relational DB (Postgres/SQLite) with an append-only events table; a purpose-built event store; an embedded KV+log | **SQLite or Postgres, one `events` table.** For one cell this is plenty; the hash chain is application-level. Don't reach for Kafka/EventStoreDB yet. |
| **Idempotent-action wrapper** (Build-Spec §4) — exactly-once / at-most-once side effects across resume | Either a durable-execution engine that gives you this for free, *or* an explicit effects-ledger you implement | Durable-execution engine (Temporal, Restate, DBOS, Inngest); or a hand-rolled effects-ledger table keyed by idempotency key | **Hand-rolled effects ledger for the M0 spike** (proves the mechanic in ~100 lines), then **adopt a durable-execution engine** when you build the real flow, so you don't reinvent checkpointing. |

The M0 decision in one line: prove the wrapper against a plain SQLite events+effects table first; then decide whether a durable-execution engine replaces your hand-rolled checkpointer for M1+. Building the spike by hand first means you understand exactly what the engine is doing for you.

---

## The rest of the stack (choose as milestones arrive)

| Plane / need | Milestone | Capability to shop for | Representative options | Default |
|---|---|---|---|---|
| **Durable execution / checkpointer** | M1, M4 | Pause/resume a workflow from exact state; survive process death; deterministic replay | Temporal · Restate · DBOS · Inngest · LangGraph persistence | A **durable-execution engine** (Temporal-class). It directly provides Build-Spec §2.2 checkpoints + §4 retries + Handbrake replay — the single highest-leverage adoption. |
| **Observability + cost** | M3 | Session-level trace capture, per-step cost attribution, loop/anomaly signal | OpenTelemetry (GenAI semconv) as the wire format + a backend: Langfuse · Arize Phoenix · Braintrust · LangSmith | **OpenTelemetry + one backend.** Emit OTel spans (Build-Spec §3.1) so you are not locked to a vendor; pick the backend for the UI. |
| **Governance / policy engine** | M5 | Per-action rule evaluation before effect, with an audit log, rules as data | Open Policy Agent (Rego) · AWS Cedar · Oso · a small in-process rule evaluator | For **12 rules over 8 classes, a small in-process evaluator is enough** and keeps the rules hand-validatable (Build-Spec §5.4). Reach for OPA/Cedar only when the rule set outgrows hand-validation. |
| **Agent runtime** | M2 | Run the role implementations; tool calling; structured outputs | Any agent framework or a thin direct-SDK harness | Keep roles as **plain implementations behind the §contracts interfaces**; the framework is a detail bound to the contract, swappable (invariant #1). Don't let a framework dictate the architecture. |
| **Handbrake surface** | M4 | Pause notification + inspect/inject/resume operations for a human | CLI · a small web approval page · an inbox/queue | **CLI first** (lowest-friction, scriptable). The operations and guarantees are fixed (Handbrake §1); the surface is cosmetic and swappable. |
| **Software-delivery surface** | M0→M2 | Ticket source, repo access, sandboxed test/build, PR creation | Your existing issue tracker + git host + CI + a sandbox | Whatever you already use. The cell attaches at the **edges** (build plan §1): read tickets, open PRs, never merge to protected branches (L0). |

---

## Two stack archetypes

Because "pick concrete tools" eventually has to happen, here are two coherent end-states. Both satisfy every spec guarantee; pick the row that matches your operational comfort.

**A — Managed / batteries-included (fewer moving parts):**
Durable-execution engine for state+checkpoint+retry · its built-in event history as the memory plane · OpenTelemetry → Langfuse for traces · in-process rule evaluator for governance · CLI handbrake. Fewest components, fastest to a running M1.

**B — Composable / own-your-primitives (more control):**
Postgres event store (append-only, hash-chained) · application-level checkpointer · explicit effects ledger · OpenTelemetry → Phoenix · OPA for governance · web handbrake. More to wire, but every layer is independently inspectable and swappable — closer to the spec's "own the side you control" stance (invariant #4).

For a first cell, **A gets you to a running flow faster; B teaches you the guarantees.** The M0 spike (hand-rolled ledger) deliberately starts in B's spirit even if you later adopt A — because building the wrapper once by hand is how you learn what the engine is doing for you.

---

## Language note (for the scaffold)

The scaffold is **Python** — the default for agentic systems, with first-class SDKs for every category above (durable-execution engines, OTel, policy engines, agent frameworks). TypeScript is an equally valid alternative (Temporal, Restate, Inngest, and OTel all have strong TS SDKs); if your software-delivery cell lives in a TS codebase, mirror the same package structure there. The spec and contracts are language-neutral; only the scaffold commits.

---

## What you do NOT need yet (resist these)

- **A message broker / Kafka** — one cell's flows fit in a DB and a durable-execution engine. Add a broker only at federation scale.
- **A separate vector/RAG store** — not part of the model's core; add only if a role's task needs retrieval.
- **The Optimizer and Auditor infra** (version leaderboards, routers) — deferred until you run multiple versions (Constitution Art. 3.4).
- **Kubernetes / heavy orchestration** — a single process (or a managed engine) runs one cell. Scale the deployment when one cell is proven, not before (invariant #8).
