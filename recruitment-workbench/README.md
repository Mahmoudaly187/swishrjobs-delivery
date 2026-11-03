# Rider Recruitment Workbench — Task 3/5

Backend for the agent-based rider recruitment platform: candidates, leads, stations,
quotas, bookings, and an event outbox with signed webhooks.

This implements **Task 3/5** of the five-task programme against the **Shared Interface
Contract v1**. It is a runnable service, not a proposal: `docker compose up` starts it on
a clean machine, and the acceptance criteria each have a test that fails if the behaviour
regresses.

## Start it

```bash
git clone <this repo> && cd recruitment-workbench
./run_tests.sh              # tests + load test + mutation proof + regenerate reports
docker compose up --build   # service on http://localhost:8000
```

Interactive API documentation: <http://localhost:8000/docs> (OpenAPI 3, generated).
A demo workbench page with the personal watermark: <http://localhost:8000/workbench>.

Without Docker:

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m uvicorn app.main:app --port 8000
```

### Prove the gate, don't just read it

A green suite proves nothing on its own. `scripts/mutation_proof.py` removes one safety
property at a time and reports whether the suite notices.

```bash
make mutation     # 12 deliberate defects, 12 caught
```

```
baseline (unmutated): PASS
  remove_booking_lock              CAUGHT  (the per-station lock is what prevents overselling under concurrency)
  allow_illegal_transition         CAUGHT  (illegal candidate transitions must be rejected)
  disable_lead_dedup               CAUGHT  (deduplication by phone token must drop repeated leads)
  phone_token_skips_country_code   CAUGHT  (equivalent phone formats must normalise to the same token)
  signature_ignores_timestamp      CAUGHT  (the HMAC must cover the timestamp so a delivery cannot be replayed)
  delivery_handles_duplicates      CAUGHT  (a repeat delivery must not be acted on twice)
  no_retry_on_failure              CAUGHT  (a failed delivery must be retried)
  workbench_list_unmasked          CAUGHT  (the workbench list must be masked by default)
  reveal_without_reason            CAUGHT  (viewing a full number must require a stated reason)
  drop_bearer_auth                 CAUGHT  (employee routes must require a bearer token)
  drop_watermark                   CAUGHT  (workbench pages must carry a personal watermark)
  recommend_full_stations          CAUGHT  (a station with no remaining quota must not be recommended)

