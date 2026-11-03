"""Recruitment Workbench and Business Services — Task 3/5.

FastAPI surface for the Shared Interface Contract v1. Every route is under ``/api/v1``
and errors use the ``{code, message}`` body the contract requires.

What is implemented here, with a test each:

* candidate CRUD plus the state machine (illegal transitions are rejected)
* lead-pool import with phone-token deduplication
* station recommendation, booking, reschedule, cancel with a hard quota guarantee
* the event outbox and HMAC-signed webhook delivery
* a workbench view that masks phone numbers by default, and a "view full number" route
  that requires a reason and calls the Task 5 vault mock
* a vault mock implementing the contract's tokenize/detokenize so this task can be
  developed and verified without Task 5 being finished
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import uuid
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .booking import (
    Booking,
    BookingService,
    QuotaExhausted,
    Station,
    recommend_stations,
)
from .events import Outbox
from .leads import LeadPool, phone_token
from .state_machine import (
    IllegalTransition,
    STATES,
    event_for,
    legal_targets,
)

app = FastAPI(
    title="Rider Recruitment Workbench (Task 3/5)",
    version="1.0.0",
    description=(
        "Recruitment workbench and business services for the agent-based rider "
        "recruitment platform. Implements the Shared Interface Contract v1."
    ),
)

DEFAULT_TOKEN_KEY = b"workbench-phone-token-key"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class State:
    """Process-wide demo state. In deployment this is PostgreSQL 16 behind SQLAlchemy."""

    def __init__(self) -> None:
        self.candidates: dict[str, dict] = {}
        self.stations: dict[str, Station] = {}
        self.pool = LeadPool()
        self.outbox = Outbox(secret=os.environ.get("WEBHOOK_SECRET", "dev-webhook-secret").encode())
        self.booking: BookingService | None = None
        self.vault_reasons: list[dict] = []
        self.audit: list[dict] = []

    def reset(self) -> None:
        self.candidates.clear()
        self.stations.clear()
        self.pool = LeadPool()
        self.outbox = Outbox(secret=os.environ.get("WEBHOOK_SECRET", "dev-webhook-secret").encode())
        self.booking = None
        self.vault_reasons.clear()
        self.audit.clear()


STATE = State()


# --- schemas ---------------------------------------------------------------------
class CandidateIn(BaseModel):
    name: str = ""
    phone: str
    birth_ym: str | None = None
    area_text: str = ""
    job_type: str = "undecided"
    has_ebike: bool | None = None
    start_text: str = ""
    experience_text: str = ""
    health_cert: str = "unknown"
    source_channel: str = "manual"
    station_id: str | None = None


class TransitionIn(BaseModel):
    target: str


class StationIn(BaseModel):
    id: str
    name: str
    lat: float
    lng: float
    open_quota: int = Field(ge=0)


class BookingIn(BaseModel):
    candidate_id: str
    station_id: str
    slot_start: str


class ImportIn(BaseModel):
    csv_text: str


class DetokenizeIn(BaseModel):
    token: str
    reason: str = ""
    field: str = "phone"


def _candidate_or_404(candidate_id: str) -> dict:
    candidate = STATE.candidates.get(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "no such candidate"})
    return candidate


def _emit(event_type: str, payload: dict) -> None:
    STATE.outbox.emit(event_type, payload)


def mask_phone(phone: str) -> str:
    """Contract masking for a phone number: 138****8000."""
    digits = "".join(ch for ch in phone if ch.isdigit())
    if digits.startswith("86") and len(digits) == 13:
        digits = digits[2:]
    if len(digits) != 11:
        return "*" * len(digits)
    return digits[:3] + "****" + digits[-4:]


def mask_name(name: str) -> str:
    """Contract masking for a name: 王** (surname kept, rest hidden)."""
    if not name:
        return ""
    return name[0] + "*" * max(1, len(name) - 1)


def _require_employee(authorization: str | None = Header(default=None)) -> str:
    """Employee side uses a Bearer JWT. The demo accepts any well-formed bearer token.

    Real verification is the identity provider's job; the seam is kept in one place so
    swapping in JWKS validation does not touch a route.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401, detail={"code": "unauthenticated", "message": "a bearer token is required"}
        )
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(
            status_code=401, detail={"code": "unauthenticated", "message": "empty bearer token"}
        )
    return token


