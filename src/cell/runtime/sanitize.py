"""Validation of intent values that reach subprocess argv.

Every runtime subprocess call already uses list-argv (never a shell), so the residual risk
is argument-as-option injection: a branch like "--force" or a refspec like "main:main"
arriving through an intent dict and being parsed by git/gh as an option instead of a value.
Intents cross the durable ledger and may be replayed on resume (M0), so they are validated
at the effect site — the outside world is never assumed idempotent, and never assumed benign
(invariant #4).
"""

from __future__ import annotations

import os
import re

# Allowlist: must start alphanumeric (bans leading "-" option injection and leading "."),
# then git-ref-safe characters only — no ":" (refspec), no whitespace/control, no "~^?*[\".
_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/\-]*$")


class UnsafeIntent(ValueError):
    """An intent value that must not reach a subprocess argv — surfaced, never executed."""


def safe_branch(name: object) -> str:
    """Return `name` iff it is a plain, option-safe git branch name; raise otherwise."""
    if (
        not isinstance(name, str)
        or not _BRANCH_RE.match(name)
        or ".." in name
        or "//" in name
        or name.endswith("/")
        or name.endswith(".lock")
    ):
        raise UnsafeIntent(f"unsafe branch name: {name!r}")
    return name


def safe_repo_dir(path: object) -> str:
    """Return `path` iff it is an existing directory; raise otherwise."""
    if not isinstance(path, str) or not os.path.isdir(path):
        raise UnsafeIntent(f"repo_dir is not an existing directory: {path!r}")
    return path


def safe_text(value: object, field: str) -> str:
    """Return `value` iff it is a str (a single argv element is otherwise inert); raise otherwise."""
    if not isinstance(value, str):
        raise UnsafeIntent(f"{field} must be a string, got {type(value).__name__}")
    return value
