---
Title: M8 — The Optimizer (capability/cost-aware implementer routing) — Design Spec
Version: 0.1.0
Date: 27.06.2026
Status: Draft — design approved, awaiting spec review
Companion to: Agentic-First-Enterprises §10 (Optimizer) · One-Cell-Build-Plan (M8) · Constitution Art 3.4
---

# M8 — The Optimizer

## 1. Purpose & context

The Optimizer is a **non-authoritative system role** (sibling to the Steward: the Steward optimizes
for reliability, the Optimizer for efficiency/capability-fit). It does **selection only, no business
decisions** (model §4.6/§10): it matches each task to the **minimum-capability implementer that
still clears the task's risk/quality floor**, and minimizes cost only *beneath* that floor.

Its precondition is now met: cost is attributed onto events (wall-clock + tokens) and there is real
capability/cost spread across the CLI runtime presets behind the Executor seat. Per invariant #8 it
was deferred until exactly this point.

**Decisions carried from brainstorming (approach A1):**
- **Offline selector** — the real routing *logic*, proven deterministically; candidates are the
  runtime presets (capability tier + cost). No requirement that other CLIs are installed; a live
  multi-runtime route is a later opt-in.
- **Route by the now-attributed cost** — per-implementer mean cost read from the event plane, with a
  declared **nominal fallback** at cold-start.
- **The risk→capability floor is constitutional input, NOT the Optimizer's judgment** (§10
  separation: a role that both set the floor and optimized against it could quietly lower it). The
  floor lives with the governance action-class registry; the Optimizer reads it.
- **Placement: at work-item assignment** (right after `decompose`, per item) — the Orchestrator owns
  assignment, the Optimizer advises it, and the choice **propagates to the worker** via the recorded
  assignment. Stable across the verdict-return retry loop, and recoverable on resume/re-entry.

**Out of scope (YAGNI / §8):** multi-objective optimization (latency/quality blends), version
ratings and learning (that is the Auditor, M9), live multi-runtime routing, any authority to change
the floor or make business/priority decisions.

## 2. The Optimizer (`src/cell/optimize.py`)

```
@dataclass(frozen=True)
class Implementer:
    id: str                 # also the executor actor's `version`, so its cost is attributable
    capability_tier: int    # 1 light · 2 standard · 3 strong
    executor: Executor      # bound implementer (a runtime preset, the reference executor, …)
    nominal_cost: float     # cold-start cost when no attributed history exists

class Optimizer(Protocol):
    def select(self, item: WorkItem, candidates: list[Implementer],
               costs: dict[str, float]) -> Implementer: ...

class NoCapableImplementer(Exception): ...   # nothing clears the floor → escalate, never route below
```

`CostAwareOptimizer.select`:
1. `floor = CAPABILITY_FLOOR[level_for(item.action_class)]` — constitutional input (read, not set).
2. `eligible = [c for c in candidates if c.capability_tier >= floor]`; if empty → `NoCapableImplementer`.
3. return `min(eligible, key=lambda c: costs.get(c.id, c.nominal_cost))` — cheapest above the floor,
   attributed cost where known, nominal otherwise.

Selection only; it records nothing itself — the handbrake logs the decision (§5) so routing is
auditable and the Optimizer stays a pure function.

## 3. The constitutional floor (`src/cell/planes/governance.py`)

A declared mapping beside `ACTION_CLASS_REGISTRY`:

```
CAPABILITY_FLOOR: dict[Level, int] = {"L3": 1, "L2": 1, "L1": 2, "L0": 3}
```

Higher risk demands a stronger minimum implementer; a high-blast (L0) task may never be routed to a
weak one to save money. Refinable only as constitutional content (a Board amendment), exactly like
the action-class registry it sits next to.

## 4. Attributed-cost source

- **`EventStore.all_events() -> list[Event]`** — a cross-flow read added to the Protocol and both
  stores (the model names Observability as the raw signal the Steward/Optimizer/Auditor consume, so
  a cross-flow analytics read is legitimate, not fat). `InMemoryEventStore` flattens its dict;
  `DurableEventStore` does `SELECT * FROM events ORDER BY flow_id, seq`.
- **`mean_cost_for(events, implementer_id) -> Optional[float]`** in `optimize.py`: the mean `compute`
  of `execute` events whose `actor.version == implementer_id`; `None` if no such history.
- The handbrake builds `costs = {im.id: mean_cost_for(store.all_events(), im.id)}` (dropping `None`),
  so `select` falls back to each implementer's `nominal_cost` until real history accrues.

## 5. Flow wiring — route at assignment (`handbrake.py`, `cell.py`)

`CellHandbrake`/`Cell.assemble` gain optional `optimizer: Optimizer` and `implementers:
list[Implementer]`. Routing is **YAGNI-gated**: it engages only with an optimizer wired **and ≥2
implementers** — otherwise the single `self.executor` is used unchanged (a uniform pipeline gets no
router, §10).

