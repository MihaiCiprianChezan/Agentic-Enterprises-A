---
Title: Establish Multiple Versions (the M9 Auditor precondition) — Design Spec
Version: 0.1.0
Date: 27.06.2026
Status: Draft — design approved, awaiting spec review
Companion to: Build-Spec §2.4 (version registry) · Agentic-First-Enterprises §11 (Auditor/versions) · Constitution Art 3.4
---

# Establish Multiple Versions

## 1. Purpose & context

The Auditor (M9) rates **versions** of roles from field activity and closes the evaluation loop the
Optimizer/Steward assume. Its precondition — *multiple versions running, with per-version
performance to compare* — is not yet met: Build-Spec §2.4's `VersionRecord` is a documented stub,
`ActorRef.version` is a free string, and there is no per-version outcome signal. This sub-project is
the **enabler**: make role versions first-class so M9 has something real to audit. It does **not**
build the Auditor (no ratings, trends, or suspension *decisions* — that is M9).

**Decisions carried from brainstorming (approach A1):**
- **Event-sourced registry** on a reserved `__versions__` flow — state lives in the event plane
  (invariant #5), durable and auditable like everything else.
- A new **`"version"` event kind** so the Auditor and `observe` can query version records cleanly.
- **The Optimizer respects version status here** (skips non-`active` versions) — this is what makes
  the registry functional and makes M9's suspension lever actually bite.

**Out of scope (YAGNI / §8):** the Auditor itself (ratings, regression alerts, the suspend-and-
escalate breaker, the human-response SLA), version *deployment*/rollout machinery, multi-cell
version sharing. The constitution amendment the Auditor needs (suspension threshold + SLA, Art 3.4
forward-note) lands with M9, not here.

## 2. `VersionRegistry` (`src/cell/versions.py`)

Implements Build-Spec §2.4, event-sourced on the reserved flow id `__versions__`:

```
VERSIONS_FLOW = "__versions__"
VersionStatus = Literal["active", "rolled_back", "suspended"]

@dataclass(frozen=True)
class VersionRecord:
    role: str
    version: str
    status: VersionStatus
    variant_of: Optional[str] = None

class VersionRegistry:
    def __init__(self, store): self.store = store
    def register(self, role, version, variant_of=None) -> None      # idempotent
    def set_status(self, version, status) -> None
    def records(self) -> dict[str, VersionRecord]                    # version -> current record
    def status_of(self, version) -> VersionStatus                   # "active" if seen-but-unregistered
```

- `register` appends a `version` event `{stage:"register", role, version, variant_of, status:"active"}`;
  `set_status` appends `{stage:"status", version, status}`. `records()`/`status_of()` **fold** the
  `__versions__` events to current state (latest wins). Registering an already-active version is a
  harmless re-append (fold is idempotent).
- `status_of(version)` returns the folded status, defaulting to `"active"` for a version that has
  appeared in field activity but was never explicitly registered (field activity is ground truth;
  the Auditor can later register/suspend it).

## 3. Per-version scorecard — `version_stats(events)`

```
@dataclass
class VersionStat:
    runs: int; passes: int; returns: int; blocks: int; mean_cost: float

def version_stats(events) -> dict[str, VersionStat]: ...
```

For each `execute` event, its version is the routed `implementer` tag (else `actor.version`) and its
`output_id`; join to the matching `verdict` event (same `output_id`) for the outcome
(`pass`/`return`), and to `governance` blocks for that work item. `mean_cost` is the mean `execute`
`compute` per version. This is the **raw signal the Auditor will rate** — produced now, consumed in
M9. Pure over an events list (use `store.all_events()` for the cross-flow view).

## 4. Optimizer respects version status (`handbrake._assign`)

Before `select`, filter candidates to active versions:
`candidates = [im for im in self.implementers if self.registry.status_of(im.id) == "active"]`.
A `rolled_back`/`suspended` version is never routed to. If no active candidate clears the floor →
`NoCapableImplementer` (escalate). With no registry wired, all implementers are treated active
(behaviour unchanged).

## 5. Wiring (`cell.py`)

`Cell.assemble` builds a `VersionRegistry(store)` by default and **registers each wired
implementer's version as `active`**; it also registers the operating roles' single versions
(`_actor_of(...).version`) so the Auditor sees the full set. Exposes `cell.versions()` →
`registry.records()` and `cell.version_stats()` → `version_stats(store.all_events())`. The handbrake
gets the registry for §4. Re-assembly re-registers idempotently.

## 6. Data flow

```
assemble → registry.register(each role/implementer version, active)
route    → _assign filters to active versions → Optimizer picks among them
run      → execute(tagged with version) → verdict → version_stats folds per-version outcome+cost
suspend  → registry.set_status(v, "suspended") → _assign no longer routes to v
```

## 7. Edge cases

- Unregistered version seen in events → counted in the scorecard; `status_of` defaults `active`.
- All candidate versions suspended → `NoCapableImplementer` (escalate; never route to a suspended one).
- No registry (older callers) → all implementers active; unchanged.
- `__versions__` is a normal durable flow → hash-chained and visible to `observe` like any flow.

## 8. Testing (offline, deterministic — `tests/test_versions.py`)

- Registry round-trip: `register` then `records()`/`status_of()` reflect it; `set_status` updates;
  fold takes the latest of duplicate registrations.
- Durable: a fresh `VersionRegistry` on the same `DurableEventStore` re-reads the records (event-sourced).
- Routing gate: two implementers, suspend the cheaper → the Optimizer routes to the other; suspend
  both eligible → escalate.
- Scorecard: a couple of runs across versions → `version_stats` tallies runs/passes/returns and the
  mean cost per version.
- `Cell.assemble` registers the wired implementers/roles as active (visible via `cell.versions()`).

Existing suite stays green; a cell with no implementers behaves exactly as today.

## 9. Files & docs

- **New:** `src/cell/versions.py`, `tests/test_versions.py`.
- **Modify:** `planes/memory.py` (`"version"` EventKind), `handbrake.py` (status filter in `_assign`
  + hold the registry), `cell.py` (registry wiring + `versions`/`version_stats`), `observe.py`
  (render `version` events).
- **Docs (same PR — standing currency rule):** Build-Spec §2.4 (registry built, statuses incl.
  `suspended`), Role-Contracts + Cell-Constitution (version status is the Auditor's lever; the
  Optimizer respects it), One-Cell-Build-Plan (versions enabler ahead of M9), README +
  `docs/Using-a-Cell.md`, CLAUDE.md.

## 10. Success criteria

1. Versions can be registered and have status (`active`/`rolled_back`/`suspended`), event-sourced and
   durable.
2. The Optimizer never routes to a non-active version; a suspended version is skipped (escalate if
   none active clears the floor).
3. `version_stats` gives per-version runs/pass/return/block + mean cost from field activity.
4. `Cell.assemble` registers the running versions; `cell.versions()`/`cell.version_stats()` expose them.
5. Full suite green; all docs in §9 updated.

## 11. Athletic, not skeletal

- **No fat:** a registry + a scorecard helper + a status filter. No Auditor, no ratings/trends, no
  suspension *policy* (M9), no deployment machinery.
- **Not skeletal:** the registry is real (event-sourced, durable, statused), status genuinely gates
  routing, and per-version outcome is measured from field activity — a working version layer the
  Auditor plugs straight into.
