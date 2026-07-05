"""Child process for test_full_flow_kill_resume: run a full Cell flow over the durable
planes (DurableEventStore + SqliteEffectsLedger) and die hard (os._exit) inside the
Executor — after the prefix decisions are durably recorded, before any verdict.

Usage: python _flow_crash_worker.py <events_db> <ledger_db> <marker_file>
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime

from cell.cell import Cell
from cell.domain.objects import Output, Ticket, WorkItem
from cell.effects.wrapper import SqliteEffectsLedger
from cell.planes.memory import DurableEventStore
from cell.roles.reference import EXECUTOR

FLOW_ID = "flow-kill"
TICKET = Ticket(
    id="t-kill",
    source="test",
    title="kill and resume",
    body="crash mid-execute",
    received_at=datetime(2026, 1, 1, tzinfo=UTC),
)


class CrashingExecutor:
    """Records the attempt, then dies without cleanup — a real process kill, not an exception."""

    actor = EXECUTOR

    def __init__(self, marker_file: str) -> None:
        self.marker_file = marker_file

    def execute(self, item: WorkItem) -> Output:
        with open(self.marker_file, "a", encoding="utf-8") as f:
            f.write("execute-attempt\n")
        os._exit(1)


def main() -> None:
    events_db, ledger_db, marker_file = sys.argv[1], sys.argv[2], sys.argv[3]
    cell = Cell.assemble(
        store=DurableEventStore(events_db),
        ledger=SqliteEffectsLedger(ledger_db),
        executor=CrashingExecutor(marker_file),
    )
    cell.submit(TICKET, FLOW_ID)


if __name__ == "__main__":
    main()
