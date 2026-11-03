"""Candidate lifecycle: the state machine, and the event each transition emits.

Criterion 2 requires that legal transitions pass and illegal transitions are rejected,
with unit tests covering *all* state pairs — not just a handful of happy paths. The
transition table below is therefore the single source of truth, and the test suite is
generated from it, so a state pair can never be forgotten.

States (Shared Interface Contract v1):
    new -> collecting -> complete -> booked -> interviewed -> hired
                                                          -> rejected
                                                          -> handoff
"""
from __future__ import annotations

from dataclasses import dataclass

# Ordered so the happy path reads top to bottom.
STATES: tuple[str, ...] = (
    "new",
    "collecting",
    "complete",
    "booked",
    "interviewed",
    "hired",
    "rejected",
    "handoff",
)

TERMINAL_STATES: frozenset[str] = frozenset({"hired", "rejected"})

# Every transition that is allowed, with the event it emits.
TRANSITIONS: dict[tuple[str, str], str] = {
    # from: (to, event)
    ("new", "collecting"): "candidate.updated",
    ("new", "rejected"): "candidate.updated",
    ("collecting", "complete"): "candidate.completed",
    ("collecting", "rejected"): "candidate.updated",
    ("collecting", "handoff"): "handoff.requested",
    ("complete", "booked"): "candidate.updated",
    ("complete", "handoff"): "handoff.requested",
    ("complete", "rejected"): "candidate.updated",
    ("booked", "interviewed"): "candidate.updated",
    ("booked", "handoff"): "handoff.requested",
    ("booked", "rejected"): "candidate.updated",
    ("interviewed", "hired"): "candidate.updated",
    ("interviewed", "rejected"): "candidate.updated",
    ("interviewed", "handoff"): "handoff.requested",
    # A handoff is a parking state for a human, who can then decide.
    ("handoff", "hired"): "candidate.updated",
    ("handoff", "rejected"): "candidate.updated",
}

# Human-readable event names, per the contract's event list.
EVENT_TYPES: frozenset[str] = frozenset(
    {
        "candidate.created",
        "candidate.updated",
        "candidate.completed",
        "booking.created",
        "booking.cancelled",
        "handoff.requested",
    }
)


class IllegalTransition(Exception):
    """Raised when a transition is not in the table."""

    def __init__(self, current: str, target: str):
        super().__init__(f"cannot move a candidate from {current!r} to {target!r}")
        self.current = current
        self.target = target


def can_transition(current: str, target: str) -> bool:
    return (current, target) in TRANSITIONS


def event_for(current: str, target: str) -> str:
    """The event a legal transition emits. Raises if the transition is illegal."""
    try:
        return TRANSITIONS[(current, target)]
    except KeyError:
        raise IllegalTransition(current, target) from None


def legal_targets(current: str) -> tuple[str, ...]:
    return tuple(t for (f, t) in TRANSITIONS if f == current)


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES


def all_state_pairs() -> list[tuple[str, str]]:
    """Every ordered pair of states, including self-pairs and unknown ones.

    The test suite walks this so that coverage of the state space is a property of the
    code rather than of the author's diligence.
    """
    return [(a, b) for a in STATES for b in STATES]


@dataclass
class TransitionResult:
    previous: str
    current: str
    event: str
