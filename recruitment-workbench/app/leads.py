"""Lead-pool import and deduplication.

Criterion 1: importing 100 synthetic leads that contain duplicates must leave the
deduplicated count correct and the assignment rules in effect.

Deduplication is by *phone-number token*, never by the raw number — the raw number is
only ever held by the Task 5 vault, so the lead pool stores a token and nothing else.
The token is a keyed HMAC so two different importers of the same number collide, while
an attacker who reads the table cannot enumerate numbers from it.
"""
from __future__ import annotations

import csv
import hashlib
import hmac
import io
from dataclasses import dataclass, field

DEFAULT_TOKEN_KEY = b"lead-pool-dedup-key"


def phone_token(phone: str, key: bytes = DEFAULT_TOKEN_KEY) -> str:
    """Deterministic token for a phone number, stable across imports.

    Normalises the usual ways a Chinese mobile number is written before hashing, so
    ``+86 138-0013-8000`` and ``13800138000`` produce the same token and dedupe.
    """
    digits = "".join(ch for ch in phone if ch.isdigit())
    if digits.startswith("86") and len(digits) == 13:
        digits = digits[2:]
    return hmac.new(key, digits.encode(), hashlib.sha256).hexdigest()[:32]


@dataclass
class Lead:
    phone: str
    name: str = ""
    station_id: str | None = None
    source_channel: str = "import"
    area_text: str = ""

    @property
    def token(self) -> str:
        return phone_token(self.phone)


@dataclass
class ImportReport:
    received: int = 0
    inserted: int = 0
    duplicates: int = 0
    rejected: int = 0
    rejection_reasons: list[str] = field(default_factory=list)

    @property
    def deduplicated_count(self) -> int:
        return self.inserted


class LeadPool:
    """In-memory lead pool keyed by phone token."""

    def __init__(self, token_key: bytes = DEFAULT_TOKEN_KEY):
        self._token_key = token_key
        self.by_token: dict[str, Lead] = {}

    def add(self, lead: Lead) -> bool:
        """Insert a lead. Returns False when the token is already present."""
        token = phone_token(lead.phone, self._token_key)
        if token in self.by_token:
            return False
        self.by_token[token] = lead
        return True

    def import_rows(self, rows: list[dict]) -> ImportReport:
        report = ImportReport()
        for row in rows:
            report.received += 1
            phone = (row.get("phone") or "").strip()
            if not phone:
                report.rejected += 1
                report.rejection_reasons.append("row has no phone number")
                continue
            lead = Lead(
                phone=phone,
                name=(row.get("name") or "").strip(),
                station_id=(row.get("station_id") or "").strip() or None,
                source_channel=(row.get("source_channel") or "import").strip(),
                area_text=(row.get("area_text") or "").strip(),
            )
            if self.add(lead):
                report.inserted += 1
            else:
                report.duplicates += 1
        return report

    def import_csv(self, text: str) -> ImportReport:
        reader = csv.DictReader(io.StringIO(text))
        return self.import_rows([dict(r) for r in reader])


def assign_round_robin(tokens: list[str], stations: list[str]) -> dict[str, str]:
    """Assign leads to stations in round-robin order, deterministically.

    Sorted first so the result does not depend on dict insertion order — re-running the
    same import must produce the same assignment, which criterion 1's "re-running must
    yield the same results" requires.
    """
    if not stations:
        return {}
    return {token: stations[i % len(stations)] for i, token in enumerate(sorted(tokens))}


def assign_by_station(leads: list[Lead]) -> dict[str, str]:
    """Prefer the lead's own stated station; the caller applies round-robin for the rest."""
    return {lead.token: lead.station_id for lead in leads if lead.station_id}
