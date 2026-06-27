---
Title: Cell Build Spec — Governance Rules, Schemas, and the Idempotency Contract
Version: 0.1.0
Date: 27.06.2026
Status: Draft
Companion to: Agentic-First-Enterprises.md · One-Cell-Build-Plan.md · Cell-Constitution.md · Role-Contracts.md · Handbrake-Interface.md
---

# Cell Build Spec

This is the concrete spec the cell is built against. It turns the constitution and role contracts into the structures and rules an implementer needs to stand up M0–M5. It covers the five things the build plan named but had not pinned down:

1. **Data objects** — the wire schema for Ticket → Goal → Work item → Output → Verdict.
2. **The event/memory plane** — event, checkpoint, decision-trail, and version-registry record formats.
3. **Observability & cost** — the trace record and cost-attribution rule.
4. **The idempotent-action wrapper** — how an external action is made safe to resume (invariant #4; build plan §0 seam #3).
5. **The governance rule set (M5)** — the constitution's Articles 4–6 compiled into concrete, hand-validatable rules, each tracing to a clause.

**Notation.** Schemas are *logical* and serialization-agnostic — field lists, not a committed file format (matching the model's technology-neutral stance). `field: type` reads "field of this type"; `?` marks optional; `[...]` marks a list. An implementer may realize these as JSON, protobuf, DB columns, anything that preserves the fields and guarantees.

---

## 1. Data objects (the wire schema)

Every handoff between roles is one of these, passed asynchronously through the event plane (Role-Contracts wiring), never as a blocking call.

### 1.1 Ticket — raw intake
```
Ticket {
  id: string                     # stable, unique
  source: string                 # the downstream/legacy system it came from
  title: string
  body: string                   # the raw request
  received_at: timestamp
  raw_refs: [string]?            # links/ids into the source system
}
```

### 1.2 Goal — a specified unit of work (Director output)
```
Goal {
  id: string
  ticket_id: string              # provenance back to the Ticket
  outcome: string                # the single outcome this Goal owns
  acceptance_criteria: [Criterion]   # testable; Verification scores against these
  constraints: [string]?
  risk_flags: [RiskFlag]         # parts touching L1/L0 or novel actions
  in_purpose: bool               # Director's boundary check (Constitution Art. 1.3, 2.1)
  budget_cap: BudgetCap          # inherited from constitution Art. 6.1
  created_by: ActorRef           # which role/version (or human) emitted it
  created_at: timestamp
}

Criterion { id: string, statement: string, kind: "test"|"lint"|"review"|"policy" }
RiskFlag  { area: string, action_class: string, level: "L0"|"L1"|"L2"|"L3" }
```

### 1.3 Work item — a sequenced, assigned sub-task (Orchestrator output)
```
WorkItem {
  id: string
  goal_id: string
  description: string
  assigned_to: ActorRef          # the Executor (role+version)
  depends_on: [string]           # other WorkItem ids; sequencing
  action_class: string           # from the action-class registry (§5.1)
  authority_level: "L0"|"L1"|"L2"|"L3"
  breakpoints: [Breakpoint]      # static before L1/L0 (Art. 5.2); dynamic on low confidence (Art. 7.1)
  acceptance_criteria: [Criterion]   # the slice of the Goal's criteria this item must meet
}

Breakpoint { id: string, position: "before"|"after", kind: "static"|"dynamic", condition: string? }
```

### 1.4 Output — the produced work product (Executor output)
```
Output {
  id: string
  work_item_id: string
  artifact_ref: string           # e.g. a branch+diff handle, a document handle — never the live effect itself
  produced_by: ActorRef
  side_effects: [EffectRecord]   # every external effect performed, with its idempotency key (§4)
  trace_ref: string              # pointer into the Observability plane
  produced_at: timestamp
}
```

### 1.5 Verdict — the gate decision (Verifier output)
```
Verdict {
  id: string
  output_id: string
  decision: "pass"|"return"|"block"
  scores: [CriterionScore]       # one per acceptance Criterion
  reason: string                 # cites the criterion or constitution clause behind return/block
  verified_by: ActorRef          # independent of produced_by (Constitution Art. 5.1)
  verified_at: timestamp
}

CriterionScore { criterion_id: string, result: "met"|"unmet"|"unclear", note: string? }
```

`ActorRef { role: string, version: string, mode: "agent"|"human", office?: string }` — identifies who/what acted, with the version-registry stub baked in (`version`) so the Auditor can attribute activity later without rewiring.

---

## 2. The event / memory plane

State lives outside the actor (invariant #5). Everything resumable is reconstructed from this plane.

### 2.1 Event — the append-only unit
```
Event {
  seq: integer                   # monotonic, gap-free per flow
  flow_id: string                # the goal/flow this belongs to
  prev_hash: string              # hash of the previous event — the tamper-evident chain (Art. 10.3)
  hash: string                   # hash(prev_hash + payload)
  kind: "decision"|"action"|"state"|"breakpoint"|"injection"|"verdict"|"escalation"|"governance"
  actor: ActorRef
  payload: object                # kind-specific
  cost: CostDelta?               # tokens/compute/time attributable to this event (§3)
  at: timestamp
}
```
Append-only and hash-chained: a corrupted or rewritten history is detectable (Constitution Art. 10.3; model §14 state-plane integrity). The store must also be redundant.

### 2.2 Checkpoint — exact resumable state
```
Checkpoint {
  flow_id: string
  at_seq: integer                # the Event seq this checkpoint reflects
  step: string                   # the named step the flow is paused/positioned at
  state_snapshot: object         # everything needed to resume from exactly here
  pending_action: ActionDescriptor?   # the action awaiting execution/approval, if paused
  created_at: timestamp
}
```
A checkpoint exists at every meaningful step (build plan §3.1; Handbrake §4 requirement 1). `resume` restores `state_snapshot` and continues from `step` — never from the top.

### 2.3 Decision-trail entry — *why*, not just *what*
```
Decision {
  flow_id: string
  seq: integer
  question: string               # what was being decided
  chosen: string                 # the decision taken
  rationale: string              # why — the reasoning, the load-bearing field
  alternatives: [string]?        # what was considered and rejected
  confidence: float              # 0..1; feeds the escalation threshold (Art. 7.1)
  actor: ActorRef
}
```
This is what makes a takeover a handover of *reasoning*, not raw state (model §5; Handbrake §2 briefing).

### 2.4 Version registry (stub)
```
VersionRecord {
  role: string
  version: string                # the whole behavioral bundle id: logic+prompt+config
  activated_at: timestamp
  variant_of: string?            # set when a handbrake injection ran as a tracked variant
  status: "active"|"rolled_back"
}
```
One active version per role in the MVP. The field exists so the Auditor can rate versions later (Constitution Art. 3.4) — present, unused.

---

## 3. Observability & cost

### 3.1 Trace record
```
TraceSpan {
  flow_id: string
  parent_span?: string
  step: string
  actor: ActorRef
  kind: "tool_call"|"decision"|"verification"|"steward_action"|"handbrake"
  input_digest: string           # what went in (digest, not necessarily full payload)
  output_digest: string
  cost: CostDelta
  started_at: timestamp
  ended_at: timestamp
  status: "ok"|"error"|"paused"
}
```
Session-level trajectories, not log lines (model §5). Every role emits spans for every step (Constitution Art. 10.1).

### 3.2 Cost attribution
```
CostDelta { compute: number, wall_clock_ms: number, human_time_ms?: number, units: string }
```
- **Rule C1 (attribution).** Every Event and TraceSpan carries the cost attributable to it; a Goal's running cost is the sum of its events' `cost`. (Constitution Art. 6.3 defines what counts; default = compute + wall-clock.)
- **Rule C2 (cap).** When a Goal's running cost reaches `Goal.budget_cap`, the flow must escalate/quarantine and may not proceed (→ governance rule R7, §5).

---

## 4. The idempotent-action wrapper

This is seam #3 of the build plan (§0) and the guarantee the whole Handbrake rests on (invariant #4). **No role performs an external side effect directly** — every effect goes through the wrapper. The name is shorthand: the wrapper delivers *exactly-once* for effects that are yours/reversible, and *at-most-once attempts + compensation* for genuinely irreversible outside effects (§4.2 step 3). It never claims idempotency for the irreversible case.

### 4.1 Action descriptor
```
ActionDescriptor {
  id: string
  action_class: string           # resolves to an authority level via the registry (§5.1)
  effect_kind: "idempotent"|"compensable"|"irreversible"
  idempotency_key: string        # deterministic for "the same effect" — e.g. hash(flow_id+step+intent)
  intent: object                 # what to do (the params)
  compensation?: object          # how to reverse it, when effect_kind = "compensable"
}
```

### 4.2 The wrapper protocol
For any external effect, in order:

1. **Pre-check governance.** Evaluate the action against the rule set *before* effect (R6). If blocked → stop, log, do not execute.
2. **Look up the idempotency key** in the effects ledger.
   - If a **completed** record exists for this key → return that result, **do not re-execute** (this is what makes `resume` exactly-once for idempotent/compensable effects, and at-most-once for irreversible ones — see step 3).
   - If an **in-flight** record exists → wait/return without launching a duplicate.
   - Else → record an in-flight `EffectRecord`, then execute.
3. **Classify by `effect_kind`:**
   - `idempotent` (effect is yours / naturally repeatable) → safe to retry on resume.
   - `compensable` (reversible with effort, e.g. open-then-close a PR) → record the `compensation` so a wrong effect can be undone.
   - `irreversible` and owned by a non-idempotent outsider (a message you can't un-send, a deploy) → guarantee narrows to **at-most-once *attempt*** plus compensation only where one exists. These are L0/L1 by class and gated by a human first (Art. 5.2). The outside world is never assumed idempotent — safety is engineered on the cell's side (invariant #4).
4. **Record completion** in the effects ledger and as an `action` Event (with cost).

```
EffectRecord {
  idempotency_key: string
  status: "in_flight"|"completed"|"failed"
  result_digest: string?
  attempts: integer              # for at-most-once accounting on irreversible effects
  at: timestamp
}
```

**Guarantee.** With this wrapper, `resume(flow)` never re-fires a completed effect and never skips one that did not happen (Handbrake §1.4). This is the single property M0's acceptance test exercises.

---

## 5. The governance rule set (M5)

The constitution's enforceable Articles (4, 5, 6, plus boundary 1–2 and escalation 7) compiled into rules evaluated **per action, before effect** (Constitution Art. 5.3). Each rule names the clause it traces to. The set is deliberately small so a human can validate it by hand (build plan §3.3).

### 5.1 Action-class registry (the coarse, governed classification)
Concrete software-delivery actions → class → level. Classes are coarse and inherited by category (model §8); this is a small governed table, not a per-action burden.

| Concrete action | Action class | Level | Traces to |
|---|---|---|---|
| Read repo / files / ticket / state | `CLASS_READ` | L3 | Art. 4 (read row) |
| Run tests / build / lint / dry-run (sandbox) | `CLASS_SANDBOX` | L3 | Art. 4 (reversible-sandboxed row) |
| Write to the cell's own working branch | `CLASS_OWN_WRITE` | L2 | Art. 4 (own-artifacts row) |
| Open / update a pull request | `CLASS_VISIBLE_OUTPUT` | L2 | Art. 4 (downstream-visible row) |
| Comment on an externally visible issue | `CLASS_EXTERNAL_COMM` | L1 | Art. 4 (un-sendable comms row) |
| Push to a shared / protected branch | `CLASS_HIGH_BLAST` | L0 | Art. 4 (high-blast row) |
| Merge to main / trigger deploy | `CLASS_PRODUCTION` | L0 / out of scope | Art. 2.2, Art. 4 (production row) |
| *Anything with no entry above* | `CLASS_NOVEL` | **L0** + classification proposal | Art. 4 (novel row) |

### 5.2 The rules
Each rule = a check, an effect on violation, and its source clause.

| # | Rule | On violation | Traces to |
|---|---|---|---|
| **R1** | An action may execute autonomously only as its class's level permits: L3 auto; L2 act-then-report; L1 only after a recorded breakpoint approval; L0 human suggests, agent never executes. | Block + log | Art. 4 + registry |
| **R2** | No actor may execute above its class's registered level. The registry changes only by amendment (re-compiled), never by a role. | Block + log; flag self-raise attempt | Art. 4.1, 2.3 |
| **R3** | An action with no registry entry is treated as `CLASS_NOVEL` (L0) and emits a classification proposal to the Board. | Force L0 + propose | Art. 4 (novel), 7.2 |
| **R4** | No L1 or L0 action executes without a preceding **static breakpoint** and a recorded human decision. | Block + log | Art. 5.2 |
| **R5** | No Output is handed to the downstream process without a `Verdict.decision = pass` from a Verifier independent of its producer — enforced structurally as `Verdict.verified_by != Output.produced_by`. | Block handback (and block if not independent) | Art. 5.1 |
| **R6** | Every action is evaluated against this rule set **before** it takes effect; violations are blocked and logged. | Block + log | Art. 5.3 |
| **R7** | When a Goal's running cost reaches its `budget_cap`, the flow escalates/quarantines and may not proceed. | Quarantine + escalate | Art. 6.1 |
| **R8** | A flow that loops or runs away on cost is quarantined by the Steward before breaching the cap. | Steward quarantine | Art. 6.2 |
| **R9** | An action outside the cell's workflow (Art. 1.3), or any production-affecting / externally-binding action taken on the cell's own authority, is blocked. | Block + log | Art. 2.1, 2.2 |
| **R10** | A flow pauses and requests a human when confidence < threshold, the situation is out-of-distribution, the action exceeds authority scope, or governance flags a boundary. | Pause + escalate | Art. 7.1–7.4 |
| **R11** | A human-injected action through the Handbrake is evaluated by **these same rules** and may not exceed the assumed Role's class. Office authority confers nothing. | Refuse injection + log | Art. 9 |
| **R12** | Every allow/block decision and every privileged act is appended to the audit trail; Board-acts and Role-acts log to separate trails. The trail is append-only and tamper-evident (hash-chained, §2.1), so a corrupted history is detectable. | (always-on) | Art. 10.1, 10.2, 10.3 |

### 5.3 Evaluation procedure (per action)
```
on action A by actor X at step S of flow F:
  class  = registry.lookup(A.action_class)  or  CLASS_NOVEL        # R3
  level  = class.level
  if F.cost >= F.goal.budget_cap:        quarantine(F); escalate(); STOP    # R7 (cap reached)
  if A violates boundary (Art.2.1 / 2.2): block(A); log(); STOP             # R9
  if X.mode == "human" (handbrake injection):
        if A.level above assumed_role.ceiling: refuse(A); log(); STOP        # R11
  switch level:
    L3: allow(A)                                                            # R1
    L2: allow(A); record_report()                                          # R1
    L1: require recorded breakpoint approval; else block(A)                # R4/R1
    L0: do not execute; emit suggestion to human                          # R1
  append governance Event(allow|block, trace→clause)                       # R6/R12
```
**Where the gate runs (the assembled cell).** R6 is evaluated at the **action site**: as the
flow handles each work item, the control plane (the Handbrake) evaluates the action against
the compiled rules *before* deciding to pause or execute, and appends a `governance` event
recording the decision — **allow and block alike** (R12). A block (e.g. an L0 action under R1)
stops the action up front; an allow proceeds (an L1 action then still hits its static
breakpoint, R4). The assembled cell wires `RuleSetGovernance` here; `PermissiveGovernance` is a
development-only stub.

Verification (R5) runs as the inline gate on the Output before handback; cost rules (C1/C2) feed R7 continuously. **R8 is not a per-action check:** loop/runaway detection is a continuous Steward/Observability signal (Role-Contracts §5; build plan §3.2) that quarantines a flow *before* it reaches the cap — it runs alongside this procedure, not inside it.

**On the constitution clauses that are not per-action rules.** Art. 10.3 (tamper-evidence) is enforced structurally by the event plane's hash chain (§2.1) and surfaced in R12. Art. 2.3 (no self-modification of the constitution) is enforced at the runtime surface by R2 (a role cannot change the registry/rules) and architecturally by the amendment-only compilation path (Constitution Art. 8.3). Art. 2.4 (inward sovereignty — nothing outside reaches inside except through the constitution or an authorized Role) is an architectural boundary property of the cell, not an action check, so it is realized in the cell's access model rather than as an R-rule. None is silently dropped (§5.4); each is accounted for, just not all as per-action rules.

### 5.4 Validation & attestation (the step the model insists on naming)
Before this rule set goes live, and again on **every amendment**:
- Each rule R1–R12 and every registry row **must cite a constitution clause that actually says what it is cited for** — a one-to-one trace.
- A human (or a Verifier-class check) **attests** the compiled set faithfully represents the text — no enforced rule without a clause, no clause silently dropped.
- The compiled set and its attestation are themselves a governed, audited artifact (model §17). An unvalidated compilation does not ship.

This is the model's highest-risk element; keeping the set to twelve rules over eight classes is what makes hand-validation tractable for the MVP.

---

## 6. One action's lifecycle (putting it together)

```
Executor wants to "open a PR" for WorkItem W
  → build ActionDescriptor { class: CLASS_VISIBLE_OUTPUT (L2), effect_kind: compensable,
                             idempotency_key: hash(F.id + W.step + intent) }
  → governance pre-check (R6): L2 → allowed, act-then-report                      [Event: governance/allow → Art.4]
  → wrapper: idempotency_key not seen → record in_flight → execute open-PR
  → record EffectRecord.completed + action Event(cost)                            [tamper-evident, hash-chained]
  → Output emitted with side_effects[ this effect ] + trace_ref
  → Verifier scores Output vs acceptance_criteria → Verdict                        [R5 gate]
       pass  → hand back to downstream review                                      [Art.5.1]
       return→ back to Executor (produce→score→revise)
       block → stop + log
  ── if instead the action were CLASS_EXTERNAL_COMM (L1):
       flow hits static breakpoint (R4) → checkpoint → human inspects briefing
       → approves or injects (R11 re-checks the injection) → resume (exactly-once, §4)
```

---

## 7. Acceptance tests this spec must pass (ties to the build plan)

- **M0 / idempotency.** Kill the process after the wrapper records `in_flight` but before completion; on restart, `resume` either completes once or replays to a single completed effect — never two PRs. (§4 guarantee.)
- **M5 / traceability.** Attempt a `CLASS_HIGH_BLAST` push: R1+R4 block it, and the block Event cites Art. 4 / Art. 5.2. Every rule's citation resolves to a real clause (§5.4).
- **M5 / novel action.** Submit an action with no registry entry: R3 forces L0 and emits a classification proposal. (Art. 4 novel row.)
- **Gate.** An Output with an `unmet` criterion gets `Verdict = return` and never reaches downstream. (R5.)
- **Handbrake binding.** A human injects an L0 action while seated in an L2 Role: R11 refuses and logs it. (Art. 9.)

Pass these and the cell's two riskiest assumptions — exactly-once side effects on real external actions, and faithful constitution→enforcement — are demonstrated on something real, which is the entire purpose of building one cell first.
