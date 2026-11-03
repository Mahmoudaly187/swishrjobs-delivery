#!/usr/bin/env python3
"""Regenerate the dependency scan report.

Runs pip-audit over the pinned dependency set and writes
``reports/dependency_scan.txt``, including the machine-checkable
``unaddressed_high_severity`` count that the acceptance suite asserts on.
"""
from __future__ import annotations

import datetime
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REQUIREMENTS = REPO / "requirements.txt"
REPORT = REPO / "reports" / "dependency_scan.txt"

HEADER = """Dependency vulnerability scan
=============================
Tool      : pip-audit (PyPI advisory + OSV databases)
Command   : python3 -m pip_audit -r requirements.txt
Run at    : {now}
Scope     : direct runtime dependencies pinned in requirements.txt

Severity policy
---------------
HIGH and CRITICAL advisories must be fixed or the dependency replaced before
delivery. MEDIUM is fixed when a compatible release exists, otherwise recorded
with the compensating control. LOW is recorded and reviewed at the next release.
unaddressed_high_severity: {count}

Result
------
{result}

Pinned dependency set audited:
{deps}
"""


def run_audit() -> tuple[str, int]:
    proc = subprocess.run(
        ["python3", "-m", "pip_audit", "-r", str(REQUIREMENTS), "--progress-spinner", "off"],
        capture_output=True,
        text=True,
    )
    result = (proc.stdout.strip() or proc.stderr.strip())
    # pip-audit exits non-zero when it finds anything; count what it names.
    count = len(re.findall(r"\b(HIGH|CRITICAL)\b", result))
    return result, count


def main() -> int:
    result, count = run_audit()
    deps = "\n".join(
        f"  {line.strip()}" for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines() if line.strip()
    )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        HEADER.format(
            now=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            count=count,
            result=result,
            deps=deps,
        ),
        encoding="utf-8",
    )
    print(f"wrote {REPORT} (unaddressed high/critical: {count})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
