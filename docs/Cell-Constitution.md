---
Title: Cell Constitution — Agentic-Enterprises-A (ratified instance)
Version: 1.0.0
Date: 27.06.2026
Status: Board-ratified (M1) · Living document
Companion to: Agentic-First-Enterprises.md · One-Cell-Build-Plan.md
---

# Cell Constitution

This is the source document this cell operates under. It is written in human language by the Board and is the text the Governance plane compiles into runtime-enforced rules (model §3, §17). It is deliberately short so the compiled rule set is small enough to validate by hand. Every enforced rule must trace back to a clause here.

This is the **ratified instance** for the `Agentic-Enterprises-A` cell, instantiated from the generic template at M1 by a Board of one. The cell-specific values (name, purpose, budget cap, Board rule) are filled in below; the rest is the template text, unchanged. Changing any of it is a Board amendment (Article 8), not an edit.

---

## Article 1 — Identity and purpose

- **1.1 Cell name.** Agentic-Enterprises-A
- **1.2 Purpose.** This cell exists to: intake a software feature or bug request, produce a verified code change on a branch, and hand it back to the existing human review/merge process — owning nothing beyond that slice.
- **1.3 The one workflow.** The cell owns exactly one slice of work, end to end: **intake → produce → verify → hand the result back to the existing downstream process.** It owns nothing outside this slice.

## Article 2 — Boundary (what the cell must never do)

- **2.1** It must not act outside the workflow named in 1.3.
- **2.2** It must not perform any irreversible, externally-binding, or production-affecting action on its own authority. Such actions are L0 (Article 4) and require a human, or lie outside the cell entirely.
- **2.3** It must not modify this constitution. Changes are Board amendments (Article 8). Agents never author their own rules.
- **2.4** It is sovereign at its boundary: nothing outside the cell reaches inside it except through this constitution or an authorized Role. The cell, in turn, treats everything outside it as untrusted external world.

## Article 3 — Roles

The cell binds to role **contracts**, not to whoever implements them. Each role declares: responsibility, inputs, outputs, authority scope, acceptance criteria, escalation rule, observability hooks.

- **3.1 Operating roles.** Direction (turns intake into a specified goal with acceptance criteria), Orchestration (sequences the work and sets breakpoints), Execution (produces the work product), Verification (independently scores the output before it takes effect).
- **3.2 System role.** Steward. Has full **technical** capability over the operating roles — pause/quarantine, roll back to a known-good checkpoint, restart, retune, and swap a misbehaving live instance for a known-good version — and **no** business-decision authority. It maintains live instances; it does **not** permanently replace the implementer behind a Role. Permanent removal or replacement is a Board decision (Art. 8).
- **3.3 Mode.** Every role runs as an agent by default and may be assumed by a human at any time through the Handbrake (impersonation on demand).
- **3.4 Deferred roles.** A role is instantiated only once its precondition exists (capability/cost spread; multiple running versions). The **Optimizer is now instantiated** (M8): its precondition — attributed cost and capability/cost spread across implementers — holds. It is bound by the risk→capability floor declared as constitutional content (`CAPABILITY_FLOOR`, Art. 4 / governance registry): it may minimize cost only *beneath* a floor it does not set, and may never route a task below it. The **version registry is now built** (Build-Spec §2.4): role versions are first-class, event-sourced, and carry a status (`active`/`rolled_back`/`suspended`); the Optimizer never routes to a non-active version, so **`suspended` is the Auditor's lever**. The **Auditor is now fully instantiated** (M9): the amendment the model §11 requires is enacted as **Article 11** (ratified 28.06.2026) — the danger-only suspension threshold, the rate-limited/non-cascading breaker, and the 24-hour human-response SLA — and the Auditor rates versions, reports regressions/danger, and holds the suspend-and-escalate breaker (`cell/auditor.py`), bound by Article 11. **No operating roles remain deferred; only federation (a second cell) is out of scope.**

## Article 4 — Authority ceilings (L0–L3)

Autonomy is assigned **per action class, not per role.** The same role may run at L3 for safe actions and L0 for dangerous ones. Levels: **L0** suggest only (human acts) · **L1** act with approval (pause at a breakpoint) · **L2** act and report · **L3** fully autonomous.

| Action class | Ceiling |
|---|---|
| Read inputs, state, and reference material | L3 |
| Run reversible, sandboxed work (tests, builds, dry-runs) | L3 |
| Write to artifacts the cell solely owns | L2 |
| Produce an output visible to teammates/downstream (proposal, draft, PR) | L2 |
| Communicate externally (a message no one can un-send) | L1 |
| Any action with high, shared, or hard-to-reverse blast radius | L0 |
| Anything production-affecting or externally binding | L0 / out of scope |
| **Any novel, unclassified action** | **L0 by default** + raise a classification proposal |

- **4.1** Levels start conservative and are raised only on observed evidence, and only by a Board-ratified amendment. No role raises its own authority.
- **4.2** Higher autonomy always implies stronger monitoring, never weaker.

## Article 5 — Required gates

- **5.1** Verification must pass before any output is handed to the downstream process. Verification is independent of Execution.
- **5.2** A breakpoint must pause the flow before any L1 action and before any L0 action (which then requires a human).
- **5.3** Every action is checked against the compiled rules **before** it takes effect; violations are blocked and logged.

## Article 6 — Budgets and limits