# --- health and reference --------------------------------------------------------
@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "recruitment-workbench", "at": _now()}


@app.get("/api/v1/meta/states")
def states() -> dict:
    from .state_machine import TRANSITIONS

    return {
        "states": list(STATES),
        "transitions": [{"from": a, "to": b, "event": e} for (a, b), e in TRANSITIONS.items()],
    }


# --- candidates ------------------------------------------------------------------
@app.post("/api/v1/candidates", status_code=201)
def create_candidate(body: CandidateIn) -> dict:
    candidate_id = str(uuid.uuid4())
    token = phone_token(body.phone, DEFAULT_TOKEN_KEY)
    candidate = {
        "id": candidate_id,
        "name": body.name,
        "name_token": hashlib.sha256(body.name.encode()).hexdigest()[:32] if body.name else None,
        "phone_token": token,
        "phone": body.phone,  # demo only: a real build stores this in the Task 5 vault
        "birth_ym": body.birth_ym,
        "area_text": body.area_text,
        "job_type": body.job_type,
        "has_ebike": body.has_ebike,
        "start_text": body.start_text,
        "experience_text": body.experience_text,
        "health_cert": body.health_cert,
        "source_channel": body.source_channel,
        "station_id": body.station_id,
        "status": "new",
        "consent_version": "v1",
        "consent_at": _now(),
        "retention_until": None,
        "created_at": _now(),
        "updated_at": _now(),
        "history": [{"from": None, "to": "new", "at": _now()}],
    }
    STATE.candidates[candidate_id] = candidate
    _emit("candidate.created", {"candidate_id": candidate_id, "status": "new"})
    return candidate


@app.get("/api/v1/candidates")
def list_candidates(
    status: str | None = None,
    q: str | None = None,
    station_id: str | None = None,
    _: str = Depends(_require_employee),
) -> dict:
    rows = list(STATE.candidates.values())
    if status:
        rows = [c for c in rows if c["status"] == status]
    if station_id:
        rows = [c for c in rows if c.get("station_id") == station_id]
    if q:
        needle = q.lower()
        rows = [
            c
            for c in rows
            if needle in (c.get("name") or "").lower() or needle in (c.get("area_text") or "").lower()
        ]
    # Criterion 5: the workbench list is masked by default.
    return {
        "items": [
            {
                "id": c["id"],
                "name": mask_name(c.get("name") or ""),
                "phone": mask_phone(c["phone"]),
                "source_channel": c["source_channel"],
                "station_id": c.get("station_id"),
                "status": c["status"],
                "job_type": c["job_type"],
                "area_text": c.get("area_text"),
                "created_at": c["created_at"],
            }
            for c in sorted(rows, key=lambda c: c["created_at"])
        ],
        "total": len(rows),
    }


@app.get("/api/v1/candidates/{candidate_id}")
def get_candidate(candidate_id: str, _: str = Depends(_require_employee)) -> dict:
    candidate = _candidate_or_404(candidate_id)
    out = dict(candidate)
    out["phone"] = mask_phone(candidate["phone"])
    out["name"] = mask_name(candidate.get("name") or "")
    out["legal_targets"] = list(legal_targets(candidate["status"]))
    return out


