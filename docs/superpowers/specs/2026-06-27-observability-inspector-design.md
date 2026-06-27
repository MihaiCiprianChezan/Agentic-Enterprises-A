---
Title: Observability Inspector + Usage Docs — Design Spec
Version: 0.1.0
Date: 27.06.2026
Status: Draft — design approved, awaiting spec review
Companion to: One-Cell-Build-Plan.md (M3 observability) · Build-Spec §2 (event plane) · §3 (trace/cost)
---

# Observability Inspector (`cell.observe`) + Usage Docs

## 1. Purpose & context

The cell already records everything it does to a **durable, hash-chained event plane** (M0/M3):
decisions, governance allow/blocks, executor actions, verdicts, and performed effects — each with
a timestamp and attributable cost. But there is no convenient way to *read a finished run back*,
so confirming "did this manual/live run behave as expected?" means re-deriving meaning from raw
events or reproducing the run. This is the instrument panel gap.

This project adds a **thin, read-only inspector** over the durable plane and the **usage docs** to
find it:

1. `python -m cell.observe <state_db> [flow_id]` — pretty-prints a finished run's full trajectory
   (timeline + verdict summary), so a human (or the agent driving a manual run) can verify the
   system worked. Post-hoc only; the record is durable, so nothing is lost by reading after exit.
2. A short **"Observing a run"** section in the root `README.md`.
3. A dedicated **`docs/Using-a-Cell.md`** usage guide (start → use → observe), linked from the
   README, plus README cross-links to every relevant doc in `docs/`.

**Decisions carried from brainstorming:**
- **Approach 1 (thin reader):** a standalone `cell/observe.py` over the durable plane; **no change
  to the cell, planes, or governance**. (Approach 3 — persisting `TraceSpan`s durably for richer
  per-span detail — is a clean future extension, deferred until sub-step span detail is needed.)
- **Post-hoc only** (no live tail).
- **Output = timeline + verdict summary**, with `--full` to dump complete event payloads.

**Overriding constraint — athletic, not fat, no new dependencies.** Pure interpretation layer over
existing read APIs (`DurableEventStore.read`, `compute_hash`, `total_cost`, `EffectsLedger.get`).

**Out of scope (YAGNI):** live tailing, JSON/automation output, durable trace spans (Approach 3),
filtering/query languages, multi-flow aggregation, any web UI.

## 2. Data source (why events suffice)

For a *past* run the durable ground truth is the **event plane**, not the trace store:

- `Event` carries `seq, flow_id, prev_hash, hash, kind, actor, payload, at, cost` and is persisted
  by `DurableEventStore` (the trace `recorder` is `InMemoryTraceStore` and is gone after the
  process exits — `live.py` wires durable `store`+`ledger` but not a durable recorder).
- Everything the inspector shows derives from events: trajectory (kind/actor/payload), **cost**
  (`total_cost(events)`, the same call `cell.cost` uses), **timing** (`Event.at`), the **verdict**
  (the `verdict` events), **governance** outcomes (the `governance` events), and the **PR URL** (the
  perform action event's `payload["result_digest"]`, which holds the real result string).
- **Integrity:** `verify_chain` recomputes each link with the store's own `compute_hash(prev_hash,
  payload)` and checks `prev_hash` continuity — a true tamper-evidence check, not just a link walk.

The **effects ledger** (`SqliteEffectsLedger` in the same DB) is read *optionally* to annotate each
performed effect as exactly-once-confirmed (`ledger.get(key)` is a completed `EffectRecord`). If the
ledger table is absent/unreadable, the inspector degrades gracefully and still reports from events.

## 3. Component: `src/cell/observe.py`

A single read-only module. Pure, testable core + a thin CLI shell.

### 3.1 Pure core (no I/O, unit-tested directly)
- `key_fact(event) -> str` — a kind-specific one-line summary from `event.payload`:
  - `decision` → `specify · goal <id> (<purpose>)` or `decompose · N work items`
  - `governance` → `ALLOW|BLOCK L<level> <action_class>` (+ reason on block)
  - `action` (execute) → `execute → <artifact_ref>`
  - `action` (perform) → `perform <step> [<effect_kind>] key=…<tail>` and, if a result is present,
    `→ <result>` (the PR URL)
  - `verdict` → `PASS|RETURN` (+ reason tail on return)
  - `breakpoint`/`injection`/`escalation`/`state` → a short label from the payload
- `verify_chain(events) -> tuple[bool, Optional[int]]` — `(intact, first_broken_seq)`, recomputing
  with `compute_hash`.
- `summarize(events, ledger=None) -> RunSummary` — a small dataclass:
  `verdict` (PASS|RETURN|BLOCKED|PAUSED|UNKNOWN), `execute_attempts` (count of execute actions),
  `rederivations` (count of specify→decompose→govern rounds = count of `specify` decisions),
  `gov_allow`/`gov_block` counts, `effects` (list of `(step, effect_kind, result, once_confirmed)`),
  `total_cost`, `window` (first.at, last.at), `chain_intact`, `chain_broken_at`, `actors` (ordered
  unique role/agent pairs).
  - **Verdict rule:** last `verdict` event → its decision; else if a `governance` block exists with
    no later resolution → BLOCKED; else if the run ends on an unresolved `breakpoint` → PAUSED; else
    UNKNOWN.

### 3.2 Formatting
- `format_header(summary, db, flow_id) -> str`, `format_timeline(events) -> str`,
  `format_summary(summary) -> str` — produce the layout in §4. `--full` appends each event's
  complete payload as indented, sorted-key JSON.

### 3.3 CLI (`main(argv=None) -> int`, `python -m cell.observe`)
- `observe <state_db> [flow_id] [--full]`
- no `flow_id` → list the distinct flow ids in the DB (discovery) and exit 0
- with `flow_id` → header + timeline + summary, exit 0
- exit codes: 0 ok; 2 usage/not-found (missing DB, unknown flow id, empty flow)

## 4. Output format

```
flow: live-1     db: cell-sandbox.cell-state.db
actors: Director · Orchestrator · Executor(real-cli) · Verifier
events: 13       window: 20:18:55 → 20:19:42 (47s)     chain: ✓ intact

  seq  kind        actor          key fact                                    +Δt
    0  decision    Director       specify · goal g1 (in_purpose)             0.0s
    1  decision    Orchestrator   decompose · 1 work item                    0.0s
    2  governance  Executor       ALLOW L2 own_write                         0.1s
    …  (re-derivation rounds 2 & 3) …
    9  action      Executor       execute → branch:cell/slice@a1b2c3d        1.2s
   10  action      Executor       perform open_pr [irreversible] key=…ab12   1.2s
   11  verdict     Verifier       PASS                                       4.6s
   12  action      Executor       perform open_pr → https://…/pull/1         4.6s

