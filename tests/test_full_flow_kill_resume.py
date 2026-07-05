"""Full-flow kill-and-resume over the durable planes.

The wrapper-level crash gate (test_durable_idempotency) proves the effect ledger; this
suite proves the *whole assembled cell*: a child process runs a flow against
DurableEventStore + SqliteEffectsLedger and is hard-killed inside the Executor. A fresh
process then re-assembles the cell over the same SQLite files and re-submits the same
ticket: the flow resumes — it never re-derives the prefix (one specify decision, ever),
completes to a pass verdict, and leaves the hash chain intact.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from cell.cell import Cell
from cell.domain.objects import Verdict
from cell.effects.wrapper import SqliteEffectsLedger
from cell.observe import verify_chain
from cell.planes.memory import DurableEventStore
from tests._flow_crash_worker import FLOW_ID, TICKET

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKER = Path(__file__).resolve().parent / "_flow_crash_worker.py"


def _run_worker(events_db: str, ledger_db: str, marker: str) -> int:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(REPO_ROOT / "src"), str(REPO_ROOT)])
    proc = subprocess.run([sys.executable, str(WORKER), events_db, ledger_db, marker], env=env)
    return proc.returncode


def _stages(events, stage: str):
    return [e for e in events if e.payload.get("stage") == stage]


def test_full_flow_kill_and_resume_over_durable_planes(tmp_path):
    events_db = str(tmp_path / "events.db")
    ledger_db = str(tmp_path / "ledger.db")
    marker = str(tmp_path / "attempts.log")

    # 1. The child dies inside the Executor.
    rc = _run_worker(events_db, ledger_db, marker)
    assert rc == 1, "worker must be hard-killed mid-flow"
    with open(marker, encoding="utf-8") as f:
        assert len(f.readlines()) == 1, "exactly one execute attempt before death"

    # 2. The prefix survived the kill: specify + decompose are durable, no verdict yet.
    store = DurableEventStore(events_db)
    events = store.read(FLOW_ID)
    assert len(_stages(events, "specify")) == 1
    assert len(_stages(events, "decompose")) == 1
    assert not [e for e in events if e.kind == "verdict"]
    store.close()

    # 3. A fresh process re-assembles the cell over the same files and re-submits.
    cell = Cell.assemble(
        store=DurableEventStore(events_db),
        ledger=SqliteEffectsLedger(ledger_db),
    )
    result = cell.submit(TICKET, FLOW_ID)

    # 4. The flow completed — and resumed, never restarted.
    assert isinstance(result, Verdict)
    assert result.decision == "pass"
    after = cell.store.read(FLOW_ID)
    assert len(_stages(after, "specify")) == 1, "the prefix is never re-derived"
    assert len(_stages(after, "decompose")) == 1
    assert len([e for e in after if e.kind == "verdict"]) == 1

    # 5. The hash chain is intact across the kill/resume boundary.
    intact, broken_at = verify_chain(after)
    assert intact, f"chain broken at seq {broken_at}"