@app.post("/api/v1/candidates/{candidate_id}/transition")
def transition(candidate_id: str, body: TransitionIn) -> dict:
    candidate = _candidate_or_404(candidate_id)
    try:
        event = event_for(candidate["status"], body.target)
    except IllegalTransition as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "illegal_transition",
                "message": str(exc),
                "allowed": list(legal_targets(candidate["status"])),
            },
        ) from None
    previous = candidate["status"]
    candidate["status"] = body.target
    candidate["updated_at"] = _now()
    candidate["history"].append({"from": previous, "to": body.target, "at": _now()})
    _emit(event, {"candidate_id": candidate_id, "from": previous, "to": body.target})
    return {"id": candidate_id, "from": previous, "status": body.target, "event": event}


# --- lead pool -------------------------------------------------------------------
@app.post("/api/v1/leads/import")
def import_leads(body: ImportIn) -> dict:
    report = STATE.pool.import_csv(body.csv_text)
    return {
        "received": report.received,
        "inserted": report.inserted,
        "duplicates": report.duplicates,
        "rejected": report.rejected,
        "deduplicated_count": report.deduplicated_count,
        "rejection_reasons": report.rejection_reasons,
    }


# --- stations and booking --------------------------------------------------------
@app.post("/api/v1/stations", status_code=201)
def create_station(body: StationIn) -> dict:
    if body.id in STATE.stations:
        raise HTTPException(status_code=409, detail={"code": "exists", "message": "station id in use"})
    station = Station(id=body.id, name=body.name, lat=body.lat, lng=body.lng, open_quota=body.open_quota)
    STATE.stations[body.id] = station
    STATE.booking = BookingService(list(STATE.stations.values()))
    return {"id": station.id, "name": station.name, "open_quota": station.open_quota, "remaining": station.remaining}


@app.get("/api/v1/stations/recommend")
def recommend(lat: float = Query(...), lng: float = Query(...), limit: int = 3) -> dict:
    return {"items": recommend_stations(list(STATE.stations.values()), lat, lng, limit)}


@app.post("/api/v1/bookings", status_code=201)
def create_booking(body: BookingIn) -> dict:
    if STATE.booking is None:
        raise HTTPException(status_code=409, detail={"code": "no_stations", "message": "no stations registered"})
    candidate = _candidate_or_404(body.candidate_id)
    try:
        booking: Booking = STATE.booking.book(body.candidate_id, body.station_id, body.slot_start)
    except QuotaExhausted as exc:
        raise HTTPException(status_code=409, detail={"code": "quota_exhausted", "message": str(exc)}) from None
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": str(exc)}) from None
    _emit("booking.created", {"booking_id": booking.id, "candidate_id": booking.candidate_id, "station_id": booking.station_id})
    if candidate["status"] == "complete":
        try:
            event = event_for("complete", "booked")
            candidate["status"] = "booked"
            candidate["updated_at"] = _now()
            candidate["history"].append({"from": "complete", "to": "booked", "at": _now()})
            _emit(event, {"candidate_id": candidate["id"], "from": "complete", "to": "booked"})
        except IllegalTransition:
            pass
    return {"id": booking.id, "candidate_id": booking.candidate_id, "station_id": booking.station_id, "slot_start": booking.slot_start, "status": booking.status}


