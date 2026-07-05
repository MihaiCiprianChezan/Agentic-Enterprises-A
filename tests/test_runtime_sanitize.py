"""Runtime intent sanitization — hostile intent values must be rejected BEFORE any
subprocess is spawned (argument-as-option injection: all runtime calls are list-argv,
so a value like "--force" being parsed as an option is the residual attack surface).
Offline: no git, no gh, no LLM.
"""

from __future__ import annotations

import pytest

from cell.runtime import deliver
from cell.runtime.sanitize import UnsafeIntent, safe_branch, safe_repo_dir, safe_text

HOSTILE_BRANCHES = [
    "--force",  # option injection
    "-B",  # option injection
    "main:main",  # refspec — would push to another branch
    "a..b",  # rev-range syntax
    "a b",  # whitespace
    "a\nb",  # control character
    "",  # empty
    ".hidden",  # leading dot
    "~/x",  # home expansion / rev syntax
    "x^",  # rev syntax
    "feat//x",  # empty path segment
    "feat/",  # trailing slash
    "feat.lock",  # git refuses *.lock refs
    "a?b",  # glob
    123,  # not a string
    None,  # not a string
]

GOOD_BRANCHES = ["main", "cell/slice-1", "feature/x_y.z", "release/1.2.3", "a"]


@pytest.mark.parametrize("bad", HOSTILE_BRANCHES)
def test_hostile_branch_names_are_rejected(bad):
    with pytest.raises(UnsafeIntent):
        safe_branch(bad)


@pytest.mark.parametrize("good", GOOD_BRANCHES)
def test_plain_branch_names_pass_through(good):
    assert safe_branch(good) == good


def test_repo_dir_must_exist(tmp_path):
    assert safe_repo_dir(str(tmp_path)) == str(tmp_path)
    with pytest.raises(UnsafeIntent):
        safe_repo_dir(str(tmp_path / "absent"))
    with pytest.raises(UnsafeIntent):
        safe_repo_dir(None)


def test_safe_text_rejects_non_strings():
    assert safe_text("ok", "title") == "ok"
    with pytest.raises(UnsafeIntent):
        safe_text(["x"], "title")


def test_open_pr_effect_rejects_hostile_intent_before_any_subprocess(tmp_path, monkeypatch):
    """The effect site is the last line of defense: a hostile intent replayed from the
    ledger must raise before a single process is spawned."""

    def _no_spawn(*args, **kwargs):
        raise AssertionError("subprocess must not be spawned for a hostile intent")

    monkeypatch.setattr(deliver.subprocess, "run", _no_spawn)
    hostile = {
        "repo_dir": str(tmp_path),
        "branch": "--force",
        "title": "t",
        "body": "b",
    }
    with pytest.raises(UnsafeIntent):
        deliver.open_pr_effect(hostile)


def test_real_executor_rejects_a_hostile_branch_at_construction():
    from cell.runtime.real_executor import RealExecutor

    with pytest.raises(UnsafeIntent):
        RealExecutor(runner=object(), checkout_dir=".", branch="main:main")
