---
Title: Cost-into-events + start() Re-entry — Design Spec
Version: 0.1.0
Date: 27.06.2026
Status: Draft — design approved, awaiting spec review
Companion to: Build-Spec §1 (schema) · §3 (trace/cost) · Role-Contracts (Executor) · Handbrake-Interface
---

# Cost-into-events + `start()` Re-entry

Two cohesive changes to the handbrake's event emission, bundled because both touch how events are
written.

## 1. Purpose & context

1. **Cost-into-events.** Live runs show `total cost: 0` because event cost comes from `_ecost(stage)
   → cost_model(stage)` — a stub that is `None` by default. The tracer already *measures* each
   step's wall-clock but never writes it into the cost, and `Output`/`Verdict` carry no cost, so a
   runtime's token usage has no channel into events. Result: cost is blind on real runs, which
   blocks the cost-aware Optimizer. We attribute **real** cost onto events: measured **wall-clock**
   (universal) plus **tokens** from runtimes that report them (claude).
2. **`start()` re-entry.** Re-invoking `start()` on an existing `flow_id` blindly re-emits the
   specify→decompose→gate prefix (the cause of the live run's confusing "3× re-derivation" — three
   invocations sharing `flow_id "live-1"`). Correctness held (idempotency produced exactly one PR),
   but the durable log was polluted. We make `start()` resume cleanly on re-entry.

**Decisions carried from brainstorming:**
- Cost scope: **wall-clock now (universal) + claude tokens now** (per-preset usage parser; other
  presets stay wall-clock-only). Mechanism: **reuse the existing `SpanHandle`** (A1).
- Measured cost becomes the canonical M3 source; **`cost_model` is demoted to an optional
  override/fallback** (still honoured if injected — tests, future $-rate models).