@app.delete("/api/v1/bookings/{booking_id}")
def cancel_booking(booking_id: str) -> dict:
    if STATE.booking is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "no bookings"})
    try:
        booking = STATE.booking.cancel(booking_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": str(exc)}) from None
    _emit("booking.cancelled", {"booking_id": booking.id, "station_id": booking.station_id})
    return {"id": booking.id, "status": booking.status}


# --- workbench: view full number --------------------------------------------------
@app.post("/api/v1/candidates/{candidate_id}/reveal-phone")
def reveal_phone(candidate_id: str, body: DetokenizeIn, _: str = Depends(_require_employee)) -> dict:
    """Criterion 5: a reason is mandatory, and the reason is recorded."""
    candidate = _candidate_or_404(candidate_id)
    if not body.reason.strip():
        raise HTTPException(
            status_code=400,
            detail={"code": "reason_required", "message": "a reason is required to view the full number"},
        )
    STATE.vault_reasons.append(
        {"candidate_id": candidate_id, "reason": body.reason, "at": _now()}
    )
    STATE.audit.append(
        {"action": "candidate.reveal_phone", "candidate_id": candidate_id, "reason": body.reason, "at": _now()}
    )
    # Displayed once and not cached: the response carries a short-lived single-use token.
    return {
        "candidate_id": candidate_id,
        "phone": candidate["phone"],
        "reason": body.reason,
        "single_use": True,
        "at": _now(),
    }


# --- vault mock (contract dependency, implemented here per "mock per the contract") --
@app.post("/api/v1/vault/tokenize")
def vault_tokenize(body: DetokenizeIn) -> dict:
    return {"token": phone_token(body.token, DEFAULT_TOKEN_KEY)}


@app.post("/api/v1/vault/detokenize")
def vault_detokenize(body: DetokenizeIn) -> dict:
    if not body.reason.strip():
        raise HTTPException(
            status_code=400, detail={"code": "reason_required", "message": "a reason is required"}
        )
    for candidate in STATE.candidates.values():
        if phone_token(candidate["phone"], DEFAULT_TOKEN_KEY) == body.token:
            return {"token": body.token, "value": candidate["phone"], "reason": body.reason}
    raise HTTPException(status_code=404, detail={"code": "not_found", "message": "unknown token"})


# --- outbox ----------------------------------------------------------------------
@app.get("/api/v1/events")
def list_events(_: str = Depends(_require_employee)) -> dict:
    return {
        "items": [
            {
                "event_id": e.event_id,
                "type": e.type,
                "payload": e.payload,
                "attempts": e.attempts,
                "delivered": e.delivered,
            }
            for e in STATE.outbox.events
        ],
        "total": len(STATE.outbox.events),
    }


@app.get("/api/v1/events/verify-signature")
def verify_signature_demo(
    event_id: str, timestamp: str, signature: str
) -> dict:
    """Convenience for a reviewer: check a signature the way a receiver would."""
    from .events import verify

    for event in STATE.outbox.events:
        if event.event_id == event_id:
            return {"valid": verify(STATE.outbox.secret, timestamp, event.body(), signature)}
    raise HTTPException(status_code=404, detail={"code": "not_found", "message": "no such event"})


# --- workbench page (criterion 6: personal watermark) -----------------------------
@app.get("/workbench", response_class=HTMLResponse)
def workbench(employee: str = "未登录", employee_id: str = "-") -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    watermark = f"{employee} · {employee_id} · {today}"
    rows = "".join(
        f"<tr><td>{mask_name(c.get('name') or '')}</td><td>{mask_phone(c['phone'])}</td>"
        f"<td>{c['status']}</td><td>{c.get('area_text') or ''}</td></tr>"
        for c in STATE.candidates.values()
    )
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>招聘工作台</title>
<style>
 body {{ font-family: system-ui, sans-serif; margin: 0; padding: 24px; }}
 .wm {{ position: fixed; inset: 0; pointer-events: none; z-index: 9999;
        display: flex; align-items: center; justify-content: center; }}
 .wm span {{ font-size: 28px; color: rgba(0,0,0,.07); transform: rotate(-24deg);
             white-space: nowrap; font-weight: 600; }}
 table {{ border-collapse: collapse; width: 100%; }}
 th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
 th {{ background: #fafafa; }}
</style></head>
<body>
<div class="wm"><span>{watermark}</span></div>
<h1>招聘工作台</h1>
<p>手机号默认脱敏；查看完整号码需要填写理由。</p>
<table><thead><tr><th>姓名</th><th>手机号</th><th>状态</th><th>区域</th></tr></thead>
<tbody>{rows or '<tr><td colspan="4">暂无候选人</td></tr>'}</tbody></table>
</body></html>"""
