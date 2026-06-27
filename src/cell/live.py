"""The live real-slice runner (python -m cell.live). OPT-IN and env-gated — it performs real
external actions (a real CLI-agent run and a real PR), so it never runs in the test suite.

Required env when CELL_LIVE=1:
  CELL_TARGET_DIR   absolute path to a local checkout of the sandbox repo (with a GitHub remote)
  CELL_TASK         the ticket text (the change to make)
Optional:
  CELL_BRANCH       working branch name (default: cell/slice)

See src/cell/runtime/README.md for the full runbook.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

from cell.cell import Cell
from cell.domain.objects import Ticket
from cell.effects.wrapper import SqliteEffectsLedger
from cell.handbrake import Paused
from cell.planes.memory import DurableEventStore
from cell.runtime.deliver import DELIVERY_ACTOR, deliver_on_pass
from cell.runtime.real_executor import RealExecutor
from cell.runtime.real_verifier import RealVerifier
from cell.runtime.runner import CliAgentRunner, CliAgentSpec


def main() -> None:
    if os.environ.get("CELL_LIVE") != "1":
        print("Live slice is opt-in. Set CELL_LIVE=1 plus CELL_TARGET_DIR and CELL_TASK to run "
              "it (see src/cell/runtime/README.md). It performs a real CLI-agent run and opens a "
              "real PR, so it is never part of the test suite.")
        return

    target = os.environ.get("CELL_TARGET_DIR")
    task = os.environ.get("CELL_TASK")
    if not target or not task:
        print("error: CELL_TARGET_DIR and CELL_TASK are required when CELL_LIVE=1.", file=sys.stderr)
        raise SystemExit(2)
    branch = os.environ.get("CELL_BRANCH", "cell/slice")
    state_db = os.path.abspath(target).rstrip("/\\") + ".cell-state.db"

    cell = Cell.assemble(
        executor=RealExecutor(CliAgentRunner(CliAgentSpec.claude_code()), target, branch),
        verifier=RealVerifier(target),
        store=DurableEventStore(state_db), ledger=SqliteEffectsLedger(state_db))

    ticket = Ticket(id="live-1", source="cli", title=task[:60], body=task,
                    received_at=datetime.now(timezone.utc))
    verdict = cell.submit(ticket, "live-1")
    if isinstance(verdict, Paused):
        print(f"paused at {verdict.step}: {verdict.reason} — inspect via the handbrake.")
        return
    if verdict.decision != "pass":
        print(f"verification did not pass ({verdict.decision}): {verdict.reason}")
        return

    url = deliver_on_pass(cell, "live-1", branch, actor=DELIVERY_ACTOR,
                          title=f"cell: {task[:60]}", body="Opened by the agent-native cell.",
                          repo_dir=target)
    print(f"PASS — pull request opened: {url}")


if __name__ == "__main__":
    main()