- Executor reports cost via a new optional **`Output.cost`** field (natural home; the out-of-band
  alternative needs mutable actor state — violates invariant #5).
- Re-entry: **resume cleanly** — completed flow → return the recorded verdict, append nothing;
  crashed flow → reuse the recorded prefix and continue, no duplicate prefix.

**Overriding constraint — athletic, not fat, no new deps.** Each change is small and behind an
existing seam. **Keep ALL docs current** (standing rule) — see §7.

**Out of scope (YAGNI):** a real cost model / $-pricing (the Optimizer's job); token capture for
codex/gemini/pi (their parsers stay `None` until needed); persisting trace spans durably (Approach 3
of the observability design); resume of *paused* flows via `start()` (that is `resume()`'s job — a
re-entered paused flow simply re-pauses).

## 2. Cost-into-events

### 2.1 Measured cost via `SpanHandle` (`planes/observability.py`)
`Tracer.span` already yields a `SpanHandle` and records `started_at`/`ended_at`. Change: on span
close, compute `elapsed_ms = round((ended_at − started_at) in ms)` and set the **measured** cost as
both the `TraceSpan.cost` and `handle.cost`, so the handbrake can read it after the block:

```
base     = handle.cost if handle.cost is not None else self.cost_model(step)   # may be None
measured  = dataclasses.replace(base or CostDelta(), wall_clock_ms=elapsed_ms)
handle.cost = measured           # caller reads this for the event
record TraceSpan(cost=measured, started_at=…, ended_at=…, …)
```

Wall-clock is authoritative from the span (it **replaces** `wall_clock_ms`, never doubles it);
`compute`/`units`/`human_time_ms` come from the caller-set cost (tokens) or `cost_model`, else zero.
The Tracer's injectable `clock` keeps `elapsed_ms` deterministic in tests.

### 2.2 Handbrake uses the measured cost (`handbrake.py`)
Every traced step appends its event with the span's measured cost instead of the `_ecost` stub:

```
with tracer.span("specify", actor, "decision") as h:
    goal = self.director.specify(ticket)
self.store.append(flow_id, "decision", goal.created_by, {…}, cost=h.cost)
```

For execute, the executor's token cost is fed in before the span closes, so the event carries
tokens + wall-clock:

```
with tracer.span("execute", actor, "tool_call") as h:
    output = self.executor.execute(item)
    h.cost = output.cost          # tokens (or None)
self.store.append(flow_id, "action", {…execute marker…}, cost=h.cost)
```

`_ecost` is removed from the append sites; `cost_model` now flows only through the Tracer (as the
fallback base). The perform/deliver effect events stay as they are (no role-step timing).

### 2.3 Token channel (`runtime/` + `domain/objects.py`)
- **`domain/objects.py`:** `Output` gains `cost: Optional[CostDelta] = None` (Build-Spec §1).
- **`runtime/runner.py`:** `RunResult` gains `cost: Optional[CostDelta] = None`. `CliAgentSpec`
  gains `usage_parser: Optional[Callable[[str], Optional[CostDelta]]] = None`. After a successful
  run, `CliAgentRunner.run` sets `RunResult.cost = spec.usage_parser(stdout)` when a parser exists.
  The **claude** preset adds `--output-format json` to its args and a parser that reads token usage
  from the JSON result and returns `CostDelta(compute=input+output tokens, units="tokens")`
  (returns `None` on any parse failure — wall-clock is still recorded). *The exact claude JSON field
  path and that `--output-format json` still performs edits with the prompt on stdin are verified by
  a live smoke test at implementation time, like the other preset flags.*
- **`runtime/real_executor.py`:** `RealExecutor.execute` copies the runner's `RunResult.cost` onto
  the `Output.cost` it returns.

Reference executors leave `Output.cost = None`; only a usage-reporting runtime populates it.

## 3. `start()` re-entry (`handbrake.py`)

```
def start(ticket, flow_id):
    if not self.store.read(flow_id):
        … fresh path: append specify + decompose, then _advance(0)  (unchanged) …
        return …
    return self._reenter(flow_id, ticket)

def _reenter(flow_id, ticket):
    goal  = self.director.specify(ticket)          # deterministic; NOT re-appended
    items = self.orchestrator.decompose(goal)       #   "
    index = first i where _existing_verdict(items[i]) is not a pass; else len(items)
    if index >= len(items):
        return self._existing_verdict(items[-1])    # completed → return verdict, append nothing
    self.store.append(flow_id, "decision", <orchestrator>, {"stage": "reenter", "index": index})
    return self._advance(flow_id, ticket, goal, items, index)
```

`_advance` already re-governs and runs `_do_item`, which recovers completed work via
`_existing_verdict`/`_unverified_output`. So a crashed flow reuses its recorded prefix, skips the
work it already finished, and completes — with a single `reenter` marker instead of a duplicate
prefix. Re-entry assumes deterministic `specify`/`decompose` (already relied on by `resume()`/
`inspect()` today). A re-entered *paused* flow re-pauses (use `resume()` to continue one).

## 4. Data flow

```
fresh:    start → specify(ev,cost=wall) → decompose(ev,cost=wall) → _advance
                → govern(ev) → execute(ev,cost=tokens+wall) → perform → verify(ev,cost=wall)
re-enter: start(existing) → _reenter → [completed → return verdict, 0 new events]
                                     → [crashed   → reenter marker → _advance from first unfinished]
```

## 5. Error handling / edge cases

- Token parse failure → `usage_parser` returns `None`; wall-clock still recorded (never crash on it).
- `--output-format json` not honoured by a future claude version → caught at the live smoke test;
  parser returns `None`; the run still works on wall-clock.
- Re-entry of a paused flow → re-pauses (documented; `resume()` is the intended path).
- Non-deterministic Director/Orchestrator → out of scope (reference roles are deterministic; same
  assumption `resume()` already makes).
- `dataclasses.replace` on a `None` base → guarded with `base or CostDelta()`.

## 6. Testing (offline, deterministic, in the suite)

- **Wall-clock on events:** inject a deterministic `clock` advancing a fixed delta; submit a flow;
  assert the execute event's `cost.wall_clock_ms` equals the expected elapsed.
- **Tokens on execute:** a fake executor returning `Output(cost=CostDelta(compute=1234))`; assert
  the execute event's `cost.compute == 1234` (and wall-clock merged in).
- **observe shows cost:** the summary's total cost is nonzero for such a flow.
- **claude preset:** `render_argv(claude_code())` includes `--output-format json`; the preset's
  `usage_parser` extracts tokens from a sample JSON string; a non-JSON string → `None`.
- **Re-entry, completed:** submit a flow to completion, submit again with the same `flow_id` →
  same verdict returned and the event count is unchanged (zero new events).
- **Re-entry, crashed:** pre-seed a flow with only specify+decompose (no verdict); `start()` reuses
  the prefix (specify count stays 1, one `reenter` marker) and completes with one execute + verdict.

Existing M3/M4/runtime tests stay green; where a test asserted `_ecost`/`cost_model` values, it
either injects `cost_model` (still honoured) or a fixed `clock` for deterministic wall-clock.

## 7. Files & docs

**Code (modify; no new modules):** `planes/observability.py` (SpanHandle/Tracer measured cost),
`handbrake.py` (use `h.cost`, drop `_ecost` at append sites, `_reenter`), `domain/objects.py`
(`Output.cost`), `runtime/runner.py` (`RunResult.cost`, `CliAgentSpec.usage_parser`, claude preset),
`runtime/real_executor.py` (thread cost). **Tests:** `test_observability.py`, `test_m4_handbrake.py`,
`test_runtime.py` (+ a focused `test_cost_attribution.py` if cleaner).

**Docs (standing rule — update in the same PR):**
- `Build-Spec.md` §3 (cost is **measured** wall-clock + reported tokens; `cost_model` an optional
  overlay) and §1 (`Output.cost`).
- `Role-Contracts.md` (Executor may report `Output.cost`).
- `Handbrake-Interface.md` (`start()` re-entry semantics).
- `README.md` "Observing a run" (cost is real now; **fix the misleading `re-derivations: 3` example
  to `1`**) and `docs/Using-a-Cell.md` §5.
- `src/cell/runtime/README.md` (claude reports token cost via `--output-format json`).

## 8. Success criteria

1. A live (or fake-token) run shows nonzero `total cost` in `cell.observe`, with wall-clock on every
   step and tokens on execute.
2. Re-running a completed `flow_id` adds zero events and returns the same verdict; re-running a
   crashed `flow_id` reuses the prefix (no duplicate specify) and completes.
3. Full suite green and deterministic; the live 3-invocation prefix pollution cannot recur.
4. All docs in §7 updated in the same change.

## 9. Athletic, not skeletal

- **No fat:** reuse the existing `SpanHandle`/`clock`/`cost_model` seams; one optional field each on
  `Output`/`RunResult`/`CliAgentSpec`; one `_reenter` method. No cost model, no $-pricing, no token
  capture for runtimes that don't report it, no new module.
- **Not skeletal:** cost is now *real and attributable* (the M3 promise), the token channel is a
  clean per-preset seam, and re-entry is genuinely safe (idempotent completed-flow, clean crashed-
  flow recovery) rather than log-polluting.
