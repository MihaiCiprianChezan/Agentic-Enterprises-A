# Final Review Fixes Report

Date: 2026-06-27

## Fixes Applied

### Fix 1 — audit `attempt` field in handbrake revise loop
File: `src/cell/handbrake.py`, method `_do_item`
Added `"attempt": attempt` to both the `store.append` call for the execute event (action)
and the verify event (verdict). Mirrors the existing `flow._produce_and_verify` pattern.

### Fix 2 — remove unused `Output` import
File: `tests/test_e2e_composition.py`
Removed `Output` from the `from cell.domain.objects import ...` line.
Confirmed `Output` is not referenced anywhere else in that file.

### Fix 3 — consolidate duplicate imports in the demo
File: `src/cell/demo.py`
Merged two separate `from cell.effects.wrapper import ...` lines into one:
`from cell.effects.wrapper import GovernanceBlocked, InMemoryEffectsLedger`

### Fix 4 — type the `Cell.inject` actor parameter
File: `src/cell/cell.py`
Annotated `actor` parameter as `actor: ActorRef`.
Added `ActorRef` to the existing `from cell.domain.objects import ...` line.

### Fix 5 — clarify `Cell.governance_log` docstring
File: `src/cell/cell.py`
Added docstring:
`"""All governance-plane events for the flow — both the _govern action-site gate decisions and any R11 injection blocks."""`

## Commands Run and Output

### Targeted tests (covering changed code)
```
python -m pytest tests/test_m4_handbrake.py tests/test_e2e_composition.py -o addopts="" -q
```
Output:
```
........................                                                 [100%]
24 passed in 0.09s
```

### Full suite
```
python -m pytest -o addopts="" -q
```
Output:
```
........................................................................[ 67%]
..................................                                       [100%]
106 passed in 0.77s
```

### Demo run
```
python -m cell.demo
```
Output: All 5 scenarios printed successfully:
1. Routine path — autonomous (L2, no human): verdict: pass
2. Dramatic path — handbrake takeover (L1): paused, injected, resumed pass
3. Kill-and-resume — exactly-once across a fresh controller: 1 execution
4. Out-of-policy — L0 action blocked and traced to a clause: blocked with R1 Art. 4
5. Steward — induced loop quarantined before the budget cap: quarantine R8
