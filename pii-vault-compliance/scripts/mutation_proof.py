#!/usr/bin/env python3
"""Mutation proof: show the gate goes red, not merely green.

A passing test suite proves little on its own — a suite that asserts nothing also
passes. This script deliberately breaks the module one property at a time and records
whether the acceptance suite notices. A mutation that survives means the suite does
not actually test that property.

Each mutation is an exact string substitution, so it either applies cleanly or the
script reports that it could not apply it rather than pretending it did.

Run:  python3 scripts/mutation_proof.py [--json reports/mutation_proof.json]
Exit: 0 when every mutation is caught, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# (name, relative path, exact text to replace, replacement, property under test)
MUTATIONS: list[tuple[str, str, str, str, str]] = [
    (
        "drop_audit_reason_gate",
        "pii_vault/api.py",
        '    if not body.reason:\n        audit.append(who.actor, "record.detokenize.denied", token, reason=None, cause="no_reason")\n        raise HTTPException(status_code=400, detail="a reason is required to detokenize")\n',
        "    if False:\n        pass\n",
        "detokenize must refuse an empty reason",
    ),
    (
        "drop_audit_permission_gate",
        "pii_vault/api.py",
        '    if not who.can("detokenize"):\n        audit.append(who.actor, "record.detokenize.denied", token, reason=body.reason, cause="no_power")\n        raise HTTPException(status_code=403, detail="role lacks the detokenize power")\n',
        "    if False:\n        pass\n",
        "detokenize must refuse a role without the power",
    ),
    (
        "skip_scope_check_on_read",
        "pii_vault/api.py",
        '    row = _record_or_404(token)\n    who.require_scope(row["city"], row["station"])\n    vault: PIIVault = STATE["vault"]',
        '    row = _record_or_404(token)\n    vault: PIIVault = STATE["vault"]',
        "cross-scope reads must be refused",
    ),
    (
        "break_audit_hash_chain",
        "pii_vault/audit.py",
        "            if entry.prev_hash != prev:\n                return False, i\n",
        "            if False:\n                pass\n",
        "the audit chain must detect a broken link",
    ),
    (
        "skip_audit_entry_hash_check",
        "pii_vault/audit.py",
        "            if entry.compute_hash() != entry.entry_hash:\n                return False, i\n",
        "            if False:\n                pass\n",
        "the audit chain must detect an edited entry",
    ),
    (
        "disable_id_checksum",
        "pii_vault/masking.py",
        "        for m in ID_RE.finditer(text):\n            if id_checksum_valid(m.group()):\n                spans.append(Span(\"id\", m.start(), m.end(), m.group()))\n",
        "        for m in ID_RE.finditer(text):\n            spans.append(Span(\"id\", m.start(), m.end(), m.group()))\n",
        "national ID detection must be checksum-gated",
    ),
    (
        "name_label_accepts_any_han",
        "pii_vault/masking.py",
        "            if not sep.strip():\n                if name[0] not in SURNAME_SET and name[:2] not in COMPOUND_SET:\n                    continue\n",
        "            if False:\n                pass\n",
        "unseparated name matches must require a plausible surname",
    ),
    (
        "retention_ignores_window",
        "pii_vault/retention.py",
        "        return now - record.created_at > timedelta(days=self.retention_days)",
        "        return False",
        "expiry must be driven by the retention window",
    ),
    (
        "consent_withdrawal_keeps_data",
        "pii_vault/retention.py",
        "            if not record.consent:\n                record.sealed.clear()\n                record.deleted = True\n",
        "            if not record.consent:\n                record.deleted = True\n",
        "consent withdrawal must erase the sealed data",
    ),
    (
        "rotation_forgets_old_key",
        "pii_vault/kms.py",
        '        self._current_file.write_text(key_id)\n        return key_id\n\n    def list_key_ids',
        '        self._current_file.write_text(key_id)\n        return key_id\n\n    def _unused_list_key_ids',
        "rotation must keep the historical key list intact",
    ),
    (
        "vault_aad_drops_token",
        "pii_vault/vault.py",
        "        return AAD_PREFIX + token.encode() + b\":\" + field.encode()",
        "        return AAD_PREFIX + field.encode()",
        "the AAD must bind the token so ciphertext cannot be relocated",
    ),
    (
        "export_skips_approval",
        "pii_vault/api.py",
        '    who.require("export")\n    who.require_scope(row["city"], row["station"])\n    if body.approval_id not in STATE["approvals"]:',
        '    who.require("export")\n    who.require_scope(row["city"], row["station"])\n    if False:',
        "export must require an approved approval id",
    ),
]


def run_suite(root: Path) -> tuple[bool, str]:
    """Return (passed, tail of output) for the acceptance suite in ``root``."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=root,
        capture_output=True,
        text=True,
        env=_env(root),
        timeout=300,
    )
    tail = (proc.stdout + proc.stderr).strip().splitlines()
    return proc.returncode == 0, "\n".join(tail[-3:])


def _env(root: Path) -> dict:
    import os

    env = dict(os.environ)
    env["PII_KMS_DIR"] = str(root / ".kms-mutation")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="write the report to this path")
    args = ap.parse_args()

    baseline_ok, baseline_tail = run_suite(REPO)
    print(f"baseline (unmutated): {'PASS' if baseline_ok else 'FAIL'}")
    if not baseline_ok:
        print("  the suite must be green before mutation testing means anything")
        print("  " + baseline_tail.replace("\n", "\n  "))
        return 1

    results = []
    work = Path(tempfile.mkdtemp(prefix="pii-vault-mutation-"))
    try:
        for name, rel, old, new, prop in MUTATIONS:
            tree = work / name
            shutil.copytree(
                REPO,
                tree,
                ignore=shutil.ignore_patterns(".git", ".pytest_cache", "__pycache__", ".kms*"),
            )
            target = tree / rel
            source = target.read_text(encoding="utf-8")
            if old not in source:
                results.append(
                    {"mutation": name, "file": rel, "property": prop, "applied": False, "caught": None,
                     "detail": "anchor text not found - mutation not applied"}
                )
                print(f"  {name:<34} NOT APPLIED (anchor text not found in {rel})")
                continue
            target.write_text(source.replace(old, new, 1), encoding="utf-8")

            passed, tail = run_suite(tree)
            caught = not passed
            results.append(
                {"mutation": name, "file": rel, "property": prop, "applied": True, "caught": caught,
                 "detail": tail}
            )
            print(f"  {name:<34} {'CAUGHT' if caught else 'SURVIVED'}  ({prop})")
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
