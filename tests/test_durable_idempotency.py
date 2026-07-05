"""M0 Step 3 — the acceptance gate (Build-Spec §7; M0-Implementation-Notes Step 3).

Two parts:
  * Unit tests for the durable SqliteEffectsLedger (the same Protocol as the in-memory
    one, but it survives process death).
  * The kill-and-resume gate: a child process records `in_flight`, fires its effect, then
    `os._exit(1)` BEFORE `completed` is recorded. On restart the flow resumes and the effect
    ends up applied exactly-once (reversible) / at-most-once (irreversible) — never twice.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from cell.domain.objects import ActorRef
from cell.effects.wrapper import (
    ActionDescriptor,
    IrreversibleInFlight,
    SqliteEffectsLedger,
    make_idempotency_key,
    perform,
)
from cell.planes.governance import PermissiveGovernance

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
WORKER = Path(__file__).resolve().parent / "_m0_crash_worker.py"

KEY = make_idempotency_key("flow1", "the_effect", {"t": "x"})
ACTOR = ActorRef(role="Executor", version="v0")
GOV = PermissiveGovernance()


def _action(kind: str) -> ActionDescriptor:
    return ActionDescriptor(
        id="a1",
        action_class="CLASS_EXTERNAL_COMM",
        effect_kind=kind,
        idempotency_key=KEY,
        intent={"t": "x"},
    )


# --- durable ledger unit tests -----------------------------------------------


def test_ledger_get_absent_is_none(tmp_path):
    led = SqliteEffectsLedger(tmp_path / "led.db")
    assert led.get("nope") is None


def test_ledger_in_flight_then_completed(tmp_path):
    led = SqliteEffectsLedger(tmp_path / "led.db")
    led.put_in_flight(KEY)
    rec = led.get(KEY)
    assert rec.status == "in_flight"
    assert rec.attempts == 1
    led.mark_completed(KEY, "pr-123")
    rec = led.get(KEY)
    assert rec.status == "completed"
    assert rec.result_digest == "pr-123"


def test_ledger_put_in_flight_increments_attempts(tmp_path):
    led = SqliteEffectsLedger(tmp_path / "led.db")
    led.put_in_flight(KEY)
    led.put_in_flight(KEY)
    assert led.get(KEY).attempts == 2


def test_ledger_survives_restart(tmp_path):
    db = tmp_path / "led.db"
    led = SqliteEffectsLedger(db)
    led.put_in_flight(KEY)
    led.mark_completed(KEY, "pr-9")
    led.close()

    reopened = SqliteEffectsLedger(db)  # simulates a process restart
    rec = reopened.get(KEY)
    assert rec.status == "completed"
    assert rec.result_digest == "pr-9"


def test_ledger_mark_failed(tmp_path):
    led = SqliteEffectsLedger(tmp_path / "led.db")
    led.put_in_flight(KEY)
    led.mark_failed(KEY)
    assert led.get(KEY).status == "failed"


# --- the kill-and-resume gate ------------------------------------------------


def _run_worker(db: str, mode: str, target: str) -> int:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_DIR)
    proc = subprocess.run([sys.executable, str(WORKER), db, mode, target], env=env)
    return proc.returncode


def _count_lines(path: str) -> int:
    if not os.path.exists(path):
        return 0
    with open(path, encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def _count_applied(db: str, key: str) -> int:
    conn = sqlite3.connect(db)
    try:
        return conn.execute("SELECT COUNT(*) FROM applied WHERE key = ?", (key,)).fetchone()[0]
    finally:
        conn.close()


def test_crash_midflight_irreversible_is_at_most_once(tmp_path):
    db = str(tmp_path / "ledger.db")
    effect_file = str(tmp_path / "effects.log")

    rc = _run_worker(db, "irreversible", effect_file)
    assert rc != 0, "worker must crash mid-effect"
    assert _count_lines(effect_file) == 1, "effect fired exactly once before the crash"

    # On restart the ledger shows the in-flight record the crash left behind.
    led = SqliteEffectsLedger(db)
    assert led.get(KEY).status == "in_flight"

    # Resume: an irreversible effect in_flight must NOT be re-attempted (at-most-once).
    calls = {"n": 0}

    def execute(action):
        calls["n"] += 1
        with open(effect_file, "a", encoding="utf-8") as f:
            f.write(KEY + "\n")
        return "sent"

    with pytest.raises(IrreversibleInFlight):
        perform(_action("irreversible"), ACTOR, execute, led, GOV)

    assert calls["n"] == 0
    assert _count_lines(effect_file) == 1, "never twice"


def test_crash_midflight_idempotent_resumes_to_single_effect(tmp_path):
    db = str(tmp_path / "ledger.db")
    applied = str(tmp_path / "applied.db")

    rc = _run_worker(db, "idempotent", applied)
    assert rc != 0, "worker must crash mid-effect"
    assert _count_applied(applied, KEY) == 1, "keyed effect applied once before the crash"

    led = SqliteEffectsLedger(db)
    assert led.get(KEY).status == "in_flight"

    # Resume: idempotent effect is safe to re-attempt; its keyed target stays single.
    def execute(action):
        conn = sqlite3.connect(applied)
        conn.execute("INSERT OR IGNORE INTO applied (key) VALUES (?)", (KEY,))
        conn.commit()
        conn.close()
        return "done"

    result = perform(_action("idempotent"), ACTOR, execute, led, GOV)
    assert result == "done"
    assert _count_applied(applied, KEY) == 1, "exactly-once end state, never twice"
    assert led.get(KEY).status == "completed"

    # A further resume returns the cached result and does not execute again.
    calls = {"n": 0}

    def execute2(action):
        calls["n"] += 1
        return "again"

    again = perform(_action("idempotent"), ACTOR, execute2, led, GOV)
    assert again == "done"
    assert calls["n"] == 0
    assert _count_applied(applied, KEY) == 1