In `_advance`, before `_do_item`, the handbrake assigns the implementer per item:

```
def _assign(flow_id, item) -> Executor:
    if not (optimizer and len(implementers) >= 2):
        return self.executor
    prior = the recorded "route" decision for item.id, if any      # resume/re-entry: reuse it
    if prior: return implementer_by_id(prior.chosen).executor
    costs = {im.id: c for im in implementers if (c := mean_cost_for(store.all_events(), im.id))}
    chosen = optimizer.select(item, implementers, costs)
    store.append(flow_id, "decision", OPTIMIZER_ACTOR,
                 {"stage": "route", "work_item_id": item.id, "chosen": chosen.id,
                  "floor": CAPABILITY_FLOOR[level_for(item.action_class)],
                  "costs": {im.id: costs.get(im.id, im.nominal_cost) for im in implementers}})
    return chosen.executor
```

`_do_item` takes the assigned `executor` (instead of `self.executor`) and uses it for the execute
span, the marker actor, and the perform actor — so the execute event's `actor.version` is the chosen
implementer's id, closing the attribution loop. The recorded `route` event makes the assignment
**auditable** and **recoverable** (a retry or a resume reuses the recorded choice rather than
re-routing on shifted costs). `OPTIMIZER_ACTOR = ActorRef("Optimizer", "ref")`.

## 6. Data flow

```
specify → decompose → [per item] route(Optimizer: floor→eligible→min attributed cost) → assign
        → govern → execute(assigned implementer; cost attributed to its id) → perform → verify
no optimizer / <2 implementers: route step is skipped entirely (self.executor as today)
```

## 7. Error handling / edge cases

- No candidate clears the floor → `NoCapableImplementer` (escalate; never route below the floor).
- No attributed history for an implementer → nominal fallback (cold-start).
- Resume / re-entry / verdict-return retry → reuse the recorded `route` assignment (no re-routing).
- ≤1 implementer or no optimizer → no routing, behaviour byte-identical to today.
- Tie on cost → `min` is stable (first eligible in declared order) — deterministic.

## 8. Testing (offline, deterministic — `tests/test_optimizer.py`)

- **Floor respected:** an L0 (`CLASS_HIGH_BLAST`) item never routes to a tier-1 implementer even if
  it is cheapest; a tier-3 is chosen.
- **Min-cost above floor:** among floor-clearing candidates, the cheapest `costs[id]` wins.
- **Attributed beats nominal:** seed `execute` history making implementer B cheaper than its nominal
  ordering; routing flips to B (proves "route by the now-attributed cost").
- **No capable implementer:** floor above every tier → `NoCapableImplementer`.
- **all_events:** returns execute events across multiple flows; `mean_cost_for` averages by
  `actor.version`.
- **Wiring:** with ≥2 implementers a `route` event is logged and the execute event's `actor.version`
  is the chosen id; with ≤1 implementer no `route` event appears and behaviour is unchanged; a
  re-entered/retried flow reuses the recorded assignment.

Existing suite stays green; `Cell.assemble()` with no optimizer is unchanged.

## 9. Files & docs

- **New:** `src/cell/optimize.py`, `tests/test_optimizer.py`.
- **Modify:** `planes/governance.py` (`CAPABILITY_FLOOR`), `planes/memory.py` (`all_events`),
  `handbrake.py` (`_assign`, thread executor into `_do_item`, optional fields), `cell.py` (assemble
  params + expose).
- **Docs (same PR — standing currency rule):** `Role-Contracts.md` (add the Optimizer contract — it
  was deferred), `Cell-Constitution.md` Art 3.4 (Optimizer now instantiated; floor is constitutional
  content), `One-Cell-Build-Plan.md` (M8 status: built), `Build-Spec.md` (the floor map + the
  `all_events` read), `Component-Selection.md` (Optimizer infra now present, minimal), `README.md` +
  `docs/Using-a-Cell.md` (capability/cost routing; the `route` line in `observe`).

## 10. Success criteria

1. The Optimizer routes a work item to the cheapest implementer that clears its constitutional floor,
   using attributed cost (nominal fallback), and **refuses** to route below the floor.
2. The decision is a recorded, auditable `route` event; resume/retry reuse it.
3. With no optimizer or <2 implementers, a cell runs exactly as today (full suite green).
4. The floor stays constitutional — the Optimizer reads `CAPABILITY_FLOOR`, never sets it.
5. All docs in §9 updated in the same change.

## 11. Athletic, not skeletal

- **No fat:** a pure selector + a small cost helper + one `all_events` read + an optional assignment
  step. No multi-objective engine, no version ratings/learning (Auditor's job), no live multi-runtime
  dependency. The router vanishes when there is nothing to route.
- **Not skeletal:** it enforces the §10 hard constraint (capability floor, never traded for cost),
  routes by *real* attributed cost, records an auditable decision, and recovers it on resume — a
  genuine, governed router, not a toy.
