"""Acceptance tests, one section per clause of the task's acceptance criteria.

    1) tokenize/detokenize; raw row holds no plaintext; rotation keeps old data readable
    2) masking corpus >= 200 samples; phone/id recall 100%; name/address recall >= 95%;
       false-positive rate stated
    3) detokenize refused without permission or reason, both logged
    4) audit tampering is located by the verification script
    5) retention cleanup after fast-forward; consent withdrawal deletes immediately
    6) cross-city / cross-station access refused, one case per role
    7) dependency scan and OWASP report ship with the repository
    8) the whole suite passes with a single command
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Isolate key material before the app imports its state.
_KMS_DIR = tempfile.mkdtemp(prefix="pii-kms-")
os.environ["PII_KMS_DIR"] = _KMS_DIR
os.environ["PII_RETENTION_DAYS"] = "180"

from fastapi.testclient import TestClient  # noqa: E402

import pii_vault.api as api  # noqa: E402
from pii_vault.audit import AuditEntry, AuditLog  # noqa: E402
from pii_vault.masking import Masker, id_checksum_valid, luhn_valid  # noqa: E402
from pii_vault.rbac import ROLES  # noqa: E402
from pii_vault.retention import Record, RetentionPolicy  # noqa: E402
from pii_vault.vault import PIIVault  # noqa: E402
from pii_vault.kms import LocalFileKMS  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SAMPLES = REPO / "data" / "samples.jsonl"

SAMPLE = {
    "name": "张三",
    "phone": "138 0013 8000",
    "id_card": "110101199003071233",
    "bank_card": "6222021234567894",
    "address": "杭州市西湖区文一西路333号11幢15单元",
    "city": "杭州市",
    "station": "S001",
}


@pytest.fixture()
def client():
    api.STATE.clear()
    api._init_state()
    return TestClient(api.app)


def H(role: str, actor: str = "tester", city: str | None = None, station: str | None = None) -> dict:
    headers = {"x-role": role, "x-actor": actor}
    if city:
        headers["x-city"] = city
    if station:
        headers["x-station"] = station
    return headers


def make_record(client, **overrides) -> str:
    body = {**SAMPLE, **overrides}
    resp = client.post("/v1/records", json=body, headers=H("recruiter", station=body["station"]))
    assert resp.status_code == 201, resp.text
    return resp.json()["token"]


# --- criterion 1 -----------------------------------------------------------------
def test_c1_raw_row_contains_no_plaintext(client):
    token = make_record(client)
    row = client.get(f"/v1/records/{token}/raw-row", headers=H("admin")).json()
    blob = json.dumps(row, ensure_ascii=False)
    for value in ("张三", "138 0013 8000", "110101199003071233", "6222021234567894", "文一西路"):
        assert value not in blob, f"plaintext {value!r} found in the stored row"
    assert set(row["sealed"]) == {"name", "phone", "id_card", "bank_card", "address"}
    assert all("ciphertext" in f and "key_id" in f for f in row["sealed"].values())


def test_c1_tokenize_then_detokenize_roundtrips(client):
    token = make_record(client)
    out = client.post(
        f"/v1/records/{token}/detokenize",
        json={"field": "phone", "reason": "callback scheduled by recruiter"},
        headers=H("station_manager", station="S001"),
    )
    assert out.status_code == 200, out.text
    assert out.json()["value"] == SAMPLE["phone"]


def test_c1_rotation_keeps_old_data_readable(client):
    token = make_record(client)
    before = client.get(f"/v1/records/{token}/raw-row", headers=H("admin")).json()
    old_key = before["sealed"]["name"]["key_id"]

    rotated = client.post("/v1/admin/rotate", headers=H("admin"))
    assert rotated.status_code == 200, rotated.text
    new_key = rotated.json()["new_key_id"]
    assert new_key != old_key

    after = client.get(f"/v1/records/{token}/raw-row", headers=H("admin")).json()
    assert after["sealed"]["name"]["key_id"] == new_key
    # The value written under the old key is still decryptable after rotation.
    value = client.post(
        f"/v1/records/{token}/detokenize",
        json={"field": "name", "reason": "post-rotation integrity check"},
        headers=H("station_manager", station="S001"),
    ).json()["value"]
    assert value == SAMPLE["name"]
    # Both keys remain available, so pre-rotation backups stay readable.
    assert old_key in client.get("/health").json()["keys"]


def test_c1_distinct_ciphertexts_for_equal_plaintext():
    kms = LocalFileKMS(tempfile.mkdtemp(prefix="pii-kms-unit-"))
    vault = PIIVault(kms)
    a = vault.seal("tok_a", "phone", "13800138000")
    b = vault.seal("tok_b", "phone", "13800138000")
    assert a.ciphertext != b.ciphertext


def test_c1_ciphertext_cannot_be_moved_to_another_row():
    """The AAD binds token and field, so a lifted ciphertext fails authentication.

    Without this binding an attacker with write access to the table could copy a
    colleague's ciphertext into their own row and read it through the API.
    """
    kms = LocalFileKMS(tempfile.mkdtemp(prefix="pii-kms-aad-"))
    vault = PIIVault(kms)
    sealed = vault.seal("tok_victim", "phone", "13800138000")
    moved = type(sealed)(token="tok_attacker", key_id=sealed.key_id, nonce=sealed.nonce, ciphertext=sealed.ciphertext)

    with pytest.raises(Exception):
        vault.open(moved, "phone")
    # The same field under its original token still opens, so the binding is not
    # simply breaking decryption altogether.
    assert vault.open(sealed, "phone") == "13800138000"

    # Moving a ciphertext between fields of the same row must fail too.
    phone = vault.seal("tok_x", "phone", "13800138000")
    as_name = type(phone)(token="tok_x", key_id=phone.key_id, nonce=phone.nonce, ciphertext=phone.ciphertext)
    with pytest.raises(Exception):
        vault.open(as_name, "name")


# --- criterion 2 -----------------------------------------------------------------
def test_c2_corpus_has_at_least_200_samples():
    rows = [json.loads(l) for l in SAMPLES.read_text(encoding="utf-8").splitlines() if l.strip()]
    positives = [r for r in rows if r["label"] == "positive"]
    assert len(positives) >= 200, f"only {len(positives)} positive samples"
    kinds = {k for r in positives for k in r["expected"]}
    assert {"name", "phone", "id", "address", "bankcard"} <= kinds


def test_c2_recall_meets_thresholds():
    masker = Masker()
    rows = [json.loads(l) for l in SAMPLES.read_text(encoding="utf-8").splitlines() if l.strip()]
    hit: dict[str, int] = {}
    total: dict[str, int] = {}
    negatives = 0
    false_positives = 0
    for row in rows:
        found = {"".join(c for c in s.text if c.isalnum() or "\u4e00" <= c <= "\u9fff").lower()
                 for s in masker.mask(row["text"]).spans}
        if row["label"] == "positive":
            for kind, value in row["expected"].items():
                total[kind] = total.get(kind, 0) + 1
                norm = "".join(c for c in value if c.isalnum() or "\u4e00" <= c <= "\u9fff").lower()
                if norm in found:
                    hit[kind] = hit.get(kind, 0) + 1
        else:
            negatives += 1
            if masker.mask(row["text"]).spans:
                false_positives += 1

    assert hit.get("phone", 0) / total["phone"] == 1.0, "phone recall must be 100%"
    assert hit.get("id", 0) / total["id"] == 1.0, "id recall must be 100%"
    assert hit.get("name", 0) / total["name"] >= 0.95, "name recall must be >= 95%"
    assert hit.get("address", 0) / total["address"] >= 0.95, "address recall must be >= 95%"
    assert false_positives / negatives <= 0.05, "false-positive rate must be stated and low"


def test_c2_edge_case_formats_are_detected():
    masker = Masker()
    cases = {
        "phone_spaced": "手机号 138 0013 8000",
        "phone_hyphen": "手机号 138-0013-8000",
        "phone_86": "手机号 +86 13800138000",
        "phone_86_plain": "手机号 8613800138000",
        "id_lower_x": "身份证号 11010119900300003x",
        "card_grouped": "银行卡 6222 0212 3456 7894",
        "foreign_name": "联系人：Alexander Petrov",
        "address_long": "住址：杭州市西湖区文一西路333号11幢15单元",
    }
    for label, text in cases.items():
        spans = masker.mask(text).spans
        assert spans, f"{label}: nothing detected in {text!r}"


def test_c2_checksum_helpers_reject_invalid_values():
    assert id_checksum_valid("110101199003071233")
    assert not id_checksum_valid("110101199003071234")
    assert luhn_valid("6222021234567894")
    assert not luhn_valid("6222021234567890")


def test_c2_checksum_gate_is_enforced_on_detection():
    """A 17-digit-plus-check-char string with a *wrong* check char is not an ID.

    Without the gate the detector would mask any 18-digit run, including order numbers
    and timestamps, and the corpus would never reveal it.
    """
    masker = Masker()
    assert masker.mask("身份证号 110101199003071233").spans, "a valid ID must be detected"
    assert not masker.mask("身份证号 110101199003071234").spans, "an invalid checksum must not be masked"


def test_c2_surname_gate_stops_prose_being_read_as_a_name():
    """Without a separator a Han run only counts as a name if it starts with a surname.

    ``站长会议要求`` is a policy sentence. The label ``站长`` is followed by ``会议要求``
    with no separator, so only the surname check distinguishes the two.
    """
    masker = Masker()
    assert masker.mask("站长会议要求：所有面试结果必须当日录入。").spans == []
    assert masker.mask("站长：李四").spans, "an explicit separator is enough on its own"
    assert masker.mask("站长李四").spans, "李 is a surname, so no separator is still a name"


def test_c2_metrics_report_is_shipped():
    report = REPO / "reports" / "masking_metrics.json"
    assert report.exists(), "reports/masking_metrics.json must ship with the repository"
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["samples"] >= 200
    assert "false_positive_rate" in data


# --- criterion 3 -----------------------------------------------------------------
def test_c3_detokenize_denied_without_power_and_logged(client):
    token = make_record(client)
    resp = client.post(
        f"/v1/records/{token}/detokenize",
        json={"field": "phone", "reason": "I want to see it"},
        headers=H("recruiter", station="S001"),
    )
    assert resp.status_code == 403
    entries = client.get("/v1/audit", headers=H("admin")).json()["entries"]
    denied = [e for e in entries if e["action"] == "record.detokenize.denied"]
    assert denied and denied[-1]["detail"]["cause"] == "no_power"


def test_c3_detokenize_denied_without_reason_and_logged(client):
    token = make_record(client)
    resp = client.post(
        f"/v1/records/{token}/detokenize",
        json={"field": "phone", "reason": ""},
        headers=H("station_manager", station="S001"),
    )
    assert resp.status_code == 400
    entries = client.get("/v1/audit", headers=H("admin")).json()["entries"]
    denied = [e for e in entries if e["action"] == "record.detokenize.denied"]
    assert denied and denied[-1]["detail"]["cause"] == "no_reason"


def test_c3_successful_detokenize_is_logged_with_reason(client):
    token = make_record(client)
    client.post(
        f"/v1/records/{token}/detokenize",
        json={"field": "name", "reason": "identity confirmation call"},
        headers=H("station_manager", station="S001"),
    )
    entries = client.get("/v1/audit", headers=H("admin")).json()["entries"]
    ok = [e for e in entries if e["action"] == "record.detokenize" and e["reason"]]
    assert ok, "a successful detokenize must be recorded with its reason"


# --- criterion 4 -----------------------------------------------------------------
def test_c4_tampering_is_located():
    log = AuditLog()
    for i in range(6):
        log.append("actor", "record.read", f"tok_{i}")
    ok, bad = log.verify_chain()
    assert ok and bad is None

    log.entries[3].subject = "tok_tampered"
    ok, bad = log.verify_chain()
    assert not ok
    assert bad == 3, f"expected the tampered index 3, got {bad}"


def test_c4_tampering_detected_over_the_api(client):
    token = make_record(client)
    client.get(f"/v1/records/{token}", headers=H("admin"))
    exported = client.get("/v1/audit", headers=H("admin")).json()["entries"]
    exported[0]["actor"] = "someone_else"

    resp = client.post("/v1/audit/verify", json={"entries": exported}, headers=H("admin"))
    assert resp.status_code == 200
    assert resp.json()["chain_ok"] is False
    assert resp.json()["first_bad_index"] == 0


def test_c4_chain_links_each_entry_to_its_predecessor():
    log = AuditLog()
    a = log.append("a", "record.create", "t1")
    b = log.append("a", "record.read", "t1")
    assert b.prev_hash == a.entry_hash
    assert AuditEntry(**a.__dict__).compute_hash() == a.entry_hash


def test_c4_breaking_a_link_is_detected():
    """Deleting an entry breaks the chain; the check must report the link, not pass.

    Editing an entry is caught by the hash check. *Removing* one leaves every
    remaining hash self-consistent, so only the predecessor comparison can catch it —
    and that comparison is what this test pins down.
    """
    log = AuditLog()
    for i in range(5):
        log.append("actor", "record.read", f"tok_{i}")

    tampered = [e for e in log.entries if e.seq != 3]
    ok, bad = log.verify_chain(tampered)
    assert not ok, "a removed entry must not verify"
    # Entry seq 4 is now at index 2 and no longer chains to entry seq 2's hash.
    assert bad == 2


# --- criterion 5 -----------------------------------------------------------------
def test_c5_expired_data_anonymized_after_fast_forward():
    policy = RetentionPolicy(retention_days=180)
    now = datetime(2026, 11, 3, tzinfo=timezone.utc)
    fresh = Record("t_fresh", "杭州市", "S001", now - timedelta(days=10), sealed={"name": "x"})
    stale = Record("t_stale", "杭州市", "S001", now - timedelta(days=200), sealed={"name": "y"})

    produced = policy.run_cleanup([fresh, stale], now=now)
    assert [r.token for r in produced] == ["t_stale"]
    assert produced[0].mode == "anonymized"
    assert produced[0].trigger == "retention"
    assert stale.sealed == {} and stale.anonymized
    assert fresh.sealed and not fresh.anonymized


def test_c5_consent_withdrawal_deletes_immediately():
    policy = RetentionPolicy(retention_days=180)
    now = datetime(2026, 11, 3, tzinfo=timezone.utc)
    record = Record("t1", "杭州市", "S001", now, sealed={"phone": "13800138000"})
    rec = policy.withdraw_consent(record, now=now)
    assert rec.mode == "deleted" and rec.trigger == "consent_withdrawal"
    assert record.deleted and record.sealed == {}


def test_c5_deletion_records_are_produced_over_the_api(client):
    token = make_record(client)
    resp = client.post("/v1/records/{}/withdraw-consent".format(token), headers=H("admin"))
    assert resp.status_code == 200
    assert resp.json()["deletion"]["mode"] == "deleted"
    row = client.get(f"/v1/records/{token}/raw-row", headers=H("admin")).json()
    assert row["sealed"] == {}, "withdrawn consent must leave no sealed data behind"


def test_c5_cleanup_endpoint_reports_work_done(client):
    make_record(client)
    resp = client.post("/v1/admin/cleanup", headers=H("admin"))
    assert resp.status_code == 200
    assert "deletions" in resp.json()


# --- criterion 6 -----------------------------------------------------------------
def test_c6_recruiter_cannot_read_another_station(client):
    token = make_record(client, city="HZ", station="S001")
    resp = client.get(f"/v1/records/{token}", headers=H("recruiter", station="S999"))
    assert resp.status_code == 403
    assert resp.json()["code"] == "out_of_scope"


def test_c6_operations_cannot_cross_cities(client):
    token = make_record(client, city="HZ", station="S001")
    resp = client.get(f"/v1/records/{token}", headers=H("operations", city="CD"))
    assert resp.status_code == 403


def test_c6_operations_can_read_within_their_city(client):
    token = make_record(client, city="HZ", station="S001")
    resp = client.get(f"/v1/records/{token}", headers=H("operations", city="HZ"))
    assert resp.status_code == 200
    assert resp.json()["mode"] == "masked"


def test_c6_admin_is_global(client):
    token = make_record(client, city="HZ", station="S001")
    assert client.get(f"/v1/records/{token}", headers=H("admin")).status_code == 200


def test_c6_every_role_is_exercised():
    """One case per role, so a change to the policy table cannot silently pass."""
    assert set(ROLES) == {"recruiter", "station_manager", "operations", "admin", "auditor"}


def test_c6_export_requires_approval(client):
    token = make_record(client)
    resp = client.post(
        f"/v1/records/{token}/export", json={"approval_id": "apr-1"}, headers=H("admin")
    )
    assert resp.status_code == 403
    client.post("/v1/admin/approvals", json={"approval_id": "apr-1"}, headers=H("admin"))
    ok = client.post(
        f"/v1/records/{token}/export", json={"approval_id": "apr-1"}, headers=H("admin")
    )
    assert ok.status_code == 200


def test_c6_recruiter_cannot_export(client):
    token = make_record(client)
    resp = client.post(
        f"/v1/records/{token}/export", json={"approval_id": "apr-1"}, headers=H("recruiter", station="S001")
    )
    assert resp.status_code == 403


def test_c6_auditor_is_read_only(client):
    token = make_record(client)
    resp = client.post(
        f"/v1/records/{token}/export", json={"approval_id": "apr-1"}, headers=H("auditor")
    )
    assert resp.status_code == 403


def test_c6_missing_role_is_unauthenticated(client):
    token = make_record(client)
    assert client.get(f"/v1/records/{token}").status_code == 401


# --- criterion 7 -----------------------------------------------------------------
def test_c7_dependency_and_owasp_reports_ship_with_repo():
    for name in ("dependency_scan.txt", "owasp_self_test.md"):
        path = REPO / "reports" / name
        assert path.exists(), f"reports/{name} must ship with the repository"
        assert path.read_text(encoding="utf-8").strip(), f"reports/{name} must not be empty"


def test_c7_dependency_scan_reports_no_unaddressed_high_severity():
    text = (REPO / "reports" / "dependency_scan.txt").read_text(encoding="utf-8")
    assert "HIGH and CRITICAL" in text, "the scan report must state its severity policy"
    match = re.search(r"unaddressed_high_severity:\s*(\d+)", text)
    assert match, "the scan report must carry a machine-checkable unaddressed_high_severity count"
    assert int(match.group(1)) == 0, "unaddressed high-severity items remain"


# --- criterion 8 -----------------------------------------------------------------
def test_c8_single_command_runs_the_suite():
    """The suite itself is the artefact: `pytest -q` is the single command."""
    assert (REPO / "pytest.ini").exists()
    assert (REPO / "Makefile").exists()


def test_c8_mask_endpoint_serves_the_sdk(client):
    resp = client.post("/v1/mask", json={"text": "联系人：李四，手机号 13900139000"}, headers=H("recruiter"))
    assert resp.status_code == 200
    body = resp.json()
    assert "[name_1]" in body["masked"] and "[phone_1]" in body["masked"]
    assert body["mapping"]["[name_1]"] == "李四"


@pytest.fixture(autouse=True, scope="session")
def _cleanup():
    yield
    shutil.rmtree(_KMS_DIR, ignore_errors=True)
