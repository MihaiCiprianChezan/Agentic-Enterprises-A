---
Title: M9b — The Auditor (rate + report) — Design Spec
Version: 0.1.0
Date: 28.06.2026
Status: Draft — design approved, awaiting spec review
Companion to: Agentic-First-Enterprises §11 · Cell-Constitution Art 11 · cell/versions.py · cell/steward.py
---

# M9b — The Auditor (rate + report)

## 1. Purpose & context

The Auditor (model §11) judges **the version, as a population over time** — distinct from the
Verifier (one output) and the Steward (one live instance). Both M9 preconditions are met: versions
are first-class + scored (`version_stats`) and the suspension policy is ratified (Constitution
Art 11). This sub-project builds the Auditor's **non-authoritative core**: rate each version, produce
a per-role fitness leaderboard, and report regressions/danger as durable records. It does **not**
suspend, set status, modify, operate, or direct — those are 9c (suspend) or forbidden outright.

**Decisions carried from brainstorming:**
- **Emit audit records** (loose-coupled, faithful to the event plane) — ratings, regression alerts,
  danger flags on a reserved `__audit__` trail; the Steward/Optimizer/human read them. No direct
  cross-role calls; the Optimizer keeps routing by cost (unchanged).
- **Danger = a safety breach** attributable to a version (Art 11): it executed in a flow that then
  escalated / was Steward-quarantined, or hit a governance block. **Catastrophic quality collapse is
  `regressed` (alert-only), never `dangerous`** — the Verifier gates its outputs.

**Out of scope:** the suspend-and-escalate breaker + SLA timer (9c); rewiring the Optimizer to route
by rating; multi-metric trend/weighting engines; reinstatement (no agent reinstates).

## 2. The Auditor (`src/cell/auditor.py`)

`AUDIT_TRAIL = "__audit__"`, `AUDITOR_ACTOR = ActorRef("Auditor", "ref")`. Read + report only.
Inputs (all read-only): `version_stats(store.all_events())`, the `VersionRegistry` records (version
set + predecessor order), the governed `SUSPENSION_POLICY` (collapse-alert threshold), and the
safety events on the plane (`escalation`-kind events; governance `block`s).

```
@dataclass
class VersionRating:
    version: str
    role: str
    runs: int
    pass_rate: float
    mean_cost: float
    verdict: str            # unproven | healthy | regressed | dangerous
    vs_predecessor: Optional[str]   # "better" | "worse" | None (no predecessor / unproven)
    reasons: list[str]

class Auditor:
    def __init__(self, store, registry): ...
    def rate(self) -> dict[str, VersionRating]: ...      # keyed by version id
    def leaderboard(self, role: str) -> list[VersionRating]: ...
    def report(self) -> dict[str, VersionRating]: ...    # emits audit records, returns the ratings
```

## 3. Rating logic

Per version with field activity (only versions that ran appear in `version_stats` — in practice the
Executor variants; an idle operating-role version has nothing to judge):
- `pass_rate = passes / runs` (0 if no runs); `mean_cost` from the scorecard.
- **`unproven`** — `runs < SUSPENSION_POLICY["collapse_alert_min_runs"]` (too little evidence).
- **`dangerous`** — a safety breach is attributable: the version executed in a flow that also carries
  an `escalation` event (Steward quarantine / flow escalation) or a governance `block`.
- **`regressed`** — `pass_rate < SUSPENSION_POLICY["collapse_alert_pass_rate"]` (catastrophic
  collapse), **or** worse than its predecessor (lower pass rate). Alert-only.
- **`healthy`** — otherwise.

Precedence: dangerous > regressed > healthy (a dangerous version is reported dangerous even if also
worse than its predecessor). `unproven` short-circuits (not enough data to rate fitness or danger).
Predecessor = the previously-registered version of the same role (registry order); `variant_of` is
the richer future mechanism. `reasons` records why (e.g. "pass_rate 0.3 < predecessor 0.9",
"quarantine in flow f2").

## 4. Leaderboard

`leaderboard(role)` → the role's **proven** versions (skip `unproven`) ranked by fitness: pass rate
descending, then mean cost ascending. The per-role fitness leaderboard §11 calls for.

## 5. Report (emit, never act)

`report()` writes durable **audit records** on `__audit__` (a new `"audit"` EventKind):
- one `rating` record per version (verdict + the numbers);
- a `regression` alert record where `verdict == "regressed"` (the signal for the Steward/Optimizer);
- a `danger` flag record where `verdict == "dangerous"` (the signal for humans / 9c).

It returns the ratings. This is the Auditor's entire world-effect in 9b — **records, not actions**.
It calls no `set_status`, no Steward/Optimizer method; the `dangerous` verdict is *produced* here and
*acted on* only by the 9c breaker.

## 6. Wiring (`cell.py`)

`Cell.assemble` builds `Auditor(store, registry)` (default) and exposes `cell.audit()` → runs
`report()` and returns the ratings + a `leaderboard` per role. `observe` renders `audit` events
(`rating Executor cheap: healthy (pass 1.0)`). Inert with no version activity.

## 7. Edge cases

- A version with no runs (idle operating role) → not in `version_stats`, not rated.
- A flow that escalated but where the version did **not** execute → not attributed to that version.
- No predecessor (first version of a role) → `vs_predecessor = None`; collapse can still mark
  `regressed`.
- Ties in the leaderboard → stable order (registry order) — deterministic.

## 8. Testing (`tests/test_auditor.py`, offline)

- A passing version with enough runs → `healthy`.
- A version that executed in a Steward-quarantined / escalated flow → `dangerous` (with the reason).
- A catastrophic-collapse version (pass rate below the threshold over ≥ min runs) → `regressed`,
  **not** dangerous (the Art 11 distinction).
- A version with a lower pass rate than its predecessor → `regressed` (`vs_predecessor == "worse"`).
- Too few runs → `unproven`.
- `leaderboard` ranks proven versions by pass rate then cost.
- `report()` emits `rating`/`regression`/`danger` records on `__audit__`; the Auditor takes **no**
  world-action (registry statuses are unchanged after `audit()`).

## 9. Files & docs

- **New:** `src/cell/auditor.py`, `tests/test_auditor.py`.
- **Modify:** `planes/memory.py` (`"audit"` EventKind), `cell.py` (Auditor wiring + `cell.audit()`),
  `observe.py` (render `audit` events).
- **Docs (same PR):** `Role-Contracts.md` (the Auditor contract — partially instantiated: rate +
  report; suspension is 9c), `One-Cell-Build-Plan.md` (9b done, 9c next), `Build-Spec.md` (the
  `__audit__` trail + audit record), README + `docs/Using-a-Cell.md`, `CLAUDE.md`.

## 10. Success criteria

1. The Auditor rates each version (`unproven`/`healthy`/`regressed`/`dangerous`) faithfully to
   Art 11 (danger = safety breach; collapse = regressed/alert-only) and ranks a per-role leaderboard.
2. `report()` emits audit records on `__audit__`; the Auditor performs **no** world-action.
3. With no version activity the cell is unchanged; full suite green.
4. All docs in §9 updated.

## 11. Athletic, not skeletal

- **No fat:** read inputs → rate → emit records. No suspension, no Optimizer rewiring, no trend
  engine, no reinstatement.
- **Not skeletal:** it produces a real fitness rating + leaderboard + the regression/danger signals
  §11 names, faithful to the governed Art 11 threshold — the evaluation signal the Optimizer and
  Steward already assume, now actually produced. 9c plugs the `dangerous` verdict into the breaker.
