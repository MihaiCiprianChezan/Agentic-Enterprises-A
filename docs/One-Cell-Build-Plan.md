---
Author: (build plan companion to "The Agent-Native Enterprise")
Version: 0.1.0
Date: 27.06.2026
Scope: One cell · Software-delivery workflow · Tool-agnostic
---

# Building the First Cell

**A concrete MVP build plan for a single sovereign cell, scoped around a software-delivery workflow, specified by required capabilities and guarantees rather than named tools.**

This is the companion build document to `Agentic-First-Enterprises.md` (referred to below as "the model"). It takes the model's own adoption sequence (§15) and YAGNI discipline (invariant #8) and turns them into a buildable plan for exactly one cell — not a federation. Federation, the supra-constitution, the Auditor, and the Optimizer are deliberately **out of scope** here and are only stubbed where a later seam is cheap to leave open.

The plan is **tool-agnostic by design**, matching the model's technology-neutral stance: every layer is specified as a set of *required capabilities and guarantees*. Any engine that satisfies the guarantee qualifies. Where a guarantee is the hard part, that is called out explicitly.

---

## 0. The one decision that governs everything: build the seams in, retrofit nothing

Three properties in the model are cheap if designed in from the first commit and ruinously expensive to retrofit. They are the spine of this plan:

1. **State lives outside the actor** (invariant #5). No durable state in agent memory, ever. This is what makes pause/resume and human takeover possible.
2. **The handbrake is structural, not a feature** (invariant #3). Every step in the one flow runs *through* a checkpoint-and-interrupt mechanism, even the steps that never pause. You are buying the option to pause, on every step, up front.
3. **Side-effecting actions are made as safe to retry as the effect allows** (invariant #4). Every external action the cell takes — a commit, a comment, a merge, a deploy trigger — is wrapped so that resume never silently re-fires it.

If these three are present, everything else in the model can be added incrementally. If any is missing, adding it later means a rewrite. Build them first.

---

## 1. The concrete first workflow

The cell owns one bounded slice of software delivery, end to end:

> **Intake a feature or bug request → produce a code change → verify it → hand the change back to the existing human review/merge process.**

This slice is chosen because it exercises every part of the model while staying small:

- It has a clear **intake** (an issue/ticket) and a clear **output** (a proposed change on a branch, with passing checks).
- It contains both **routine** actions (read a file, run tests, format code) and **high-blast-radius** ones (push to a shared branch, trigger CI, comment on a customer-visible issue) — so the L0–L3 authority model has something real to bite on.
- It has a natural **verification gate** (tests, lint, review criteria) independent of the producer.
- It ends at an **edge into the legacy organization** (human code review and merge), exactly the brownfield boundary the model describes (§16) — the cell never merges to the protected branch itself; it hands a reviewable change to the existing human process.

What the cell explicitly does **not** own in the MVP: deciding *which* features matter (that intent comes in as the ticket backlog), merging to production, releasing, and anything touching production data or infrastructure. Those stay L0 (human-only) or outside the cell entirely.

---

## 2. The cell's roles in the MVP

The model's full role set (§4) is collapsed to the minimum that still makes the flow legible. Roles are *contracts*, not separate systems — several can run on one underlying implementation with different permissions and prompts.

| Role | In MVP? | Owns | Notes |
|---|---|---|---|
| Direction (Director) | Yes — thin | Turns a ticket into a specified goal with acceptance criteria, under the constitution. | At one-cell scale this is a lightweight intake+spec step, not a CEO. |
| Orchestration (Orchestrator) | Yes — thin | Sequences the work, sets the breakpoints, decides retry/escalate/proceed. | Keep it thin (model §14: supervisor as SPOF) and restartable from state. |
| Execution (Executor) | Yes | Produces the actual code change with its tools (repo, editor, test runner). | The deep specialist. Knows its task, not the global plan. |
| Verification (Verifier) | Yes | Independently scores the change against acceptance criteria, tests, lint, policy. | Must be independent of the Executor. This is the only inline gate. |
| Steward | Minimal | Watches for drift/looping/runaway cost; can roll a flow back to a checkpoint. | Start as alerting + manual rollback; automate later. |
| Optimizer | **Deferred** | — | YAGNI (§10): a single uniform pipeline has no capability spread to route. Add only when model/cost variance appears. |
| Auditor | **Deferred** | — | YAGNI (§11): nothing to compare until you run multiple versions. Add when versions start flying. |
| Board | Yes — pattern | Writes/owns the constitution; the human accountability anchor. | Can be one person (the model's "Board of one", §3). Wears the hat part-time. |

The deferred roles are not designed out — the version registry stub (§4 below) leaves the Auditor's seam open, and the Optimizer slots between existing steps when needed.

---

## 3. Reference architecture: the four planes as capability requirements

Each plane is specified as guarantees. Pick any implementation that meets them.

### 3.1 Memory / context plane — *the most critical dependency, harden first*

Required capabilities:

- **Durable, external state for every flow.** Goal state, step-by-step progress, and produced artifacts persist outside any agent process and survive its restart.
- **Append-only event history** capturing not just *what changed* but *what was decided and why* — the decision trail (model §5). A human taking over must inherit the reasoning, not just the latest state.
- **Checkpoint at every meaningful step**, addressable for resume and for replay.
- **A version registry stub**: every agent version/variant is identifiable and activity is attributable to it. In the MVP this can be a single recorded version string per role — but the field exists from day one so the Auditor has something to read later.
- **Tamper-evidence.** The history must be detectable-if-corrupted (model §14 trust boundary). At minimum, content-addressed or hash-chained events.

Guarantee that is the hard part: *correctness and integrity of this store is the cell's single largest point of failure.* Make it redundant and verifiable before scaling any autonomy on top of it.

### 3.2 Observability plane

Required capabilities:

- **Full-trace capture** of every step, tool call, decision, output, and **cost** — session-level trajectories, not just log lines.
- **Per-session and per-role cost attribution** (tokens/compute/time), so budget caps and the cost-spiral guardrail (§14) have data.
- **Loop and anomaly detection** signals available to the Steward.

This plane is a prerequisite for *any* autonomy graduation (model §15 step 4: instrument before you scale autonomy). Build it before raising anything above L1.

### 3.3 Governance plane — *compiled constitution*

Required capabilities:

- **Machine-readable policy evaluated per action, before the action takes effect.** Authority ceilings, permission checks, required gates, budget caps — as data the agent reads at runtime, not prose a human reads later.
- **An append-only audit trail** of every policy decision (allow/block) and every privileged act.
- **A compilation + validation step** from the written constitution to the enforced rules, where *every encoded rule traces back to a constitution clause* and a human (or a Verifier-class check) attests the compiled set faithfully represents the text (model §17).

Guarantee that is the hard part: **the validation/attestation that compiled rules faithfully represent human intent.** This is the riskiest single element in the whole model. For the MVP, keep the constitution deliberately tiny (§6 below) so the compiled rule set is small enough to validate by hand. Do not attempt automated natural-language-to-policy compilation yet; write the rules directly and keep the human-readable clause they trace to next to each one.

### 3.4 Control plane — the Handbrake

Required capabilities, all five primitives from model §6, on the one flow:

1. **Breakpoints** — declared pause points, static (always pause before an irreversible/high-blast action) and dynamic (pause when confidence < threshold).
2. **State inspection** rendered as a *readable briefing* — recent activity + the exact decision point — not raw state (model §6.2).
3. **Injection** — the human supplies an edited output, missing context, or a corrected instruction that overrides what the agent was about to do.
4. **Resume** — continue from the exact paused point, consuming the injected value; never restart from the top.
5. **Replay** — reconstruct any past run step by step to locate a bad decision.

Hard requirements that make the handbrake real (model §6): a durable checkpointer (provided by 3.1) and idempotent actions (§0 point 3). Without both, resume re-fires side effects.

---

## 4. Authority classes for software-delivery actions (L0–L3)

Autonomy is assigned **per action class, not per role** (model §8). The same Executor runs at L3 for safe actions and L0 for dangerous ones. Starting assignments for this cell — every class starts conservative and is raised only on observed evidence, and only by a human (invariant #10):

| Action class | Start level | Rationale |
|---|---|---|
| Read repo / files / tickets | L3 — fully autonomous | No blast radius. |
| Run tests / lint / build in sandbox | L3 | Isolated, reversible. |
| Write to a working branch (the cell's own) | L2 — act and report | Reversible; the cell owns it. |
| Open/update a pull request | L2 | Reversible, but customer/teammate-visible — report it. |
| Comment on an externally visible issue | L1 — act with approval | Irreversible-ish (you can't un-send), human gate at first. |
| Push to a shared/protected branch | L0 — suggest only | High blast radius; never the cell's call in MVP. |
| Merge to main / trigger deploy | L0 / out of scope | Stays with the legacy human process (§1). |
| **Any novel, unclassified action** | **L0 by default** | Fail-safe: unclassified ⇒ highest risk class + raise a classification proposal (model §8). |

Risk classes are coarse and inherited by category (model §8) — this is a small governed set, not a per-action burden. Raising a level is a governance change surfaced by Observability and ratified by the human Board; performance earns a *proposal*, never an automatic promotion.

---

## 5. The minimal constitution for this cell

Keep it to a single short page so the compiled rule set is hand-validatable. It must declare, at minimum:

- **Purpose & boundary** — what slice this cell owns (the §1 workflow) and, explicitly, what it must never do (merge to main, touch production data/infra, act outside the repo).
- **Authority ceilings** — the L0–L3 table above, as the source the Governance plane compiles.
- **Required gates** — Verification must pass before any output is handed back; the breakpoint before any L1 action.
- **Budget caps** — per-goal ceilings on cost/compute/wall-clock; the loop/cost-spiral cutoff.
- **Escalation rule** — the conditions that pause the flow for a human (confidence below threshold, out-of-distribution, authority exceeded, governance flag — model §12).
- **The Board's own decision rule** — even for a Board of one, write down who ratifies amendments and how (model §3 self-referential closure).
- **Separation of record** — Board-acts and Role-acts (when the same human does both) log to separate audit trails (model §16 minimum safeguard).

The impersonation-binding rule (invariant #9) is in force from day one: a human who steps into a Role through the handbrake inherits *that Role's* authority and is bound by the same governance — not their human-Office authority. Changing what's allowed is a constitutional amendment, not a keyboard action.

---

## 6. Milestone sequence

Following the model's §15 order, compressed to one cell. Each milestone is usable before the next exists, and each has an acceptance test.

**M0 — Foundations (the three seams of §0).**
Stand up the durable state/event store (3.1) and wrap *one* external action (e.g. "open a PR") to be idempotent. Acceptance: kill the process mid-flow; restart; the flow resumes from its last checkpoint and does **not** duplicate the side effect.

**M1 — Charter the Board, write the constitution.**
One human wears the Board hat; write the one-page constitution (§5). Acceptance: every later enforced rule can point to a clause here.

**M2 — Roles as contracts.**
Write the explicit interface (responsibility, inputs, outputs, authority scope, acceptance criteria, escalation rule, observability hooks) for Director, Orchestrator, Executor, Verifier. Acceptance: the system binds to the contracts; you can swap an implementer behind any one without touching the others.

**M3 — Instrument everything (Observability).**
Full-trace + cost attribution on every step (3.2). Acceptance: you can replay a completed run and read its full decision/cost trace.

**M4 — The handbrake on the one flow.**
All five primitives (3.4) on the intake→change→verify flow. Acceptance: a human can pause at the pre-PR breakpoint, read a briefing, inject a corrected diff, and resume — and the resumed run uses the injection, not a re-decision.

**M5 — Compile governance from the constitution.**
Encode the L0–L3 ceilings, required gates, and budget caps as runtime-evaluated policy with an audit trail; hand-validate that each rule traces to a clause (3.3). Acceptance: an attempted L0 action (push to protected branch) is blocked and logged; the block traces to a constitution clause.

**M6 — Graduate autonomy.**
Start every class at the §4 levels. Raise exactly one class (e.g. "write to the cell's working branch" from L2 to L3 once trusted) only after Observability shows clean behavior, ratified by the Board. Acceptance: a promotion exists in the audit trail as a human-ratified amendment, not an automatic change.

**M7 — Add the Steward (minimal).**
Drift/loop/cost-runaway alerting + the ability to roll a flow back to a known-good checkpoint. Acceptance: an induced loop is detected and the flow is quarantined before it burns the budget cap.

**Deferred past the MVP (and that is correct):** Optimizer (M8, only when capability/cost spread appears), Auditor + real version registry (M9, only when multiple versions run), any second cell / federation / supra-constitution (only when one cell is proven).

---

## 7. Definition of done: what proves the cell works

The MVP earns its place when, on the real software-delivery slice:

1. The **routine path runs fully autonomously** end to end (model §18 routine case): ticket in, change produced, verified, handed to human review — no human in the loop, governance enforced silently as runtime checks.
2. The **dramatic path works on demand** (model §18 worked example): at the pre-PR/L1 breakpoint a human takes over via the handbrake, injects a correction, and resumes — bound by the same governance, with the takeover in its own audit trail.
3. **Kill-and-resume is safe**: process death mid-flow never duplicates an external side effect and never loses the decision trail.
4. **An out-of-policy action is blocked and traceable** to a written clause.

Hit those four and the two riskiest assumptions in the model — idempotency on real external effects (invariant #4) and faithful constitution→enforcement (§17) — have been tested on something real rather than asserted. That is the entire point of building one cell before a federation.

---

## 8. What this plan deliberately leaves for later

So the scope stays honest:

- **No federation, no Director-to-Director treaties, no supra-constitution** (model §16). One sovereign cell only. The Director-as-sole-port idea matters only when a second cell exists.
- **No automated constitution compiler.** Rules are written directly and hand-validated against a tiny constitution; automated NL→policy is the hard research-grade part and is not on the MVP critical path.
- **No high-throughput human takeover guarantee.** The model is honest that a human can always *stop and inspect* any role but cannot always *run* a high-fan-out role at native throughput (model §7). The MVP's flow is low-fan-out, so this doesn't bite yet — don't design as if it's solved.
- **No production authority.** Merge, release, and anything touching production data/infra stay L0 or outside the cell.

The model's closing note applies to this plan too: it is *a* starting point, meant to be argued with and corrected where it meets reality. Build M0–M2 first; they prove the spine, and everything else is incremental.
