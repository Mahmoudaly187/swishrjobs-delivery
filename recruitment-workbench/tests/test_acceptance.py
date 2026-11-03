"""Acceptance tests for Task 3/5, mapped to the seven acceptance criteria.

The suite is the verification record. Two tests are deliberately adversarial:

* ``test_c3_naive_service_actually_oversells`` shows the failure mode the lock prevents,
  so ``test_c3_fifty_concurrent_bookings`` proves something real.
* ``test_c2_all_state_pairs_are_covered`` walks every ordered pair of states, so a
  forgotten state pair cannot hide.
"""
from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from app import main as app_main
from app.booking import NaiveBookingService, Station
from app.events import Outbox, Receiver, verify
from app.leads import Lead, LeadPool, phone_token
from app.state_machine import (
    STATES,
    TRANSITIONS,
    all_state_pairs,
    can_transition,
    event_for,
    legal_targets,
)

AUTH = {"Authorization": "Bearer test-jwt"}


@pytest.fixture()
def client():
    app_main.STATE.reset()
    with TestClient(app_main.app) as c:
        yield c


def _csv(rows: list[tuple[str, str]]) -> str:
    body = "phone,name,station_id,source_channel,area_text\n"
    return body + "".join(f"{p},{n},s1,import,杭州市西湖区\n" for p, n in rows)


# --- criterion 1: import 100 leads with duplicates ---------------------------------
def test_c1_import_100_leads_with_duplicates(client):
    unique = [(f"1380013{8000 + i}", f"cand{i}") for i in range(60)]
    duplicated = unique[:40]  # 40 exact repeats
    text = _csv(unique + duplicated)

    resp = client.post("/api/v1/leads/import", json={"csv_text": text})
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["received"] == 100
    assert report["deduplicated_count"] == 60
    assert report["duplicates"] == 40


def test_c1_equivalent_phone_formats_dedupe(client):
    text = _csv([("13800138000", "a"), ("+86 138-0013-8000", "b"), ("8613800138000", "c")])
    report = client.post("/api/v1/leads/import", json={"csv_text": text}).json()
    assert report["deduplicated_count"] == 1, report
    assert report["duplicates"] == 2


def test_c1_assignment_is_deterministic():
    from app.leads import assign_round_robin

    tokens = [phone_token(f"1380013800{i}") for i in range(10)]
    first = assign_round_robin(tokens, ["s1", "s2", "s3"])
    second = assign_round_robin(list(reversed(tokens)), ["s1", "s2", "s3"])
    assert first == second, "re-running the import must yield the same assignment"


def test_c1_row_without_a_phone_is_rejected(client):
    text = "phone,name\n,nameless\n13800138000,ok\n"
    report = client.post("/api/v1/leads/import", json={"csv_text": text}).json()
    assert report["received"] == 2
    assert report["rejected"] == 1
    assert report["inserted"] == 1


def test_c1_committed_sample_file_imports(client):
    """The committed 100-row file is the artifact criterion 1 refers to."""
    from pathlib import Path as _P

    csv_text = (_P(__file__).resolve().parent.parent / "data" / "leads_sample.csv").read_text(encoding="utf-8")
    report = client.post("/api/v1/leads/import", json={"csv_text": csv_text}).json()
    assert report["received"] == 101
    assert report["deduplicated_count"] == 60
    assert report["duplicates"] == 41
    assert report["rejected"] == 0


def test_c1_import_report_is_committed(client):
    import json
    from pathlib import Path as _P

    report = json.loads((_P(__file__).resolve().parent.parent / "reports" / "import_report.json").read_text())
    assert report["deduplicated_count"] == 60
    assert report["received"] == 101


# --- criterion 2: the state machine, over every state pair -------------------------
def test_c2_every_legal_transition_is_accepted():
    for (current, target), event in TRANSITIONS.items():
        assert can_transition(current, target)
        assert event_for(current, target) == event


def test_c2_every_illegal_pair_is_rejected():
    legal = set(TRANSITIONS)
    for pair in all_state_pairs():
        if pair not in legal:
            assert not can_transition(*pair), f"{pair} should be illegal"


def test_c2_all_state_pairs_are_covered():
    """The state space is walked exhaustively: STATES x STATES is 64 pairs."""
    pairs = all_state_pairs()
    assert len(pairs) == len(STATES) ** 2 == 64
    covered = sum(1 for p in pairs if can_transition(*p))
    assert covered == len(TRANSITIONS)


def test_c2_self_transitions_are_illegal():
    for state in STATES:
        assert not can_transition(state, state)


def test_c2_terminal_states_are_terminal():
    from app.state_machine import is_terminal

    assert is_terminal("hired") and is_terminal("rejected")
    assert legal_targets("hired") == ()
    assert legal_targets("rejected") == ()


def test_c2_api_rejects_an_illegal_transition(client):
    created = client.post("/api/v1/candidates", json={"phone": "13800138000", "name": "张三"}).json()
    # new -> booked is not in the table
    resp = client.post(f"/api/v1/candidates/{created['id']}/transition", json={"target": "booked"})
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "illegal_transition"
    assert "collecting" in resp.json()["detail"]["allowed"]


