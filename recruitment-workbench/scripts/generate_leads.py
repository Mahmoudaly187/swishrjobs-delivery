#!/usr/bin/env python3
"""Generate the synthetic lead file used by criterion 1: 100 rows, 40 duplicates."""
from __future__ import annotations

import csv
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "leads_sample.csv"
STATIONS = ["s1", "s2", "s3"]
CHANNELS = ["douyin", "wechat", "referral", "offline"]
AREAS = ["杭州市西湖区文一西路", "杭州市余杭区仓前街道", "杭州市滨江区江南大道", "杭州市拱墅区莫干山路"]


def main() -> int:
    random.seed(20261103)  # deterministic: re-running yields the same file
    rows = []
    seen = set()
    i = 0
    while len(seen) < 60:
        phone = f"1380013{8000 + i:04d}"[:11]
        if phone in seen:
            i += 1
            continue
        seen.add(phone)
        rows.append(
            {
                "phone": phone,
                "name": f"候选人{i:03d}",
                "station_id": STATIONS[i % len(STATIONS)],
                "source_channel": CHANNELS[i % len(CHANNELS)],
                "area_text": AREAS[i % len(AREAS)],
            }
        )
        i += 1
    # 40 exact duplicates of the first 40 rows, plus two equivalent-format repeats.
    rows += [dict(r) for r in rows[:40]]
    rows.append({"phone": "+86 138-0013-8000", "name": "候选人000", "station_id": "s1", "source_channel": "wechat", "area_text": AREAS[0]})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["phone", "name", "station_id", "source_channel", "area_text"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {OUT} with {len(rows)} rows ({len(rows) - 60} duplicates)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
