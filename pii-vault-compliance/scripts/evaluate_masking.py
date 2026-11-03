#!/usr/bin/env python3
"""Measure masking recall and false-positive rate against the synthetic corpus.

Recall per field is the fraction of injected values the masker actually replaced.
The false-positive rate is the fraction of negative samples in which anything was
replaced at all, reported both overall and as the count of spurious spans per sample.

Run:  python3 scripts/evaluate_masking.py [--json]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pii_vault.masking import Masker  # noqa: E402

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "samples.jsonl"


def normalize(value: str) -> str:
    """Compare on content, not on formatting: spaces/hyphens are presentation."""
    return "".join(ch for ch in value if ch.isalnum() or "\u4e00" <= ch <= "\u9fff").lower()


def evaluate() -> dict:
    masker = Masker()
    rows = [json.loads(line) for line in SAMPLES.read_text(encoding="utf-8").splitlines() if line.strip()]

    per_kind_total: dict[str, int] = {}
    per_kind_hit: dict[str, int] = {}
    fp_samples = 0
    fp_spans = 0
    negatives = 0

    for row in rows:
        result = masker.mask(row["text"])
        found = {normalize(s.text) for s in result.spans}
        if row["label"] == "positive":
            for kind, value in row["expected"].items():
                per_kind_total[kind] = per_kind_total.get(kind, 0) + 1
                if normalize(value) in found:
                    per_kind_hit[kind] = per_kind_hit.get(kind, 0) + 1
        else:
            negatives += 1
            if result.spans:
                fp_samples += 1
                fp_spans += len(result.spans)

    recall = {
        kind: round(per_kind_hit.get(kind, 0) / total, 4) for kind, total in sorted(per_kind_total.items())
    }
    return {
        "samples": len(rows),
        "positives": len(rows) - negatives,
        "negatives": negatives,
        "per_field_recall": recall,
        "per_field_support": dict(sorted(per_kind_total.items())),
        "false_positive_samples": fp_samples,
        "false_positive_rate": round(fp_samples / negatives, 4) if negatives else 0.0,
        "spurious_spans": fp_spans,
        "spurious_spans_per_sample": round(fp_spans / negatives, 4) if negatives else 0.0,
    }


def main() -> int:
    report = evaluate()
    if "--json" in sys.argv:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    print(f"samples           : {report['samples']} ({report['positives']} positive, {report['negatives']} negative)")
    print("per-field recall  :")
    for kind, value in report["per_field_recall"].items():
        print(f"    {kind:<10} {value:6.2%}   (n={report['per_field_support'][kind]})")
    print(f"false positives   : {report['false_positive_samples']} of {report['negatives']} "
          f"negative samples ({report['false_positive_rate']:.2%})")
    print(f"spurious spans    : {report['spurious_spans']} "
          f"({report['spurious_spans_per_sample']:.3f} per sample)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
