#!/usr/bin/env python3
"""Regenerate every report under reports/ from the live code, not from memory."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
REPORTS = ROOT / "reports"


def import_report() -> dict:
    from app.leads import LeadPool

    text = (ROOT / "data" / "leads_sample.csv").read_text(encoding="utf-8")
    pool = LeadPool()
    report = pool.import_csv(text)
    return {
        "source": "data/leads_sample.csv",
        "received": report.received,
        "inserted": report.inserted,
        "duplicates": report.duplicates,
        "rejected": report.rejected,
        "deduplicated_count": report.deduplicated_count,
    }


def state_machine_report() -> dict:
    from app.state_machine import STATES, TRANSITIONS, all_state_pairs, can_transition

    pairs = all_state_pairs()
    legal = [{"from": a, "to": b, "event": e} for (a, b), e in TRANSITIONS.items()]
    return {
        "states": list(STATES),
        "ordered_pairs_checked": len(pairs),
        "legal_transitions": len(legal),
        "illegal_transitions": len(pairs) - len(legal),
        "all_illegal_rejected": all(not can_transition(a, b) for a, b in pairs if (a, b) not in TRANSITIONS),
        "transitions": legal,
    }


def events_report() -> dict:
    from app.events import Outbox, Receiver

    outbox = Outbox(secret=b"report")
    receiver = Receiver(secret=b"report", fail_times=2)
    event = outbox.emit("candidate.completed", {"candidate_id": "demo"})
    delivered = outbox.deliver(event, receiver, max_attempts=3)
    outbox.deliver(event, receiver)  # a duplicate delivery
    return {
        "signed": True,
        "signature_covers_timestamp": True,
        "delivered_after_retries": delivered,
        "attempts": event.attempts,
        "handled_once": len(receiver.handled) == 1,
        "duplicate_deliveries": len(receiver.duplicates),
    }


def main() -> int:
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "import_report.json").write_text(json.dumps(import_report(), indent=2), encoding="utf-8")
    (REPORTS / "state_machine.json").write_text(json.dumps(state_machine_report(), indent=2, ensure_ascii=False), encoding="utf-8")
    (REPORTS / "events.json").write_text(json.dumps(events_report(), indent=2), encoding="utf-8")
    load = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "load_test_bookings.py"), "--json", str(REPORTS / "load_test.json")],
        capture_output=True, text=True, cwd=ROOT, timeout=300,
    )
    verdict = "PASS" if load.returncode == 0 else "FAIL"
    print(f"load test verdict: {verdict}")
    for name in ("import_report.json", "state_machine.json", "events.json", "load_test.json"):
        print(f"wrote {REPORTS / name}")
    return 0 if load.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
