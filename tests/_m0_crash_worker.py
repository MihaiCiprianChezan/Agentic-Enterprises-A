"""Crash worker for the M0 kill-and-resume gate (not a test module — note the leading _).

Run as a child process. It performs one external effect through the durable wrapper and
`os._exit(1)`s mid-effect: the `in_flight` ledger row is committed (by perform, before
execute), the effect fires, then the process dies BEFORE `completed` is recorded. The
parent test then restarts and asserts the effect ends up applied once — never twice.

Usage:  python _m0_crash_worker.py <ledger_db> <mode> <target>
  mode = "irreversible" -> target is an append-only log file (un-undoable, like a send)
  mode = "idempotent"   -> target is a sqlite db with a keyed `applied` table (repeatable)

Requires `cell` importable; the parent sets PYTHONPATH=src.
"""

from __future__ import annotations

import os
import sqlite3
import sys

from cell.domain.objects import ActorRef
from cell.effects.wrapper import (
    ActionDescriptor,
    SqliteEffectsLedger,
    make_idempotency_key,
    perform,
)
from cell.planes.governance import PermissiveGovernance


def main() -> None:
    db, mode, target = sys.argv[1], sys.argv[2], sys.argv[3]
    ledger = SqliteEffectsLedger(db)
    gov = PermissiveGovernance()
    actor = ActorRef(role="Executor", version="v0")
    key = make_idempotency_key("flow1", "the_effect", {"t": "x"})
    action = ActionDescriptor(
        id="a1",
        action_class="CLASS_EXTERNAL_COMM",
        effect_kind=mode,
        idempotency_key=key,
        intent={"t": "x"},
    )

    def execute(_action):
        if mode == "irreversible":
            with open(target, "a", encoding="utf-8") as f:
                f.write(key + "\n")
                f.flush()
                os.fsync(f.fileno())
        else:  # idempotent: a keyed, naturally repeatable effect
            conn = sqlite3.connect(target)
            conn.execute("CREATE TABLE IF NOT EXISTS applied (key TEXT PRIMARY KEY)")
            conn.execute("INSERT OR IGNORE INTO applied (key) VALUES (?)", (key,))
            conn.commit()
            conn.close()
        # Crash AFTER the effect fired but BEFORE perform() records `completed`.
        os._exit(1)

    perform(action, actor, execute, ledger, gov)


if __name__ == "__main__":
    main()
