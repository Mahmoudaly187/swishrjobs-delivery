"""Data retention: expiry and consent withdrawal.

Criterion 5 needs three things proven: expired data is deleted or anonymized with a
deletion record, consent withdrawal deletes immediately, and a time fast-forward
drives the cleanup task. Time is therefore injected rather than read from the clock.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Record:
    token: str
    city: str
    station: str
    created_at: datetime
    consent: bool = True
    anonymized: bool = False
    deleted: bool = False
    # Sealed fields are dropped on delete/anonymize; kept as a dict for the demo.
    sealed: dict = field(default_factory=dict)


@dataclass
class DeletionRecord:
    token: str
    at: str
    mode: str          # "deleted" | "anonymized"
    trigger: str       # "retention" | "consent_withdrawal"
    detail: str = ""


class RetentionPolicy:
    """Retention window plus the cleanup pass.

    ``retention_days`` is the maximum age of an identifiable record. Records past it
    are anonymized (PII stripped, aggregate kept) rather than silently dropped, which
    preserves recruiting statistics while satisfying "deleted or anonymized".
    """

    def __init__(self, retention_days: int = 180):
        self.retention_days = retention_days
        self.deletions: list[DeletionRecord] = []

    def is_expired(self, record: Record, now: datetime) -> bool:
        return now - record.created_at > timedelta(days=self.retention_days)

    def run_cleanup(self, records: list[Record], now: datetime | None = None) -> list[DeletionRecord]:
        now = now or utcnow()
        produced: list[DeletionRecord] = []
        for record in records:
            if record.deleted or record.anonymized:
                continue
            if not record.consent:
                record.sealed.clear()
                record.deleted = True
                rec = DeletionRecord(
                    token=record.token,
                    at=now.isoformat(timespec="microseconds"),
                    mode="deleted",
                    trigger="consent_withdrawal",
                    detail="consent withdrawn: identifiable data erased immediately",
                )
            elif self.is_expired(record, now):
                record.sealed.clear()
                record.anonymized = True
                rec = DeletionRecord(
                    token=record.token,
                    at=now.isoformat(timespec="microseconds"),
                    mode="anonymized",
                    trigger="retention",
                    detail=f"older than {self.retention_days} days",
                )
            else:
                continue
            self.deletions.append(rec)
            produced.append(rec)
        return produced

    def withdraw_consent(self, record: Record, now: datetime | None = None) -> DeletionRecord:
        """Immediate deletion on withdrawal, independent of the retention window."""
        now = now or utcnow()
        record.consent = False
        return self.run_cleanup([record], now=now)[0]