- **6.1 Per-goal ceiling.** No single goal may exceed 250,000 tokens of compute or 15 minutes of wall-clock without escalation.
- **6.2 Cost-spiral cutoff.** A flow that loops or exceeds its budget cap is quarantined by the Steward, not allowed to run on.
- **6.3** What counts as cost (compute, human time, opportunity cost) is compute + wall-clock.

## Article 7 — Escalation

A flow pauses and requests a human (impersonation on demand) when any of these fire:

- **7.1** Confidence falls below the threshold for the action's current autonomy level.
- **7.2** The situation is out-of-distribution: novel, ambiguous, or unspecified.
- **7.3** The action would exceed the role's authority scope.
- **7.4** The Governance plane flags a policy boundary, or the Steward detects drift and quarantines the role.

On escalation the flow checkpoints; a human assumes the Role's interface, acts or corrects, and either hands it back or stays for the duration. State lives in the memory plane, so takeover needs no special wiring.

## Article 8 — The Board and amendment

- **8.1 The Board.** The human accountability anchor. May be one person or many. Authors and owns this constitution; carries legal and representational accountability; runs a periodic check that the cell still serves its written purpose. The Board does not operate the cell turn by turn.
- **8.2 Decision rule.** This cell's Board is one person: Mihai-Ciprian Chezan (mikache82@gmail.com). Amendments require that person's sole approval. A Board of one needs no quorum, ratify threshold, or deadlock procedure beyond its own decision.
- **8.3 Amendment process.** Propose → ratify → re-compile the Governance plane → re-validate that every compiled rule still traces to a clause → log in the audit trail. Because governance is re-compiled from this text, a ratified amendment propagates to enforcement with no separate "update the agents" step.
- **8.4 Learning is human-codified.** The Observability plane and (later) the Auditor may surface patterns as *proposed* amendments. Only the Board turns a proposal into a rule.

## Article 9 — The impersonation-binding rule

A human who assumes a Role through the Handbrake **acts as that Role**: they inherit the Role's authority scope and are bound by this constitution exactly as the agent would be. They do **not** carry any human-Office authority into the seat. Doing something this constitution forbids is not a keyboard action — it is an amendment (Article 8).

## Article 10 — Record

- **10.1** Every action, decision, cost, and policy decision is captured in the Observability and audit trails.
- **10.2 Separation of record.** When one human plays both Board and a Role, Board-acts and Role-acts are logged to **separate** audit trails, so the two capacities stay distinguishable after the fact.
- **10.3** The state/event history is append-only and tamper-evident; a corrupted history must be detectable.

## Article 11 — Version audit and suspension

Added by Board amendment on 28.06.2026 (Art. 8.3), now that role versions are first-class and scored (Build-Spec §2.4) — the governed content the model (§11) requires **before** the Auditor switches on. **Now realized in code** (M9c): the Auditor's `enforce` breaker suspends only on danger, within these bounds.

- **11.1 Suspension is reserved for danger.** A version may be suspended only when its field activity shows a **safety breach** — it triggers governance blocks or escalations, or the Steward quarantines it (loop / cost-spiral / runaway). **Ordinary regression — including a catastrophic quality collapse — is alert-only** (rated down for the Optimizer, flagged to the Steward), never suspended: verification gates a low-quality version's outputs, so the harm the breaker exists to prevent does not arise.
- **11.2 Bounded breaker.** Suspensions are **rate-limited** and **non-cascading** — one suspension may not auto-trigger another. The bounds are governed content (`SUSPENSION_POLICY`, Build-Spec §5).
- **11.3 The Auditor cannot reinstate.** Pause is unilateral (safety); un-pause is not — only the Steward or a human resolves it. A suspended-but-critical version carries a **24-hour human-response SLA**; a missed SLA is a governed event that escalates up the Office ladder and, if still unanswered, onto the break-glass path.

> **Forward note (proposed, not enacted).** A future amendment may extend the danger threshold to also suspend on catastrophic quality collapse (pass rate below `collapse_alert_pass_rate` over `collapse_alert_min_runs`). Deferred — the model reserves suspension for harm, and a collapsed version's bad output is already gated by verification; revisit if gated waste proves costly.

---

### Ratification record (M1)

Instantiated from the generic template and ratified by the Board on 27.06.2026. The
cell-specific values:

- **Cell name (1.1)** — Agentic-Enterprises-A.
- **Purpose (1.2)** — intake → produce a verified code change → hand back to human review/merge.
- **Budget cap (6.1)** — 250,000 tokens of compute or 15 minutes of wall-clock per goal.
- **Cost basis (6.3)** — compute + wall-clock.
- **Board (8.2)** — a Board of one (Mihai-Ciprian Chezan), sole approval.

With these filled, the constitution is concrete enough to compile a tiny rule set against
(M5) and to build M2–M4 of the build plan. Every later enforced rule must trace to a clause
here (build-plan M1 acceptance). Subsequent changes are Board amendments (Article 8.3), not edits.

### Amendment record

- **Article 11 — Version audit and suspension** — added by Board amendment on 28.06.2026, ratified
  by the Board (Mihai-Ciprian Chezan, sole approval per 8.2) and recorded on the Board-acts trail
  (`AutonomyBoard.ratify_amendment`, Art. 8.3). Enacts the model §11 governed content — the
  danger-only suspension threshold, the rate-limited/non-cascading breaker, and the 24-hour
  human-response SLA — as the precondition for instantiating the Auditor (M9).