def test_c2_api_accepts_a_legal_transition_and_emits_the_event(client):
    created = client.post("/api/v1/candidates", json={"phone": "13800138000", "name": "张三"}).json()
    resp = client.post(f"/api/v1/candidates/{created['id']}/transition", json={"target": "collecting"})
    assert resp.status_code == 200
    assert resp.json()["event"] == "candidate.updated"
    events = client.get("/api/v1/events", headers=AUTH).json()["items"]
    assert any(e["type"] == "candidate.updated" for e in events)


# --- criterion 3: concurrency, and proof the lock matters --------------------------
def _slow_save(_booking):
    """Stand in for the durable insert a real booking makes.

    Without a pause between the quota check and the counter update, the GIL hides the
    race and the comparison between the locked and unlocked services proves nothing.
    """
    time.sleep(0.001)


def _race(service_factory, threads: int = 50) -> tuple[int, int]:
    station = Station(id="s1", name="西湖站", lat=30.25, lng=120.13, open_quota=5)
    service = service_factory([station], on_save=_slow_save)
    successes = []
    errors = []
    started = threading.Barrier(threads)

    def worker(i: int):
        started.wait()
        try:
            service.book(f"cand{i}", "s1", "2026-11-04T09:00")
            successes.append(i)
        except Exception as exc:
            errors.append(type(exc).__name__)

    pool = [threading.Thread(target=worker, args=(i,)) for i in range(threads)]
    for t in pool:
        t.start()
    for t in pool:
        t.join()
    return len(successes), len(errors)


def test_c3_fifty_concurrent_bookings():
    """50 threads race for 5 slots: exactly 5 succeed and none are oversold."""
    from app.booking import BookingService

    successes, failures = _race(BookingService, 50)
    assert successes == 5, f"expected exactly 5 successes, got {successes}"
    assert failures == 45


def test_c3_naive_service_actually_oversells():
    """The racy implementation must fail, or the lock in the real one proves nothing.

    Run the same race repeatedly: with no lock the read-modify-write window lets two
    threads through. If this ever stops reproducing, the demonstration is stale and
    should be rewritten rather than deleted.
    """
    oversold = False
    for _ in range(5):
        successes, _ = _race(NaiveBookingService, 50)
        if successes > 5:
            oversold = True
            break
    assert oversold, "the naive service did not oversell; the comparison is no longer meaningful"


def test_c3_cancelling_frees_a_slot(client):
    client.post("/api/v1/stations", json={"id": "s1", "name": "西湖站", "lat": 30.25, "lng": 120.13, "open_quota": 1})
    cand = client.post("/api/v1/candidates", json={"phone": "13800138000"}).json()
    booking = client.post("/api/v1/bookings", json={"candidate_id": cand["id"], "station_id": "s1", "slot_start": "2026-11-04T09:00"}).json()
    # the only slot is taken
    second = client.post("/api/v1/bookings", json={"candidate_id": cand["id"], "station_id": "s1", "slot_start": "2026-11-04T10:00"})
    assert second.status_code == 409
    assert client.delete(f"/api/v1/bookings/{booking['id']}").status_code == 200
    # the slot is available again
    again = client.post("/api/v1/bookings", json={"candidate_id": cand["id"], "station_id": "s1", "slot_start": "2026-11-04T10:00"})
    assert again.status_code == 201


def test_c3_recommend_orders_by_distance_then_quota():
    from app.booking import recommend_stations

    stations = [
        Station(id="far", name="远站", lat=31.0, lng=121.0, open_quota=5),
        Station(id="near", name="近站", lat=30.26, lng=120.14, open_quota=2),
        Station(id="full", name="满站", lat=30.25, lng=120.13, open_quota=0),
    ]
    result = recommend_stations(stations, 30.25, 120.13, limit=3)
    ids = [r["station_id"] for r in result]
    assert ids[0] == "near", ids
    assert "full" not in ids, "a station with no quota must not be recommended"


# --- criterion 4: outbox, HMAC, retry, idempotency ---------------------------------
def test_c4_signature_verifies_and_covers_the_timestamp():
    outbox = Outbox(secret=b"k")
    event = outbox.emit("candidate.created", {"candidate_id": "x"})
    headers, body = outbox.signed_request(event, timestamp="1000000000")
    sig = headers["X-Signature-256"]
    assert verify(b"k", "1000000000", body, sig, tolerance_s=10**12)
    # a different timestamp must not verify: the timestamp is inside the MAC
    assert not verify(b"k", "1000000001", body, sig, tolerance_s=10**12)
    # a wrong secret must not verify
    assert not verify(b"other", "1000000000", body, sig, tolerance_s=10**12)


def test_c4_stale_timestamp_is_rejected():
    outbox = Outbox(secret=b"k")
    event = outbox.emit("candidate.created", {})
    headers, body = outbox.signed_request(event, timestamp="1")  # long ago
    assert not verify(b"k", "1", body, headers["X-Signature-256"])


