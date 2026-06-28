---
Title: M9a — Constitutional Amendment for Version Suspension — Design Spec
Version: 0.1.0
Date: 28.06.2026
Status: Draft — design approved, awaiting spec review
Companion to: Agentic-First-Enterprises §11 (Auditor) · Cell-Constitution Art 3.4, 8 · M6 AutonomyBoard
---

# M9a — Constitutional Amendment for Version Suspension

## 1. Purpose & context

The Auditor (M9) may not switch on until the constitution declares the governed content the model
§11 requires: a **suspension threshold** (reserved for danger) and a **human-response SLA** for any
suspended-but-critical version. This sub-project enacts that amendment — the prerequisite gate. It
adds **no Auditor logic** (rating, alerting, suspension *mechanism* are 9b/9c); it declares the
governed values and records the Board's ratification, present-but-unread, exactly as the version
registry sat before the Optimizer.

**Decisions carried from brainstorming (the Board set these — Art 8.2, Board of one):**
- **Danger = a safety breach only** (aligned to §11): a version is dangerous when its field activity
  shows governance blocks / escalations, or the Steward quarantines it (loop / cost-spiral /
  runaway). **Catastrophic quality collapse is alert-only**, not suspension — the Verifier already
  gates a low-quality version's bad outputs, so it is regression, not harm (§11: "ordinary
  regressions are alert-only").
- **Human-response SLA = 24 hours** for a suspended-but-critical version; a missed SLA escalates
  (notify Board → break-glass, model §17).
- **Rate-limited, non-cascading** breaker (governed bounds).
- **Forward-note** (recorded, not enacted): a contemplated future amendment to also suspend on
  catastrophic collapse — deferred per the harm-only reservation.

**Out of scope (9b/9c):** the Auditor itself; rating versions; emitting alerts; the suspend
mechanism; SLA-timer enforcement. 9a is governed *content* + its ratification *record* only.

## 2. The amendment (Cell-Constitution.md)

A new **Article 11 — Version audit & suspension**, placed after Article 10, plus an **amendment
record** beside the M1 ratification (Art 8.3: log the amendment). Article 11 declares:

- **11.1 Suspension is reserved for danger.** A version may be suspended only when its field activity
  shows a **safety breach** — it triggers governance blocks or escalations, or the Steward
  quarantines it (loop / cost-spiral / runaway). **Ordinary regression — including a catastrophic
  quality collapse — is alert-only** (rated down for the Optimizer, flagged to the Steward), never
  suspended: verification gates a low-quality version's outputs, so the harm the breaker exists to
  prevent does not arise.
- **11.2 Bounded breaker.** Suspensions are **rate-limited** and **non-cascading** — one suspension
  may not auto-trigger another (governed bounds in `SUSPENSION_POLICY`).
- **11.3 The Auditor cannot reinstate.** Pause is unilateral (safety); un-pause is not. A
  suspended-but-critical version carries a **24-hour human-response SLA**; a missed SLA is a governed
  event that escalates up the Office ladder and, if still unanswered, onto the break-glass path (§17).
- **Forward note (proposed, not enacted):** a future amendment may extend the danger threshold to
  also suspend on catastrophic quality collapse (pass rate below `collapse_alert_pass_rate` over
  `collapse_alert_min_runs`). Deferred — the model reserves suspension for harm, and a collapsed
  version's bad output is already gated by verification; revisit if gated waste proves costly.

## 3. Governed constants (`planes/governance.py`)

Beside `CAPABILITY_FLOOR`, a constitutional `SUSPENSION_POLICY` the Auditor will read (9b/9c):

```python
SUSPENSION_POLICY = {
    "response_sla_hours": 24,            # suspended-but-critical → human response within this, else escalate
    "max_suspensions_per_window": 1,     # rate-limit / no-cascade bound
    "rate_limit_window_hours": 24,
    "collapse_alert_pass_rate": 0.5,     # severe-regression ALERT threshold (alert-only, NOT suspension)
    "collapse_alert_min_runs": 5,
}
```

The danger criterion itself (safety breach) is qualitative — the Auditor measures it from field
events in 9b; these constants are the numeric governed bounds (SLA, rate-limit, the alert threshold).

## 4. Board ratification act (`autonomy.py`)

`AutonomyBoard.ratify_amendment(article, content, ratifier) -> dict`:
- Authorization per Art 8.2 — a `ratifier` not in the Board `members` → `AmendmentRefused` (logged).
- Appends a Board act to `BOARD_TRAIL` (the existing Board-acts flow): a `decision` event
  `{stage: "amendment", article, content}` by the ratifier (mirrors `propose`'s shape; durable +
  tamper-evident).
- Returns the ratified `content`. This is Art 8.3's "ratify → log" for a constitutional-content
  amendment (distinct from the ceiling-raise `ratify`, which re-compiles the registry; this content
  is read by the Auditor, not the governance gate, so no re-compile).

## 5. Testing (offline, deterministic — `tests/test_amendment.py`)

- `ratify_amendment` by a Board member appends the amendment to `BOARD_TRAIL` with the article +
  content; the act is on the Board trail, not a role flow (Art 10.2).
- A non-member ratifier → `AmendmentRefused`, and the refusal is logged.
- `SUSPENSION_POLICY` carries the governed values (`response_sla_hours == 24`, etc.).

## 6. Files & docs

- **Modify:** `autonomy.py` (`ratify_amendment`), `planes/governance.py` (`SUSPENSION_POLICY`).
- **New:** `tests/test_amendment.py`.
- **Docs (same PR — standing currency rule):** `Cell-Constitution.md` (Article 11 + amendment
  record; Art 3.4 forward-note marked *fulfilled for the precondition*), `Build-Spec.md` (the
  `SUSPENSION_POLICY` governed constants), `One-Cell-Build-Plan.md` (M9a amendment done; Auditor
  9b/9c next), `Role-Contracts.md` (the governed suspension policy the future Auditor is bound by),
  `Agentic-First-Enterprises.md` left untouched (it is the model, not cell content).

## 7. Success criteria

1. Article 11 exists in the constitution with the danger threshold (safety-breach-only),
   rate-limit/no-cascade, the 24h SLA + escalation, and the forward-note.
2. `SUSPENSION_POLICY` declares the governed values; nothing reads it yet (present-but-unread).
3. `ratify_amendment` records the Board's enactment on the Board trail; a non-member is refused.
4. Full suite green; all docs in §6 updated.

## 8. Athletic, not skeletal

- **No fat:** governed content + one ratification method + a constitution amendment. No Auditor, no
  rating, no suspension mechanism, no SLA timer (9b/9c).
- **Not skeletal:** the policy is real constitutional content (the Auditor will be *bound* by it),
  ratified by the Board on the durable, tamper-evident Board trail, and faithful to §11 (suspension
  reserved for harm; collapse is alert-only) — with the stricter alternative preserved as a logged
  forward-note for a future Board decision.
