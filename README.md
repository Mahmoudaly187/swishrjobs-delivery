# SwishrJobs delivery artifacts

Public, verifiable work produced by SwishrJobs. Each directory is a self-contained
deliverable: the artifact, the evidence behind any claim, and the tests or measurements
that back it.

| Directory | What it is |
|---|---|
| [`pii-vault-compliance/`](pii-vault-compliance/) | Personal-information vault and compliance module: field-level AES-256-GCM, a reversible anonymization library, RBAC with city/station scoping, a hash-chained audit log and retention handling. Runnable FastAPI service, 36 acceptance tests, and a mutation prover that breaks the module 12 ways to show every break is caught. Measured masking metrics, dependency scan and OWASP self-test included. |
| [`recruitment-workbench/`](recruitment-workbench/) | Rider recruitment workbench (Task 3/5 of the agent-based recruitment platform): candidate state machine with all 64 state pairs tested, phone-token lead deduplication, concurrency-safe booking with a committed 50-thread load test, and an HMAC-signed event outbox with retry and idempotency. FastAPI service, 32 acceptance tests, 12/12 mutation proof. |
| `bounty-143/` | mailschema 0.3.2 behaviour defect: description, evidence and report. |
| `raptorx-2026-11/` | RaptorX Research Challenge entry: five Solana research reports. |
| `flapjax-q86/` | Receipt Relay Q86 treasury-flow analysis. |

## Verifying the PII vault

```bash
cd pii-vault-compliance
./run_tests.sh     # 36 tests, 12/12 mutations caught, reports regenerated
```

Or step by step:

```bash
make install
make test          # 36 passed
make mutation      # 12 deliberate defects, 12 caught
make metrics       # recall and false-positive rate, regenerated
```

## Verifying the recruitment workbench

```bash
cd recruitment-workbench
./run_tests.sh              # 32 tests, load test PASS, 12/12 mutations caught
docker compose up --build   # service on http://localhost:8000, /docs, /workbench
```

Two results are worth reading before the rest. `reports/load_test.json` shows 50 threads
racing for the last 5 slots: the locked service books exactly 5, and the deliberately
unlocked one oversold in 20 of 20 runs, creating up to 50 bookings for 5 slots.
`reports/mutation_proof.json` shows 12 deliberate defects and that the suite catches
every one — including, on the first run, a concurrency test that was passing for the
wrong reason until the lock was made provably load-bearing.

`reports/masking_metrics.json` holds the measured figures and `scripts/evaluate_masking.py`
reproduces them, so the numbers can be checked rather than taken on trust.