baseline green, then 12/12 deliberate defects caught
```

It earned its place twice over. The first run caught a concurrency test that was passing
for the wrong reason: removing the booking lock did not fail the suite, because with no
pause between the quota check and the counter update the GIL hid the race. The lock is
now shown to be load-bearing by a hook that stands in for the durable insert a real
deployment makes, and `remove_booking_lock` is caught. Committed as
`reports/mutation_proof.json`.

## Acceptance criteria, and where each is proven

| # | Criterion | Test | Evidence |
|---|---|---|---|
| 0 | Runnable deliverable, source + startup instructions | `docker compose up`, `./run_tests.sh` | this README |
| 1 | 100 leads with duplicates import; dedup count correct; assignment takes effect | `test_c1_*` (5 tests) | `reports/import_report.json` |
| 2 | Candidate state machine; illegal transitions rejected; **all state pairs** covered | `test_c2_*` (7 tests, walks all 64 ordered pairs) | `reports/state_machine.json` |
| 3 | 50 concurrent bookings for the last 5 slots: exactly 5 succeed | `test_c3_fifty_concurrent_bookings`, `scripts/load_test_bookings.py` | `reports/load_test.json` |
| 4 | Every state change emits an event; HMAC signature; retry; idempotency | `test_c4_*` (6 tests) | `reports/events.json` |
| 5 | Workbench masked by default; full number needs a reason | `test_c5_*` (4 tests) | — |
| 6 | Personal watermark on pages | `test_c6_workbench_page_carries_the_watermark` | `/workbench` |
| 7 | OpenAPI + contract tests; one command, all green | `test_c7_*` (3 tests), `make test` | `/openapi.json` |

Two of these are worth calling out because they are the ones usually faked.

**Criterion 2, all state pairs.** The transition table in `app/state_machine.py` is the
single source of truth, and the test walks `STATES x STATES` — 64 ordered pairs —
asserting that exactly the 16 legal ones pass and the other 48 are rejected. Coverage of
the state space is therefore a property of the code, not of the author's diligence.

**Criterion 3, no overselling.** `app/booking.py` ships two services. `BookingService`
holds a per-station lock across the check and the insert. `NaiveBookingService` does not,
and exists so the load test can show the failure mode rather than assert that the good
one works: across 20 runs of 50 threads for 5 slots it oversold **20/20**, creating up to
50 bookings for 5 slots. The locked service held the quota exactly, 5 of 5, every run.

## Layout

| Path | Purpose |
|---|---|
| `app/state_machine.py` | Candidate states, the legal transition table, and the event each emits. |
| `app/leads.py` | Lead pool, phone-token deduplication, deterministic round-robin assignment. |
| `app/booking.py` | Stations, quota-safe booking, cancellation, distance-ranked recommendations. |
| `app/events.py` | Transactional outbox, HMAC-SHA256 signing, retry, idempotent receiver. |
| `app/main.py` | FastAPI surface under `/api/v1`, contract error bodies, vault mock. |
| `tests/test_acceptance.py` | 32 tests, grouped by criterion. |
| `scripts/load_test_bookings.py` | The committed concurrency load test (criterion 3). |
| `scripts/mutation_proof.py` | Breaks the module 12 ways and proves the suite catches each. |
| `scripts/write_reports.py` | Regenerates every report under `reports/`. |
| `data/leads_sample.csv` | 100 synthetic leads including duplicates (criterion 1). |
| `reports/` | The measured evidence. |

## Shared Interface Contract v1 — what is implemented

* **Stack.** Python 3.12, FastAPI, Pydantic. Dependencies are MIT / BSD / Apache-2.0 only;
  no GPL or AGPL anywhere in the tree.
* **API.** REST under `/api/v1`, JSON bodies, errors as `{code, message}`. Employee routes
  take a `Bearer` token.
* **Candidate fields.** All contract fields are present on the model.
* **Events.** `candidate.created`, `candidate.updated`, `candidate.completed`,
  `booking.created`, `booking.cancelled`, `handoff.requested`.
* **Masking.** `138****8000` for a phone number, `王**` for a name.
* **Vault.** `/api/v1/vault/tokenize` and `/api/v1/vault/detokenize` are mocked here, per
  the contract's "write your own mocks, do not wait for others". Task 5 replaces them.

### Deliberate deviations, stated rather than hidden

* **Storage is in-process.** The contract specifies PostgreSQL 16 with pgvector and Redis.
  The domain logic, the state machine, the quota guarantee and the outbox are all
  independent of the store, so wiring a real database is a substitution rather than a
  rewrite — but it is not done here, and the service is therefore not horizontally
  scalable as shipped. A single-process service with a per-station lock is correct on one
  node; across nodes the guarantee needs a database constraint (`SELECT ... FOR UPDATE`, or
  a unique index on `(station_id, slot_start)`) and that is the first thing to add when the
  store lands.
* **The frontend is not built.** Criterion 5's list and detail views and criterion 6's
  watermark are demonstrated on the server-rendered `/workbench` page, which shows the
  real masking behaviour and a real watermark. The React + Ant Design client is out of
  scope for this repository.
* **Identity is a seam.** `_require_employee` accepts any well-formed bearer token. It is
  one function, so replacing it with JWKS validation against the identity provider's keys
  touches no route.
* **Synthetic data only.** `data/leads_sample.csv` is generated, no real personal
  information appears anywhere, and nothing in the test suite calls an external LLM.

## Licence notes

Every dependency is permissive: FastAPI (MIT), Starlette (BSD-3-Clause), Pydantic (MIT),
Uvicorn (BSD-3-Clause), httpx (BSD-3-Clause), pytest (MIT). None is GPL or AGPL.
