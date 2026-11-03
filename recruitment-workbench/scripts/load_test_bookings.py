#!/usr/bin/env python3
"""Load test: 50 concurrent bookings racing for the last 5 slots at one station.

Committed with the repository, per acceptance criterion 3. Runs against the real
``BookingService`` and against the deliberately racy ``NaiveBookingService`` so the
result is a comparison rather than a single number.

Run:  python3 scripts/load_test_bookings.py [--threads 50] [--quota 5] [--json PATH]
Exit: 0 when the real service holds the quota and the naive one is shown to break it.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.booking import BookingService, NaiveBookingService, QuotaExhausted, Station


def _slow_save(_booking):
    """Stand in for the durable insert: the window between check and update."""
    time.sleep(0.001)


def race(service_factory, threads: int, quota: int) -> dict:
    station = Station(id="s1", name="西湖站", lat=30.25, lng=120.13, open_quota=quota)
    service = service_factory([station], on_save=_slow_save)
    successes: list[int] = []
    rejected: list[int] = []
    started = threading.Barrier(threads)
    lock = threading.Lock()

    def worker(i: int) -> None:
        started.wait()  # release every thread at the same instant
        try:
            service.book(f"cand{i}", "s1", "2026-11-04T09:00")
            with lock:
                successes.append(i)
        except QuotaExhausted:
            with lock:
                rejected.append(i)

    pool = [threading.Thread(target=worker, args=(i,)) for i in range(threads)]
    t0 = time.perf_counter()
    for t in pool:
        t.start()
    for t in pool:
        t.join()
    elapsed = time.perf_counter() - t0
    # The counter can be wrong *and* the bookings created can exceed the quota; the
    # number of bookings actually created is the honest measure of overselling.
    created = len(service.bookings)
    return {
        "threads": threads,
        "quota": quota,
        "successes": len(successes),
        "rejected": len(rejected),
        "station_booked": station.booked,
        "bookings_created": created,
        "oversold_by": max(0, created - quota),
        "elapsed_s": round(elapsed, 4),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threads", type=int, default=50)
    ap.add_argument("--quota", type=int, default=5)
    ap.add_argument("--repeat", type=int, default=20, help="runs for the naive comparison")
    ap.add_argument("--json", help="write the report here")
    args = ap.parse_args()

    safe = race(BookingService, args.threads, args.quota)
    print("BookingService (per-station lock):")
    for k, v in safe.items():
        print(f"  {k:16} {v}")

    naive_runs = [race(NaiveBookingService, args.threads, args.quota) for _ in range(args.repeat)]
    worst = max(r["bookings_created"] for r in naive_runs)
    broke = sum(1 for r in naive_runs if r["oversold_by"] > 0)
    print(f"\nNaiveBookingService (no lock), {args.repeat} runs:")
    print(f"  runs that oversold   {broke}/{args.repeat}")
    print(f"  worst bookings made  {worst} (quota {args.quota})")
    print(f"  median successes     {statistics.median(r['successes'] for r in naive_runs)}")

    ok = safe["successes"] == args.quota and safe["oversold_by"] == 0 and broke > 0
    print(
        f"\nVERDICT: {'PASS' if ok else 'FAIL'} - the locked service held the quota exactly"
        f" ({safe['successes']}/{args.quota}) and the unlocked one oversold in {broke}/{args.repeat} runs."
    )

    if args.json:
        report = {
            "locked": safe,
            "naive_repeat": args.repeat,
            "naive_runs_that_oversold": broke,
            "naive_worst_bookings_created": worst,
            "naive_runs": naive_runs,
            "verdict": "PASS" if ok else "FAIL",
        }
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