VERDICT: PASS
execute attempts: 1   ·   re-derivations: 3 (specify→decompose→govern)
governance: 3 allow · 0 block
effects: 1 performed — open_pr → https://…/pull/1  (exactly-once ✓)
total cost: <CostDelta summary>
chain: ✓ intact (tamper-evident)
```

A broken chain prints the timeline normally but the header and summary show
`chain: ✗ BROKEN at seq N` — surfacing tampering is the job, so it must never be swallowed.

## 5. Error handling

| Condition | Behaviour |
|---|---|
| DB file missing | clear message to stderr, exit 2 |
| `flow_id` unknown | list available flow ids, exit 2 |
| Flow has no events | "no events for <flow_id>", exit 2 |
| Hash chain broken | print timeline; flag `chain: ✗ BROKEN at seq N` in header + summary; exit 0 |
| Ledger absent/unreadable | skip exactly-once annotation, note it; still report from events |
| Unknown event kind | fall back to a generic `<kind> · <first payload keys>` line (never crash) |

## 6. Testing — `tests/test_observe.py` (offline, deterministic, in the suite)

Append a known flow to a temp `DurableEventStore` (decision specify → decision decompose →
governance allow → action execute → verdict pass → action perform), then assert:

1. `summarize` → `verdict == "PASS"`, `execute_attempts == 1`, `rederivations == 1`,
   `gov_allow == 1`, one effect with its result, `chain_intact is True`.
2. `format_timeline` contains the key facts: the branch `artifact_ref`, `PASS`, and the PR URL.
3. `verify_chain` flags a tampered row: rewrite one stored `payload` so its `hash` no longer
   matches → `(False, seq)`, and `format_summary` shows `✗ BROKEN at seq N`.
4. CLI with no `flow_id` lists the flow ids; CLI with an unknown `flow_id` exits 2.

No network, no real `gh`, no LLM. Reuses `DurableEventStore`/`SqliteEffectsLedger` on a temp file.

## 7. Docs deliverables

- **Root `README.md`:**
  - a short **"Observing a run"** section (the `cell.observe` command + a small sample), placed
    after "Run the real slice".
  - a one-line link to the new `docs/Using-a-Cell.md`.
  - ensure the "Read the design" list links **every** `docs/*.md` (add the milestone note
    `M0-Implementation-Notes.md` under a "deeper" line).
- **`docs/Using-a-Cell.md` (new):** a brief-but-clear usage guide — install, run the tests, watch
  the demo, assemble + drive a cell in code (submit / handbrake ops), run the live slice, and
  observe a run with `cell.observe`. It is the "how to actually use it" reference the README links
  to; the README stays the onramp and does not duplicate it at length.
- **`src/cell/runtime/README.md`:** one-line pointer — after a live run, inspect it with
  `python -m cell.observe <state_db> <flow_id>`.

## 8. Files

- **New:** `src/cell/observe.py`, `tests/test_observe.py`, `docs/Using-a-Cell.md`.
- **Modified:** `README.md` (Observing-a-run section + doc cross-links), `src/cell/runtime/README.md`
  (one-line pointer). **No change** to any `cell/*` runtime module, plane, or governance.

## 9. Success criteria

1. `python -m cell.observe <db> <flow_id>` prints a correct timeline + verdict summary for a real
   finished run (verified by dogfooding it on an actual run after build).
2. Tamper a stored row → the inspector flags `✗ BROKEN at seq N` (does not crash, does not hide it).
3. Offline suite green and deterministic; the full repo suite stays green.
4. No existing `cell/*` component changed (thin: a reader + docs only).
5. README links every relevant doc; `docs/Using-a-Cell.md` lets a newcomer start, use, and observe
   a cell without reading the source.

## 10. Athletic, not skeletal

- **No fat:** one module, one job (read + interpret + format); no live tail, no query language, no
  JSON mode, no durable-trace rework. Pure core + thin CLI.
- **Not skeletal:** it *interprets* — verdict, attempts, re-derivations, exactly-once, cost, and a
  real tamper-evidence check — not a raw dump. Robust on every real failure mode (missing DB/flow,
  broken chain, absent ledger, unknown kind) instead of crashing.
