"""Append-only, hash-chained audit log.

Every entry commits to the hash of the entry before it, so altering any line breaks
the chain from that point on and ``verify_chain`` names the first bad index. That is
criterion 4.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

GENESIS = "0" * 64


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


@dataclass
class AuditEntry:
    seq: int
    at: str
    actor: str
    action: str
    subject: str
    reason: str | None
    detail: dict
    prev_hash: str
    entry_hash: str

    def canonical(self) -> bytes:
        payload = {
            "seq": self.seq,
            "at": self.at,
            "actor": self.actor,
            "action": self.action,
            "subject": self.subject,
            "reason": self.reason,
            "detail": self.detail,
            "prev_hash": self.prev_hash,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

    def compute_hash(self) -> str:
        return hashlib.sha256(self.canonical()).hexdigest()


class AuditLog:
    """In-memory append-only log. Persisted through the same rows the API serves."""

    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    def append(
        self, actor: str, action: str, subject: str, reason: str | None = None, **detail
    ) -> AuditEntry:
        prev_hash = self.entries[-1].entry_hash if self.entries else GENESIS
        entry = AuditEntry(
            seq=len(self.entries) + 1,
            at=_now(),
            actor=actor,
            action=action,
            subject=subject,
            reason=reason,
            detail=detail,
            prev_hash=prev_hash,
            entry_hash="",
        )
        entry.entry_hash = entry.compute_hash()
        self.entries.append(entry)
        return entry

    def verify_chain(self, entries: list[AuditEntry] | None = None) -> tuple[bool, int | None]:
        """Return ``(ok, first_bad_index)``.

        ``first_bad_index`` is the 0-based position of the earliest entry that does not
        hash correctly or does not chain to its predecessor, or ``None`` when intact.
        """
        rows = self.entries if entries is None else entries
        prev = GENESIS
        for i, entry in enumerate(rows):
            if entry.prev_hash != prev:
                return False, i
            if entry.compute_hash() != entry.entry_hash:
                return False, i
            prev = entry.entry_hash
        return True, None

    def export(self) -> list[dict]:
        return [e.__dict__ for e in self.entries]
