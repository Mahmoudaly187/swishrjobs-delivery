"""HTTP surface.

Routes map one-to-one onto the eight acceptance criteria:

    POST /v1/records                      store PII (sealed, tokenized)
    GET  /v1/records/{token}              read back, masked unless a reason is given
    POST /v1/records/{token}/detokenize   full value; needs power *and* reason (crit 3)
    GET  /v1/records/{token}/raw-row      proves no plaintext in the row      (crit 1)
    POST /v1/admin/rotate                 re-wrap under a fresh key          (crit 1)
    POST /v1/admin/cleanup                retention / consent sweep          (crit 5)
    GET  /v1/audit                        the chain, plus verification        (crit 4)
    POST /v1/audit/verify                 tamper check                        (crit 4)
    POST /v1/mask                         SDK endpoint for Tasks 1 and 3      (crit 2)
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .audit import AuditLog
from .kms import LocalFileKMS, load_kms_from_env
from .masking import Masker
from .rbac import AccessDenied, Principal, principal_from_headers
from .retention import Record, RetentionPolicy
from .vault import PIIVault, SealedField

app = FastAPI(title="PII Vault & Compliance Module", version="1.0.0")

STATE: dict = {}


def _init_state() -> None:
    if STATE:
        return
    import os

    kms_dir = os.environ.get("PII_KMS_DIR", "/tmp/pii-vault-kms")
    try:
        kms = load_kms_from_env()
    except Exception:
        kms = LocalFileKMS(kms_dir)
    STATE.update(
        {
            "kms": kms,
            "vault": PIIVault(kms),
            "masker": Masker(),
            "audit": AuditLog(),
            "policy": RetentionPolicy(int(os.environ.get("PII_RETENTION_DAYS", "180"))),
            "records": {},
            "approvals": set(),
        }
    )


_init_state()

FIELDS = ("name", "phone", "id_card", "bank_card", "address")


class RecordIn(BaseModel):
    name: str | None = None
    phone: str | None = None
    id_card: str | None = None
    bank_card: str | None = None
    address: str | None = None
    city: str
    station: str
    consent: bool = True


class DetokenizeIn(BaseModel):
    field: str
    reason: str | None = Field(default=None, max_length=500)


class MaskIn(BaseModel):
    text: str


class ApprovalIn(BaseModel):
    approval_id: str


def principal(
    x_role: str | None = Header(default=None),
    x_actor: str | None = Header(default=None),
    x_city: str | None = Header(default=None),
    x_station: str | None = Header(default=None),
    x_permissions: str | None = Header(default=None),
) -> Principal:
    try:
        return principal_from_headers(
            {
                "x-role": x_role or "",
                "x-actor": x_actor or "",
                "x-city": x_city or "",
                "x-station": x_station or "",
                "x-permissions": x_permissions or "",
            }
        )
    except AccessDenied as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.exception_handler(AccessDenied)
async def _access_denied(_: Request, exc: AccessDenied) -> JSONResponse:
    return JSONResponse(status_code=403, content={"error": str(exc), "code": exc.code})


def _record_or_404(token: str) -> dict:
    row = STATE["records"].get(token)
    if row is None:
        raise HTTPException(status_code=404, detail="unknown token")
    return row


def _rehydrate(row: dict, name: str) -> SealedField:
    sealed = row["sealed"][name]
    return SealedField(
        token=sealed["token"],
        key_id=sealed["key_id"],
        nonce=sealed["nonce"],
        ciphertext=sealed["ciphertext"],
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "keys": STATE["kms"].list_key_ids()}


@app.post("/v1/records", status_code=201)
def create_record(body: RecordIn, who: Principal = Depends(principal)) -> dict:
    vault: PIIVault = STATE["vault"]
    token = vault.new_token()
    sealed: dict[str, dict] = {}
    for name in FIELDS:
        value = getattr(body, name)
        if value:
            sealed[name] = vault.seal(token, name, value).to_row()
    STATE["records"][token] = {
        "token": token,
        "city": body.city,
        "station": body.station,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        "consent": body.consent,
        "anonymized": False,
        "deleted": False,
        "sealed": sealed,
    }
    STATE["audit"].append(
        who.actor, "record.create", token, city=body.city, station=body.station, fields=sorted(sealed)
    )
    return {"token": token, "fields": sorted(sealed)}


@app.get("/v1/records/{token}")
def read_record(
    token: str,
    reason: str | None = None,
    who: Principal = Depends(principal),
) -> dict:
    row = _record_or_404(token)
    who.require_scope(row["city"], row["station"])
    vault: PIIVault = STATE["vault"]
    masker: Masker = STATE["masker"]
    full = bool(reason) and who.can("view_full")
    if full:
        who.require("view_full")
    out: dict = {"token": token, "city": row["city"], "station": row["station"], "mode": "full" if full else "masked"}
    for name, _ in row["sealed"].items():
        plaintext = vault.open(_rehydrate(row, name), name)
        out[name] = plaintext if full else masker.mask_value(name, plaintext)
    STATE["audit"].append(
        who.actor,
        "record.read",
        token,
        reason=reason,
        mode=out["mode"],
        fields=sorted(row["sealed"]),
    )
    return out


@app.post("/v1/records/{token}/detokenize")
def detokenize(token: str, body: DetokenizeIn, who: Principal = Depends(principal)) -> dict:
    """Full value. Requires the power *and* a stated reason; both outcomes are logged."""
    row = _record_or_404(token)
    audit: AuditLog = STATE["audit"]
    if not who.can("detokenize"):
        audit.append(who.actor, "record.detokenize.denied", token, reason=body.reason, cause="no_power")
        raise HTTPException(status_code=403, detail="role lacks the detokenize power")
    if not body.reason:
        audit.append(who.actor, "record.detokenize.denied", token, reason=None, cause="no_reason")
        raise HTTPException(status_code=400, detail="a reason is required to detokenize")
    if body.field not in row["sealed"]:
        raise HTTPException(status_code=404, detail=f"field {body.field!r} not present")
    who.require_scope(row["city"], row["station"])
    value = STATE["vault"].open(_rehydrate(row, body.field), body.field)
    audit.append(who.actor, "record.detokenize", token, reason=body.reason, field=body.field)
    return {"token": token, "field": body.field, "value": value, "reason": body.reason}


@app.get("/v1/records/{token}/raw-row")
def raw_row(token: str, who: Principal = Depends(principal)) -> dict:
    """The stored row exactly as the database holds it — ciphertext only."""
    row = _record_or_404(token)
    who.require_scope(row["city"], row["station"])
    return {k: v for k, v in row.items() if k != "sealed"} | {"sealed": row["sealed"]}


@app.post("/v1/records/{token}/export")
def export(token: str, body: ApprovalIn, who: Principal = Depends(principal)) -> dict:
    row = _record_or_404(token)
    who.require("export")
    who.require_scope(row["city"], row["station"])
    if body.approval_id not in STATE["approvals"]:
        STATE["audit"].append(
            who.actor, "record.export.denied", token, approval=body.approval_id, cause="no_approval"
        )
        raise HTTPException(status_code=403, detail="export requires an approved approval id")
    STATE["audit"].append(who.actor, "record.export", token, approval=body.approval_id)
    return {"token": token, "exported": sorted(row["sealed"]), "approval": body.approval_id}


@app.post("/v1/admin/approvals")
def grant_approval(body: ApprovalIn, who: Principal = Depends(principal)) -> dict:
    who.require("export")
    STATE["approvals"].add(body.approval_id)
    STATE["audit"].append(who.actor, "approval.grant", body.approval_id)
    return {"approval_id": body.approval_id, "status": "granted"}


@app.post("/v1/admin/rotate")
def rotate(who: Principal = Depends(principal)) -> dict:
    who.require("export")  # administrative power, reusing the admin-only flag
    vault: PIIVault = STATE["vault"]
    new_key_id = STATE["kms"].rotate()
    rewrapped = 0
    for token, row in STATE["records"].items():
        for name, sealed_row in list(row["sealed"].items()):
            plaintext = vault.open(_rehydrate(row, name), name)
            row["sealed"][name] = vault.seal(token, name, plaintext, key_id=new_key_id).to_row()
            rewrapped += 1
    STATE["audit"].append(who.actor, "keys.rotate", "all", new_key_id=new_key_id, fields=rewrapped)
    return {"new_key_id": new_key_id, "rewrapped": rewrapped, "keys": STATE["kms"].list_key_ids()}


@app.post("/v1/admin/cleanup")
def cleanup(who: Principal = Depends(principal)) -> dict:
    who.require("export")
    policy: RetentionPolicy = STATE["policy"]
    records = []
    for row in STATE["records"].values():
        records.append(
            Record(
                token=row["token"],
                city=row["city"],
                station=row["station"],
                created_at=datetime.fromisoformat(row["created_at"]),
                consent=row["consent"],
                anonymized=row["anonymized"],
                deleted=row["deleted"],
                sealed=row["sealed"],
            )
        )
    produced = policy.run_cleanup(records)
    for record in records:
        row = STATE["records"][record.token]
        row["consent"] = record.consent
        row["anonymized"] = record.anonymized
        row["deleted"] = record.deleted
        row["sealed"] = record.sealed
    for rec in produced:
        STATE["audit"].append(who.actor, f"data.{rec.mode}", rec.token, reason=rec.trigger, detail=rec.detail)
    return {"processed": len(produced), "deletions": [d.__dict__ for d in produced]}


@app.post("/v1/records/{token}/withdraw-consent")
def withdraw(token: str, who: Principal = Depends(principal)) -> dict:
    row = _record_or_404(token)
    who.require_scope(row["city"], row["station"])
    row["consent"] = False
    record = Record(
        token=token,
        city=row["city"],
        station=row["station"],
        created_at=datetime.fromisoformat(row["created_at"]),
        consent=False,
        sealed=row["sealed"],
    )
    rec = STATE["policy"].withdraw_consent(record)
    row["deleted"] = True
    row["sealed"] = {}
    STATE["audit"].append(who.actor, "data.deleted", token, reason="consent_withdrawal")
    return {"token": token, "deletion": rec.__dict__}


@app.get("/v1/audit")
def audit_entries(who: Principal = Depends(principal), limit: int = 100) -> dict:
    who.require_scope(None, None) if who.role == "admin" else None
    entries = STATE["audit"].entries[-limit:]
    ok, bad = STATE["audit"].verify_chain()
    return {"entries": [e.__dict__ for e in entries], "chain_ok": ok, "first_bad_index": bad}


@app.post("/v1/audit/verify")
def audit_verify(payload: dict, who: Principal = Depends(principal)) -> dict:
    """Verify a caller-supplied chain, so a tampered export can be checked offline."""
    from .audit import AuditEntry

    rows = payload.get("entries", [])
    entries = [AuditEntry(**{k: r[k] for k in AuditEntry.__dataclass_fields__}) for r in rows]
    ok, bad = STATE["audit"].verify_chain(entries)
    return {"chain_ok": ok, "first_bad_index": bad}


@app.post("/v1/mask")
def mask(body: MaskIn, who: Principal = Depends(principal)) -> dict:
    result = STATE["masker"].mask(body.text)
    return {
        "masked": result.masked,
        "mapping": result.mapping,
        "spans": [{"kind": s.kind, "start": s.start, "end": s.end} for s in result.spans],
    }
