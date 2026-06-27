# Runtime package — binding a real CLI agent (sub-project B)

The cell drives a real CLI coding agent through the Executor seat. The code here is built and
tested **offline and deterministically** (a `FakeRunner`, temp git repos, fake effects). The
**live** demonstration is opt-in and performs real external actions — run it yourself; it is
never part of CI and is never run by automated agents.

## The faithful split
- The agent (default: Claude Code, `claude -p`) **produces the change** on a working branch.
- The cell **verifies** it (runs the target's tests) and **opens the PR** through `perform()` —
  exactly-once, so a crash/resume never opens two PRs. The cell never merges (L0).

## Running the live slice (manual, opt-in)

1. **Scaffold a sandbox repo** (disposable): a tiny Python package with one failing pytest test
   that fully specifies a small change (the "ticket"), e.g. `slugify()`. Push it to GitHub:
   `gh repo create <you>/cell-sandbox --public --source . --push`.
2. **Clone it locally** and note the path → `CELL_TARGET_DIR`.
3. **Install + authenticate** the agent CLI (`claude`) and `gh` on this machine.
4. **Run it:**
   ```bash
   CELL_LIVE=1 CELL_TARGET_DIR=/path/to/cell-sandbox \
     CELL_TASK="Implement slugify() in src/... so tests/test_slug.py passes." \
     CELL_BRANCH="cell/slice" \
     python -m cell.live
   ```
   (`CELL_BRANCH` is optional; defaults to `cell/slice` — the working branch name.)
5. **Result:** the agent edits a branch, the cell runs the tests, and on green it prints the PR
   URL. Re-running (or resuming after a kill) opens **no** second PR — the `perform()`/durable
   ledger guarantee on a real GitHub side effect.
6. **Note:** the cell keeps its durable state file **beside** the target checkout (outside the
   git tree), named `<target>.cell-state.db` — so it is never staged or committed and no
   `.gitignore` entry is needed.

## Selecting another runtime
Swap the spec: `CliAgentRunner(CliAgentSpec.codex())` (or `.gemini()` / `.pi()`). Those presets
are config-ready and run through the same runner; confirm their flags on first use (CLIs evolve
fast) and ensure that CLI is installed/authenticated. Claude Code is the live-verified default.
