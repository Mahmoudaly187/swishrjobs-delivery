#!/usr/bin/env python3
"""Mutation proof for Task 3/5: show the gate goes red, not merely green.

Each mutation removes exactly one safety property the acceptance criteria depend on.
The suite must fail on every one of them. A mutation that survives means the suite does
not actually test that property.

Run:  python3 scripts/mutation_proof.py [--json reports/mutation_proof.json]
Exit: 0 when every mutation is caught, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# (name, relative path, exact text to replace, replacement, property under test)
MUTATIONS: list[tuple[str, str, str, str, str]] = [
    (
        "remove_booking_lock",
        "app/booking.py",
        "        with self._locks[station_id]:\n            if station.booked >= station.open_quota:",
        "        if True:\n            if station.booked >= station.open_quota:",
        "the per-station lock is what prevents overselling under concurrency",
    ),
    (
        "allow_illegal_transition",
        "app/main.py",
        '    try:\n        event = event_for(candidate["status"], body.target)\n    except IllegalTransition as exc:\n        raise HTTPException(\n            status_code=409,\n            detail={\n                "code": "illegal_transition",\n                "message": str(exc),\n                "allowed": list(legal_targets(candidate["status"])),\n            },\n        ) from None\n',
        '    event = "candidate.updated"\n',
        "illegal candidate transitions must be rejected",
    ),
    (
        "disable_lead_dedup",
        "app/leads.py",
        "        if token in self.by_token:\n            return False\n",
        "        if False:\n            return False\n",
        "deduplication by phone token must drop repeated leads",
    ),
    (
        "phone_token_skips_country_code",
        "app/leads.py",
        '    if digits.startswith("86") and len(digits) == 13:\n        digits = digits[2:]\n',
        "    if False:\n        digits = digits[2:]\n",
        "equivalent phone formats must normalise to the same token",
    ),
    (
        "signature_ignores_timestamp",
        "app/events.py",
        '    mac = hmac.new(secret, timestamp.encode() + b"." + body, hashlib.sha256)',
        "    mac = hmac.new(secret, body, hashlib.sha256)",
        "the HMAC must cover the timestamp so a delivery cannot be replayed",
    ),
    (
        "delivery_handles_duplicates",
        "app/events.py",
        '        if event["event_id"] in self.seen_ids:\n            self.duplicates.append(event["event_id"])\n            return True  # acknowledge, but do not act twice\n',
        '        if event["event_id"] in self.seen_ids:\n            self.duplicates.append(event["event_id"])\n',
        "a repeat delivery must not be acted on twice",
    ),
    (
        "no_retry_on_failure",
        "app/events.py",
        "        for _ in range(max_attempts):\n            event.attempts += 1",
        "        for _ in range(1):\n            event.attempts += 1",
        "a failed delivery must be retried",
    ),
    (
        "workbench_list_unmasked",
        "app/main.py",
        '                "phone": mask_phone(c["phone"]),',
        '                "phone": c["phone"],',
        "the workbench list must be masked by default",
    ),
    (
        "reveal_without_reason",
        "app/main.py",
        '    if not body.reason.strip():\n        raise HTTPException(\n            status_code=400,\n            detail={"code": "reason_required", "message": "a reason is required to view the full number"},\n        )\n',
        "    if False:\n        pass\n",
        "viewing a full number must require a stated reason",
    ),
    (
        "drop_bearer_auth",
        "app/main.py",
        '    if not authorization or not authorization.lower().startswith("bearer "):\n        raise HTTPException(\n            status_code=401, detail={"code": "unauthenticated", "message": "a bearer token is required"}\n        )\n',
        '    if False:\n        pass\n    authorization = authorization or "Bearer anonymous"\n',
        "employee routes must require a bearer token",
    ),
    (
        "drop_watermark",
        "app/main.py",
        '    watermark = f"{employee} · {employee_id} · {today}"',
        '    watermark = ""',
        "workbench pages must carry a personal watermark",
    ),
    (
        "recommend_full_stations",
        "app/booking.py",
        "        (s for s in stations if s.remaining > 0),",
        "        (s for s in stations),",
        "a station with no remaining quota must not be recommended",
    ),
]


def _env(root: Path) -> dict:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(root)
    return env


def run_suite(root: Path) -> tuple[bool, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=root,
        capture_output=True,
        text=True,
        env=_env(root),
        timeout=600,
    )
    tail = (proc.stdout + proc.stderr).strip().splitlines()
    return proc.returncode == 0, "\n".join(tail[-3:])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="write the report here")
    args = ap.parse_args()

    baseline_ok, baseline_tail = run_suite(REPO)
    print(f"baseline (unmutated): {'PASS' if baseline_ok else 'FAIL'}")
    if not baseline_ok:
        print("  the suite must be green before mutation testing means anything")
        print("  " + baseline_tail.replace("\n", "\n  "))
        return 1

    results = []
    work = Path(tempfile.mkdtemp(prefix="workbench-mutation-"))
    try:
        for name, rel, old, new, prop in MUTATIONS:
            tree = work / name
            shutil.copytree(
                REPO,
                tree,
                ignore=shutil.ignore_patterns(".git", ".pytest_cache", "__pycache__", "reports"),
            )
            (tree / "reports").mkdir(exist_ok=True)
            target = tree / rel
            source = target.read_text(encoding="utf-8")
            if old not in source:
                results.append({"mutation": name, "file": rel, "property": prop,
                                "applied": False, "caught": None,
                                "detail": "anchor text not found - mutation not applied"})
                print(f"  {name:<32} NOT APPLIED (anchor not found in {rel})")
                continue
            target.write_text(source.replace(old, new, 1), encoding="utf-8")
            passed, tail = run_suite(tree)
            caught = not passed
            results.append({"mutation": name, "file": rel, "property": prop,
                            "applied": True, "caught": caught, "detail": tail})
            print(f"  {name:<32} {'CAUGHT' if caught else 'SURVIVED'}  ({prop})")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    applied = [r for r in results if r["applied"]]
    survived = [r for r in applied if not r["caught"]]
    report = {
        "baseline_passed": baseline_ok,
        "mutations_defined": len(MUTATIONS),
        "mutations_applied": len(applied),
        "caught": len(applied) - len(survived),
        "survived": len(survived),
        "score": f"{len(applied) - len(survived)}/{len(applied)}",
        "results": results,
    }
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nbaseline green, then {len(applied) - len(survived)}/{len(applied)} deliberate defects caught")
    if survived:
        print("SURVIVORS (the suite does not test these):")
        for r in survived:
            print(f"  - {r['mutation']}: {r['property']}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
