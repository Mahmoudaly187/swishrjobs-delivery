"""Transactional outbox with HMAC-signed webhook delivery.

Criterion 4: every state change emits an event, webhooks carry an HMAC-SHA256
signature, failures are retried, and duplicate delivery is idempotent.

The three properties are separated on purpose:

* **Signed.** The signature covers ``<timestamp>.<body>`` rather than the body alone,
  so a captured delivery cannot be replayed later — the receiver rejects a stale
  timestamp even though the signature is valid. Signing the bare body, the common
  shortcut, does not have this property.
* **Retried.** Delivery attempts are bounded and recorded, so a failing receiver is
  visible instead of silently dropped.
* **Idempotent.** Each event carries a stable ``event_id``; a receiver that has already
  processed that id must not act twice. The test asserts the receiver sees a repeat
  delivery and the handler runs once.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass, field

SIGNATURE_HEADER = "X-Signature-256"
TIMESTAMP_HEADER = "X-Timestamp"


def sign(secret: bytes, timestamp: str, body: bytes) -> str:
    """HMAC-SHA256 over ``<timestamp>.<body>``, hex encoded, ``sha256=`` prefixed."""
    mac = hmac.new(secret, timestamp.encode() + b"." + body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def verify(secret: bytes, timestamp: str, body: bytes, signature: str, tolerance_s: int = 300) -> bool:
    """Verify a signature and reject a stale timestamp."""
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(time.time() - ts) > tolerance_s:
        return False
    return hmac.compare_digest(sign(secret, timestamp, body), signature)


@dataclass
class Event:
    event_id: str
    type: str
    payload: dict
    attempts: int = 0
    delivered: bool = False
    last_error: str = ""
    deliveries: int = 0

    def body(self) -> bytes:
        # event_id is inside the signed body so a receiver can dedupe on it.
        return json.dumps(
            {"event_id": self.event_id, "type": self.type, "payload": self.payload},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()


class Outbox:
    """Append-only outbox. Events are written before any delivery is attempted."""

    def __init__(self, secret: bytes = b"webhook-signing-secret"):
        self.secret = secret
        self.events: list[Event] = []

    def emit(self, event_type: str, payload: dict) -> Event:
        event = Event(event_id=str(uuid.uuid4()), type=event_type, payload=payload)
        self.events.append(event)
        return event

    def signed_request(self, event: Event, timestamp: str | None = None) -> tuple[dict, bytes]:
        ts = timestamp or str(int(time.time()))
        body = event.body()
        headers = {
            "Content-Type": "application/json",
            TIMESTAMP_HEADER: ts,
            SIGNATURE_HEADER: sign(self.secret, ts, body),
        }
        return headers, body

    def deliver(self, event: Event, transport, max_attempts: int = 3) -> bool:
        """Deliver one event, retrying on failure.

        ``transport(headers, body) -> bool`` is the thing being tested; it returns
        True on success. Returns whether the event was delivered.
        """
        for _ in range(max_attempts):
            event.attempts += 1
            headers, body = self.signed_request(event)
            try:
                if transport(headers, body):
                    event.delivered = True
                    event.last_error = ""
                    return True
                event.last_error = "transport returned failure"
            except Exception as exc:  # a failing receiver must not crash the outbox
                event.last_error = f"{type(exc).__name__}: {exc}"
        return False

    def flush(self, transport, max_attempts: int = 3) -> dict:
        delivered = failed = 0
        for event in self.events:
            if event.delivered:
                continue
            if self.deliver(event, transport, max_attempts):
                delivered += 1
            else:
                failed += 1
        return {"delivered": delivered, "failed": failed}


class Receiver:
    """A receiver that verifies the signature and deduplicates by event_id."""

    def __init__(self, secret: bytes, fail_times: int = 0):
        self.secret = secret
        self.fail_times = fail_times
        self.received: list[dict] = []
        self.seen_ids: set[str] = set()
        self.handled: list[str] = []      # events actually acted on
        self.duplicates: list[str] = []
        self.rejected: list[str] = []
        self.calls = 0

    def __call__(self, headers: dict, body: bytes) -> bool:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ConnectionError("receiver unavailable")
        if not verify(
            self.secret,
            headers.get(TIMESTAMP_HEADER, ""),
            body,
            headers.get(SIGNATURE_HEADER, ""),
        ):
            self.rejected.append(headers.get(TIMESTAMP_HEADER, ""))
            return False
        event = json.loads(body)
        self.received.append(event)
        if event["event_id"] in self.seen_ids:
            self.duplicates.append(event["event_id"])
            return True  # acknowledge, but do not act twice
        self.seen_ids.add(event["event_id"])
        self.handled.append(event["event_id"])
        return True
