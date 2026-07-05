"""Delivery — open the PR as the cell's one external effect, through perform().

The agent produced the change; the cell hands it back. Routing the open-PR through perform()
against the cell's durable ledger makes it exactly-once: a crash/resume never opens a second PR
(invariant #4 / M0). The real `gh` mechanics live in open_pr_effect (exercised live); the
idempotency that matters is tested here with a fake effect.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from cell.domain.objects import ActorRef
from cell.effects.wrapper import ActionDescriptor, make_idempotency_key, perform
from cell.runtime.sanitize import safe_branch, safe_repo_dir, safe_text

if TYPE_CHECKING:  # type-only; the composition root imports nothing from the runtime
    from cell.cell import Cell

DELIVERY_ACTOR = ActorRef(role="Executor", version="real-cli")


def open_pr_effect(intent: dict[str, Any]) -> str:
    """Push the branch and open a PR; return the PR URL. Real external effect (live only).

    The intent is validated here, at the effect site, because it may arrive via ledger
    replay on resume — not only from the caller that built it."""
    repo_dir = safe_repo_dir(intent["repo_dir"])
    branch = safe_branch(intent["branch"])
    title = safe_text(intent["title"], "title")
    body = safe_text(intent["body"], "body")
    subprocess.run(
        ["git", "push", "-u", "origin", branch],
        cwd=repo_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    proc = subprocess.run(
        [
            "gh",
            "pr",
            "create",
            "--head",
            branch,
            "--title",
            title,
            "--body",
            body,
        ],
        cwd=repo_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def deliver_on_pass(
    cell: Cell,
    flow_id: str,
    branch: str,
    *,
    actor: ActorRef,
    title: str,
    body: str,
    repo_dir: str,
    effect: Callable[[dict[str, Any]], str] = open_pr_effect,
) -> str:
    """Open the PR for `branch` exactly-once via the cell's wrapper. Call only on a pass verdict."""
    key = make_idempotency_key(flow_id, "open_pr", {"branch": branch})
    action = ActionDescriptor(
        id=f"deliver-{flow_id}-{branch}",
        action_class="CLASS_VISIBLE_OUTPUT",
        # a PR is a non-idempotent outside effect -> irreversible (at-most-once); a crash
        # mid-create escalates on resume, never opening a second PR
        effect_kind="irreversible",
        idempotency_key=key,
        intent={"branch": branch, "title": title, "body": body, "repo_dir": repo_dir},
    )
    return perform(
        action,
        actor,
        lambda a: effect(a.intent),
        cell.ledger,
        cell.governance,
        store=cell.store,
        flow_id=flow_id,
    )