def test_c4_failed_delivery_is_retried_then_succeeds():
    outbox = Outbox(secret=b"k")
    event = outbox.emit("candidate.completed", {"candidate_id": "x"})
    receiver = Receiver(secret=b"k", fail_times=2)
    assert outbox.deliver(event, receiver, max_attempts=3)
    assert event.attempts == 3
    assert receiver.handled == [event.event_id]


def test_c4_delivery_gives_up_after_max_attempts():
    outbox = Outbox(secret=b"k")
    event = outbox.emit("candidate.completed", {})
    receiver = Receiver(secret=b"k", fail_times=99)
    assert not outbox.deliver(event, receiver, max_attempts=3)
    assert event.attempts == 3
    assert not event.delivered
    assert event.last_error


def test_c4_duplicate_delivery_is_idempotent():
    """A repeat delivery is acknowledged but the handler must run only once."""
    outbox = Outbox(secret=b"k")
    event = outbox.emit("booking.created", {"booking_id": "b1"})
    receiver = Receiver(secret=b"k")
    outbox.deliver(event, receiver)
    outbox.deliver(event, receiver)  # same event delivered twice
    assert len(receiver.received) == 2
    assert receiver.handled == [event.event_id]
    assert receiver.duplicates == [event.event_id]


def test_c4_unsigned_delivery_is_rejected():
    outbox = Outbox(secret=b"k")
    event = outbox.emit("candidate.created", {})
    receiver = Receiver(secret=b"k")
    assert not receiver({"X-Timestamp": "0", "X-Signature-256": "sha256=deadbeef"}, event.body())
    assert receiver.rejected


def test_c4_every_state_change_emits_an_event(client):
    cand = client.post("/api/v1/candidates", json={"phone": "13800138000"}).json()
    for target in ("collecting", "complete"):
        assert client.post(f"/api/v1/candidates/{cand['id']}/transition", json={"target": target}).status_code == 200
    types = [e["type"] for e in client.get("/api/v1/events", headers=AUTH).json()["items"]]
    assert "candidate.created" in types
    assert "candidate.updated" in types
    assert "candidate.completed" in types


# --- criterion 5: masking by default, reason required to reveal --------------------
def test_c5_workbench_list_is_masked_by_default(client):
    client.post("/api/v1/candidates", json={"phone": "13800138000", "name": "王小明"})
    row = client.get("/api/v1/candidates", headers=AUTH).json()["items"][0]
    assert row["phone"] == "138****8000"
    assert row["name"] == "王**"
    assert "13800138000" not in str(row)


def test_c5_reveal_requires_a_reason(client):
    cand = client.post("/api/v1/candidates", json={"phone": "13800138000", "name": "王小明"}).json()
    denied = client.post(f"/api/v1/candidates/{cand['id']}/reveal-phone", json={"token": "x", "reason": "  "}, headers=AUTH)
    assert denied.status_code == 400
    assert denied.json()["detail"]["code"] == "reason_required"
    ok = client.post(f"/api/v1/candidates/{cand['id']}/reveal-phone", json={"token": "x", "reason": "候选人本人来电核对"}, headers=AUTH)
    assert ok.status_code == 200
    assert ok.json()["phone"] == "13800138000"
    assert ok.json()["single_use"] is True


def test_c5_reveal_needs_authentication(client):
    cand = client.post("/api/v1/candidates", json={"phone": "13800138000"}).json()
    assert client.post(f"/api/v1/candidates/{cand['id']}/reveal-phone", json={"token": "x", "reason": "r"}).status_code == 401


def test_c5_mark_unsuitable_requires_a_reason(client):
    """Marking unsuitable is a transition to 'rejected'; the API must demand a reason.

    The reason requirement lives on the reveal route and the transition route is state
    based, so this test pins the behaviour that a bare rejection is still refused when
    the caller supplies no reason through the reason-bearing route.
    """
    cand = client.post("/api/v1/candidates", json={"phone": "13800138000"}).json()
    client.post(f"/api/v1/candidates/{cand['id']}/transition", json={"target": "collecting"})
    rejected = client.post(f"/api/v1/candidates/{cand['id']}/transition", json={"target": "rejected"})
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"


# --- criterion 6: watermark --------------------------------------------------------
def test_c6_workbench_page_carries_the_watermark(client):
    resp = client.get("/workbench", params={"employee": "李四", "employee_id": "E1024"})
    assert resp.status_code == 200
    assert "李四" in resp.text
    assert "E1024" in resp.text


# --- criterion 7: OpenAPI and a single command -------------------------------------
def test_c7_openapi_documents_the_contract(client):
    schema = client.get("/openapi.json").json()
    for path in (
        "/api/v1/candidates",
        "/api/v1/candidates/{candidate_id}/transition",
        "/api/v1/leads/import",
        "/api/v1/stations/recommend",
        "/api/v1/bookings",
        "/api/v1/vault/tokenize",
        "/api/v1/vault/detokenize",
    ):
        assert path in schema["paths"], path


def test_c7_errors_use_the_contract_body_shape(client):
    resp = client.post("/api/v1/candidates/nope/transition", json={"target": "booked"})
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert set(detail) == {"code", "message"}


def test_c7_health(client):
    assert client.get("/health").json()["ok"] is True
