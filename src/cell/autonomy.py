"""Graduating autonomy — Board-ratified amendments to the authority ceilings (M6).

Realizes One-Cell-Build-Plan §6 M6. Autonomy levels start conservative (Constitution Art. 4)
and are raised only on observed evidence, and only by a Board-ratified amendment (Art. 4.1,
8.3). Performance earns a *proposal*; only the Board turns a proposal into a rule (Art. 8.4;
invariant #10 — agents never author their own constraints).

A promotion therefore never happens automatically: the Observability/Auditor surface a
`PromotionProposal`, and the Board `ratify`s it, which re-compiles the governance registry and
records the amendment on the Board-acts audit trail (Art. 8.3, 10.2; tamper-evident per R12).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from cell.domain.objects import ActorRef, Level
from cell.planes.governance import ACTION_CLASS_REGISTRY, NOVEL_LEVEL

# The Board-acts audit trail, kept separate from any role flow (Constitution Art. 10.2).
BOARD_TRAIL = "board"

# Autonomy ascends L0 < L1 < L2 < L3; a graduation must strictly increase it.
_AUTONOMY = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}


@dataclass(frozen=True)
class PromotionProposal:
    """A proposed raise of one action class's ceiling, surfaced by Observability/Auditor
    (Art. 8.4). It is only a proposal until the Board ratifies it."""

    action_class: str
    from_level: Level
    to_level: Level
    evidence: str
    proposed_by: ActorRef


class AmendmentRefused(Exception):
    """A ratification that is not the Board's, or not backed by evidence — refused and logged
    (Constitution Art. 8.2, 8.4; invariant #10)."""


class AutonomyBoard:
    """The Board's amendment authority over the autonomy ceilings. Construct it with the
    authorized Board member identities (the constitution's Art. 8.2 decision rule) and the
    durable store that carries the Board-acts trail."""

    def __init__(
        self, *, members: set[str], store: Any, registry: dict[str, Level] = ACTION_CLASS_REGISTRY
    ) -> None:
        self._members = set(members)
        self._store = store
        # The cell's CURRENT ceilings (a frozen snapshot) — proposals and ratification are
        # judged against these, not the module global, so an already-amended cell stays
        # consistent. After a ratified amendment, build a new Board on the amended registry.
        self._registry = MappingProxyType(dict(registry))

    def _level_of(self, action_class: str) -> Level:
        return self._registry.get(action_class, NOVEL_LEVEL)

    def propose(
        self, action_class: str, to_level: Level, evidence: str, proposed_by: ActorRef
    ) -> PromotionProposal:
        """Surface a promotion proposal (Art. 8.4). Recorded on the Board trail, but it changes
        nothing — only `ratify` applies it."""
        proposal = PromotionProposal(
            action_class=action_class,
            from_level=self._level_of(action_class),
            to_level=to_level,
            evidence=evidence,
            proposed_by=proposed_by,
        )
        self._store.append(
            BOARD_TRAIL,
            "decision",
            proposed_by,
            {
                "stage": "promotion_proposal",
                "action_class": action_class,
                "from": proposal.from_level,
                "to": to_level,
                "evidence": evidence,
            },
        )
        return proposal

    def ratify(self, proposal: PromotionProposal, ratifier: ActorRef) -> dict[str, Level]:
        """The Board turns a proposal into a rule. Returns the re-compiled registry (build a
        fresh RuleSetGovernance from it). Refuses — and logs the block — unless the ratifier is
        the Board, the proposal carries evidence, is consistent with the current ceiling, and is
        a genuine raise (Art. 8.2/8.4; invariant #10)."""
        if not self._is_board(ratifier):
            self._block(ratifier, proposal, "only the Board may ratify an amendment (Art. 8.2)")
            raise AmendmentRefused("only the Board may ratify an autonomy amendment (Art. 8.2)")
        if not proposal.evidence:
            self._block(
                ratifier, proposal, "a promotion must be earned on observed evidence (Art. 8.4)"
            )
            raise AmendmentRefused("a promotion must be earned on observed evidence (Art. 8.4)")

        current = self._level_of(proposal.action_class)
        if proposal.from_level != current:
            self._block(
                ratifier,
                proposal,
                f"stale proposal: from_level {proposal.from_level} != current ceiling {current}",
            )
            raise AmendmentRefused(
                f"stale proposal: from_level {proposal.from_level} does not match current {current}"
            )
        if _AUTONOMY[proposal.to_level] <= _AUTONOMY[current]:
            self._block(
                ratifier,
                proposal,
                f"not a graduation: {current} -> {proposal.to_level} does not raise autonomy",
            )
            raise AmendmentRefused(
                f"not a graduation: {current} -> {proposal.to_level} does not raise autonomy"
            )

        amended = dict(self._registry)
        amended[proposal.action_class] = proposal.to_level
        # The amendment itself is a governed, audited artifact on the Board-acts trail.
        self._store.append(
            BOARD_TRAIL,
            "governance",
            ratifier,
            {
                "stage": "amendment",
                "decision": "ratified",
                "clause": "Art. 8.3",
                "action_class": proposal.action_class,
                "from": proposal.from_level,
                "to": proposal.to_level,
                "evidence": proposal.evidence,
            },
        )
        return amended

    def ratify_amendment(self, article: str, content: dict, ratifier: ActorRef) -> dict:
        """Ratify a constitutional-*content* amendment (e.g. the version-suspension policy, Art. 11) —
        distinct from the ceiling-raise `ratify`: this content is read by the Auditor, not the
        governance gate, so there is no registry to re-compile. Authorized by the Board (Art. 8.2),
        logged on the Board-acts trail (Art. 8.3); a non-Board ratifier is refused and the refusal
        recorded (invariant #10)."""
        if not self._is_board(ratifier):
            self._store.append(
                BOARD_TRAIL,
                "governance",
                ratifier,
                {
                    "stage": "amendment",
                    "decision": "block",
                    "clause": "Art. 8.2",
                    "article": article,
                    "reason": "only the Board may ratify an amendment (Art. 8.2)",
                },
            )
            raise AmendmentRefused(
                "only the Board may ratify a constitutional amendment (Art. 8.2)"
            )
        # Deep-copy so a later mutation of the caller's dict cannot alter the recorded act (the
        # payload is re-hashed by verify_chain — a shared reference would break tamper-evidence).
        self._store.append(
            BOARD_TRAIL,
            "governance",
            ratifier,
            {
                "stage": "amendment",
                "decision": "ratified",
                "clause": "Art. 8.3",
                "article": article,
                "content": copy.deepcopy(content),
            },
        )
        return (
            content  # the stored record is an independent deep copy; the caller keeps its own dict
        )

    def _is_board(self, actor: ActorRef) -> bool:
        return getattr(actor, "mode", "agent") == "human" and actor.version in self._members

    def _block(self, ratifier: ActorRef, proposal: PromotionProposal, reason: str) -> None:
        self._store.append(
            BOARD_TRAIL,
            "governance",
            ratifier,
            {
                "stage": "amendment",
                "decision": "block",
                "clause": "Art. 8",
                "action_class": proposal.action_class,
                "from": proposal.from_level,
                "to": proposal.to_level,
                "evidence": proposal.evidence,
                "reason": reason,
            },
        )
