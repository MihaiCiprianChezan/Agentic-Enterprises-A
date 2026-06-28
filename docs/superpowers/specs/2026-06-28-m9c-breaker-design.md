---
Title: M9c — The Auditor's Suspend-and-Escalate Breaker — Design Spec
Version: 0.1.0
Date: 28.06.2026
Status: Draft — design approved, awaiting spec review
Companion to: Agentic-First-Enterprises §11 · Cell-Constitution Art 11 · cell/auditor.py · cell/versions.py
---

# M9c — The Auditor's Suspend-and-Escalate Breaker

## 1. Purpose & context

The final M9 piece. The Auditor (9b) *rates* versions and *reports* `dangerous` ones but takes no
world-action. 9c adds its **one governed action**: a circuit breaker that **suspends** a version it
rated dangerous and **escalates** a stuck suspension — bounded by the ratified `SUSPENSION_POLICY`
(Constitution Art 11). It never reinstates (pause is unilateral for safety; un-pause is a
human/Steward act).

**Decisions carried from brainstorming:**
- **Suspend on danger only** — danger is a safety breach (Art 11), already computed by 9b. A
  `healthy`/`regressed` version is never suspended.
- **Rate-limited, non-cascading** — at most `max_suspensions_per_window` (1) suspensions per
  `rate_limit_window_hours` (24); excess dangerous versions are **escalated, not auto-suspended** (the
  cascade the limit exists to prevent).
- **Suspended-but-critical** = after the suspension, its role has **no other active version**. That
  opens a 24h SLA; a missed SLA (deadline passed, still suspended) → **break-glass escalation**.
- **Never reinstate** — `enforce` only ever sets `suspended`.

**Out of scope:** reinstatement (human/Steward); a scheduler/daemon (the breaker is an on-demand
pass); rewiring the Optimizer (it already skips non-active versions); the model's §17 break-glass
*infrastructure* beyond emitting the escalation record.

## 2. `Auditor.enforce(now=None) -> BreakerResult`

