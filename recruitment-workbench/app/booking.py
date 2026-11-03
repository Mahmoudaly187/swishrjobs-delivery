"""Booking with a hard quota guarantee under concurrency.

Criterion 3 is the load test: 50 bookings racing for the last 5 slots must produce
exactly 5 successes. That is a mutual-exclusion problem, and the interesting part is
that the naive implementation passes a single-threaded test and fails in production.

Two implementations are provided so the difference is demonstrable rather than
asserted:

* ``NaiveBookingService`` reads the count and then writes, with no lock. It is correct
  under one thread and oversells under many. It exists so the test suite can show the
  failure mode, and it is never wired into the API.
* ``BookingService`` holds a per-station lock across the check-and-insert, so the
  invariant holds regardless of thread interleaving.

The test suite runs both against the same 50-thread scenario and asserts that the
naive one *does* oversell (at least once across repeated runs) while the locked one
never does. A test that only proves the good implementation works would not show that
the guard is load-bearing.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Station:
    id: str
    name: str
    lat: float
    lng: float
    open_quota: int
    booked: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.open_quota - self.booked)


@dataclass
class Booking:
    id: str
    candidate_id: str
    station_id: str
    slot_start: str
    status: str = "booked"


class QuotaExhausted(Exception):
    """Raised when a station has no remaining slots."""


class BookingService:
    """Thread-safe booking: the check, the increment and the save happen under one lock.

    ``on_save`` is called inside the critical section. It exists so a test can stand in
    for the write a real deployment makes to PostgreSQL: the reason a booking race is
    dangerous is that the quota check and the durable insert are not atomic, and without
    a hook there is no honest way to reproduce that in a test. It defaults to a no-op.
    """

    def __init__(self, stations: list[Station], on_save=None):
        self.stations = {s.id: s for s in stations}
        self.bookings: list[Booking] = []
        self._on_save = on_save
        # One lock per station, so bookings at different stations do not serialise.
        self._locks: dict[str, threading.Lock] = {s.id: threading.Lock() for s in stations}

    def book(self, candidate_id: str, station_id: str, slot_start: str) -> Booking:
        station = self.stations.get(station_id)
        if station is None:
            raise KeyError(f"unknown station {station_id!r}")
        with self._locks[station_id]:
            if station.booked >= station.open_quota:
                raise QuotaExhausted(f"station {station_id!r} has no remaining slots")
            booking = Booking(
                id=str(uuid.uuid4()),
                candidate_id=candidate_id,
                station_id=station_id,
                slot_start=slot_start,
            )
            if self._on_save is not None:
                self._on_save(booking)
            station.booked += 1
            self.bookings.append(booking)
            return booking

    def cancel(self, booking_id: str) -> Booking:
        for booking in self.bookings:
            if booking.id == booking_id and booking.status == "booked":
                station = self.stations[booking.station_id]
                with self._locks[booking.station_id]:
                    booking.status = "cancelled"
                    station.booked = max(0, station.booked - 1)
                return booking
        raise KeyError(f"no active booking {booking_id!r}")


class NaiveBookingService(BookingService):
    """Deliberately racy: no lock across the check-and-insert.

    Used only by the test suite, to prove that the lock in ``BookingService`` is what
    prevents overselling. The ``time.sleep`` stands in for the round trip a real
    implementation would make between reading the counter and writing it back — that
    gap is the whole reason the read-modify-write is unsafe, and without it the GIL
    hides the bug and the comparison would prove nothing.
    """

    def book(self, candidate_id: str, station_id: str, slot_start: str) -> Booking:
        station = self.stations.get(station_id)
        if station is None:
            raise KeyError(f"unknown station {station_id!r}")
        if station.booked >= station.open_quota:  # read
            raise QuotaExhausted(f"station {station_id!r} has no remaining slots")
        booking = Booking(
            id=str(uuid.uuid4()),
            candidate_id=candidate_id,
            station_id=station_id,
            slot_start=slot_start,
        )
        # The durable write happens between the check and the counter update, which is
        # exactly where a real implementation loses the race.
        if self._on_save is not None:
            self._on_save(booking)
        station.booked += 1  # write
        self.bookings.append(booking)
        return booking


def recommend_stations(
    stations: list[Station], lat: float, lng: float, limit: int = 3, slot_hours: int = 2
) -> list[dict]:
    """Sort by distance, then by remaining quota, and return bookable time slots.

    Distance is the haversine distance in kilometres, so the ordering is the real one a
    job seeker would expect rather than a lexicographic accident.
    """
    import math

    def distance_km(station: Station) -> float:
        r = 6371.0
        p1, p2 = math.radians(lat), math.radians(station.lat)
        dp = p2 - p1
        dl = math.radians(station.lng - lng)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * r * math.asin(math.sqrt(a))

    ranked = sorted(
        (s for s in stations if s.remaining > 0),
        key=lambda s: (round(distance_km(s), 3), -s.remaining, s.id),
    )
    start = utcnow().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    out = []
    for station in ranked[:limit]:
        slots = [
            (start + timedelta(hours=slot_hours * i)).isoformat(timespec="minutes")
            for i in range(min(station.remaining, 5))
        ]
        out.append(
            {
                "station_id": station.id,
                "name": station.name,
                "distance_km": round(distance_km(station), 3),
                "remaining": station.remaining,
                "slots": slots,
            }
        )
    return out
