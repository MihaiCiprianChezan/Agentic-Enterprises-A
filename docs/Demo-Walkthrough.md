# Demo Walkthrough

`python -m cell.demo` runs five scenarios through an assembled `Cell` and prints each legibly — **no
LLM, no network, fully deterministic** (reference roles + in-memory planes). It's the fastest way to
*watch* the machine behave, including the paths a single happy run never shows: a human takeover, a
crash, a policy block, and a runaway. Read it alongside [`Anatomy-of-a-Run.md`](Anatomy-of-a-Run.md)
— each scenario below maps to that flow.

```bash
python -m cell.demo
```

---

## 1. Routine path — autonomous (L2, no human)

The happy path: the work item is a cell-owned write (`CLASS_OWN_WRITE`, **L2 → act-and-report**), so
the governance gate **allows** it and the flow runs end to end with no human in the loop — exactly
steps 0–5 of the Anatomy table.

```
verdict: pass
governance: allow
cost: 0.0 | steps: ['specify', 'decompose', 'execute', 'verify']
```

→ Director **specify** → Orchestrator **decompose** → Executor **execute** → Verifier **verify = pass**.
The four trace steps are the spine; governance `allow` is the R6 gate clearing an L2 action.

---

## 2. Dramatic path — handbrake takeover (L1)

Now the work item is an L1 action (e.g. an externally-visible comment). Art. 5.2 requires a **static
breakpoint before any L1/L0 action**, so the flow **pauses** and hands control to a human through the
handbrake. The human inspects a legible **briefing** (not a state dump), **injects** a corrected
output, and **resumes** — and the run completes.

```
paused at: pre-execute:wi-goal-t2 (static breakpoint before L1 action (Art. 5.2))
briefing: role=Executor moves=['approve', 'edit_output', 'add_context', 'reject_escalate']
resumed -> verdict: pass | used injection: branch://corrected
```

→ This is invariant #3 (**every flow has a handbrake**) and #9 (**a human who takes the seat is bound
by the Role's authority**, not their office). The injection is consumed at the exact paused step.

---

## 3. Kill-and-resume — exactly-once across a fresh controller

The §7 definition of done. The process is **killed mid-effect**, then a **brand-new controller** is
built on the same durable state and **resumes** — and the external effect ends up applied **exactly
once**, never twice.

```
effect executions across pause+restart+resume: 1 (exactly once)
```

→ This is the **effects wrapper** (M0, Anatomy step 4): invariant #4 (side effects safe to retry) on
invariant #5 (state lives in the event plane, not the actor's memory). Re-running a `flow_id` resumes
from the durable trail rather than re-firing.

---

## 4. Out-of-policy — an L0 action blocked, traced to a clause

The work item attempts an L0 action (`CLASS_HIGH_BLAST` — e.g. pushing to a protected branch). The
gate **blocks** it before any effect and **cites the constitution clause**: an L0 action is suggest-
only; the agent never executes it.

```
blocked: [R1 Art. 4] L0 action CLASS_HIGH_BLAST: the agent suggests, never executes (Art. 4);
         it requires a static breakpoint and a human (Art. 5.2)
audit: CLASS_HIGH_BLAST -> block | reason: [R1 Art. 4] L0 action CLASS_HIGH_BLAST …
```

→ The R6 gate (Anatomy step 2) doing its job: invariant #10 (**governance is compiled from the
constitution**; every allow/block traces to an Article). The block is on the audit trail.

---

## 5. Steward — an induced loop quarantined before the budget cap

A flow is induced to loop (the same work item executed over and over). The **Steward** — the
reliability system role — detects the runaway (R8) and **quarantines** the flow **before** it
breaches the budget cap, without losing the decision trail.

```
steward: quarantine (R8) | reason: loop: 6 execute attempts on one work item exceeds 3
cost at quarantine: 1400.0 (cap 10000)
```

→ This is a **system role** acting (the Anatomy "cast" band): non-authoritative, technical-only — it
pauses and rolls back a misbehaving flow, but never alters a business decision or a work product.

---

## What the five together prove

| Scenario | Path | The point |
|---|---|---|
| 1 Routine | gate **allows** (L2) → runs autonomously | the happy spine works end to end |
| 2 Handbrake | gate **pauses** (L1) → human inject + resume | every flow is interruptible (#3, #9) |
| 3 Kill-resume | crash mid-effect → exactly-once | durable, idempotent effects (#4, #5) — the §7 gate |
| 4 Block | gate **blocks** (L0) + cites a clause | governance compiled from the constitution (#10) |
| 5 Steward | runaway **quarantined** before the cap | the system roles keep the machine healthy |

For a *live* run with a real agent opening a real PR, see [`Using-a-Cell.md`](Using-a-Cell.md) §4 and
the worked example in [`Anatomy-of-a-Run.md`](Anatomy-of-a-Run.md) §6.