`now: Optional[datetime]` (default `datetime.now(timezone.utc)`). The Auditor gains the acting method
(9b's `report()` stays read-only). `BreakerResult` is a dataclass: `suspended: list[str]`,
`escalated: list[str]` (dangerous-but-rate-limited), `sla_opened: list[str]`, `breakglass: list[str]`.

```
def enforce(self, now=None) -> BreakerResult:
    now = now or _utcnow()
    ratings = self.rate()
    dangerous = [v for v, r in ratings.items()
                 if r.verdict == "dangerous" and self.registry.status_of(v) == "active"]
    budget = max_per_window - self._recent_suspensions(now)        # rate-limit headroom
    suspend, escalate = dangerous[:max(0, budget)], dangerous[max(0, budget):]
    for v in suspend:
        self.registry.set_status(v, "suspended")                  # Optimizer now skips it
        self._log("suspend", v, now, reason=ratings[v].reasons)
        if self._critical(ratings[v].role, v):                    # no other active version of the role
            self._log("sla_open", v, now, deadline=now + sla_hours)
    for v in escalate:
        self._log("escalate_unsuspended", v, now)                 # dangerous but rate-limited → human
    breakglass = self._sweep_missed_slas(now)                     # expired SLA + still suspended
    return BreakerResult(suspend, escalate, [...opened...], breakglass)
```

## 3. Rate-limit & no-cascade (§2 of the design)

`_recent_suspensions(now)`: count `suspend` acts on `__audit__` whose recorded `ts` is within
`rate_limit_window_hours` of `now`. Headroom = `max_suspensions_per_window − recent`. Suspend up to
the headroom; the rest are `escalate_unsuspended` (logged, **not** suspended). With the policy default
(1 / 24h), a single pass suspends at most one version even if several are dangerous — no cascade.

## 4. Critical + SLA lifecycle (§3)

- **Critical** = `not any(other active version of the same role)` after the suspension
  (`registry.records()` filtered by role + status). If critical → `sla_open` with
  `deadline = now + response_sla_hours`.
- **Miss sweep** `_sweep_missed_slas(now)`: for each `sla_open` with no later `sla_missed`/resolution,
  if `deadline < now` **and** `registry.status_of(v) == "suspended"` (not reinstated) → log
  `sla_missed` (break-glass) and return it. A version reinstated to `active` by then does **not** miss.
- Timestamps/deadlines are recorded in the breaker's own acts (from `now`), so the lifecycle is
  deterministic under an injected `now` — independent of event wall-time.

## 5. Logging (`__audit__` + `__versions__`)

Every act is an audit record on `__audit__` (`stage ∈ suspend | sla_open | sla_missed |
escalate_unsuspended`, with `version`, `ts`, and `reason`/`deadline`). The suspension is *also*
recorded as a registry status change on `__versions__` (via `set_status`). Doubly auditable, both
tamper-evident.

## 6. Wiring (`cell.py`, `observe.py`)

`cell.enforce(now=None)` → `auditor.enforce(now)`; `cell.audit()` stays read-only rate+report.
`observe` renders the breaker acts (`SUSPEND risky-v2`, `SLA opened risky-v2`,
`SLA-MISSED → break-glass risky-v2`, `escalate (rate-limited) other`).

## 7. Edge cases

- No dangerous versions → no-op (empty result).
- A dangerous version already `suspended` → skipped (idempotent; not re-suspended).
- Suspending a version that has a healthy active sibling → not critical, no SLA.
- An SLA whose version was reinstated before the deadline → no miss.
- `enforce` never sets `active` (no reinstatement path exists on the Auditor).

## 8. Testing (`tests/test_auditor.py`, offline, deterministic)

- A `dangerous` version → suspended (status `suspended`) + a `suspend` act logged.
- A `healthy`/`regressed` version → **not** suspended (only danger suspends).
- Two dangerous, limit 1 → exactly one suspended, the other in `escalated` (no cascade).
- Critical suspension (no active sibling) → `sla_open` with a deadline.
- Non-critical suspension (a healthy active sibling) → no SLA.
- An expired SLA, still suspended, on a later `enforce(now2)` → `breakglass`.
- A version reinstated to `active` before the deadline → no `breakglass`.
- `enforce` never sets a version `active`.

## 9. Files & docs

- **Modify:** `src/cell/auditor.py` (`enforce`, `BreakerResult`, helpers), `cell.py` (`cell.enforce()`),
  `observe.py` (render breaker stages).
- **Docs (same PR):** `Role-Contracts.md` (Contract 7 — add the breaker action + SLA), `Cell-Constitution.md`
  Art 11 (11.2/11.3 now realized in code), `One-Cell-Build-Plan.md` (**M9 complete**), `Build-Spec.md`
  (the breaker acts), README + `docs/Using-a-Cell.md`, `CLAUDE.md`.

## 10. Success criteria

1. The Auditor suspends only `dangerous` versions, within the rate limit (excess escalated, not
   suspended), and never reinstates.
2. A critical suspension opens the 24h SLA; an expired-and-still-suspended SLA produces a break-glass
   escalation; a reinstated version does not miss.
3. Every act is logged on `__audit__` and (for suspensions) `__versions__`.
4. Full suite green; all docs updated; **M9 complete** (M0–M9 done).

## 11. Athletic, not skeletal

- **No fat:** one `enforce` pass — suspend-on-danger within the governed bounds + the SLA lifecycle.
  No reinstatement, no scheduler, no new role, no Optimizer rewiring.
- **Not skeletal:** the breaker is real and governed — rate-limited/non-cascading, critical-aware,
  with a deterministic SLA→break-glass safety valve, faithful to Article 11. It completes the
  evaluation loop the Optimizer and Steward assume, and closes M9.
