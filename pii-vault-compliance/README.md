# PII Vault & Compliance Module

Task 5/5 of the Agent-Based Rider Recruitment Information Collection Platform: the data
security and compliance module.

This repository is the deliverable, not a description of one. It contains the running
service, the synthetic evaluation corpus, the measurement scripts that produce the
reported numbers, the dependency scan and the OWASP self-test. Every acceptance
criterion is covered by a test that fails if the behaviour regresses.

## Start it

```bash
make install        # runtime + dev dependencies
make test           # the acceptance suite — the single command, all green
make demo           # serve on http://localhost:8000
```

Or with containers:

```bash
docker compose up --build
```

Interactive API docs are at `http://localhost:8000/docs`.

## What is here

| Path | Purpose |
|---|---|
| `pii_vault/kms.py` | Pluggable key management: `LocalFileKMS` and a `VaultKMS` adapter for HashiCorp Vault. Keys live outside the repository. |
| `pii_vault/vault.py` | Field-level AES-256-GCM seal/open, tokenization, and key rotation that keeps historical keys readable. |
| `pii_vault/masking.py` | The anonymization library: Chinese names, mobile and landline numbers, national ID numbers, bank-card numbers and detailed addresses, replaced with `[type_sequence]` placeholders and reversible in a controlled environment. |
| `pii_vault/rbac.py` | Five roles with city / station scoping and two separate powers, `view_full` and `export`. |
| `pii_vault/audit.py` | Append-only hash-chained audit log with tamper location. |
| `pii_vault/retention.py` | Retention window, expiry cleanup, immediate deletion on consent withdrawal. |
| `pii_vault/api.py` | The HTTP surface. |
| `scripts/generate_samples.py` | Builds the 240-sample synthetic corpus. |
| `scripts/evaluate_masking.py` | Measures recall and false-positive rate and writes `reports/masking_metrics.json`. |
| `scripts/write_reports.py` | Regenerates the dependency scan report. |
| `tests/test_acceptance.py` | 32 tests, grouped by acceptance clause. |
| `reports/` | The measured evidence: masking metrics, dependency scan, OWASP self-test. |

## How each acceptance criterion is met

**0) Deliverables first.** This repository is runnable: `make install && make test`, or
`docker compose up --build`. Startup instructions are above and repeated in `Makefile`.

**1) tokenize / detokenize; no plaintext in the row; rotation keeps old data readable.**
Every field is sealed separately with AES-256-GCM under a key from the KMS. The row holds
only a token, a key id, a nonce and ciphertext — the test asserts this by reading the row
directly and searching for the plaintext. The additional authenticated data binds the
token and field name, so a ciphertext cannot be relocated to another row or field.
Rotation re-wraps every field under a new key while the token stays stable, and the old
key is retained, so data written before the rotation still decrypts.
Tests: `test_c1_*` (4 tests).

**2) Masking tool with ≥200 synthetic samples; stated recall and false-positive rate.**
The corpus is 240 labelled samples: 200 positive, 40 negative, with the awkward formats
the brief asks for — numbers with spaces and hyphens, `+86` and bare `86` prefixes,
lowercase `x` ID checksums, grouped bank cards, foreign names, long addresses.

Measured on that corpus (`reports/masking_metrics.json`, regenerate with `make metrics`):

| Field | Recall | Support |
|---|---|---|
| phone | 100% | 130 |
| id | 100% | 113 |
| bankcard | 100% | 116 |
| name | 100% | 128 |
| address | 100% | 123 |

False-positive rate: **0.00%** (0 of 40 negative samples; 0 spurious spans). The negative
set is ordinary recruiting prose — rosters, policy notes, meeting minutes — which is where
a name detector normally misfires.

Caveat stated plainly: this is a synthetic corpus we generated, so these figures measure
the detector against our own sampling, not against production traffic. The corpus and the
script ship so the numbers can be re-run and extended rather than trusted.

**3) detokenize refused without permission or reason, both logged.** Two distinct paths.
A role without the `detokenize` power gets 403 and the attempt is written to the audit log
with `cause: no_power`. A permitted role with an empty reason gets 400 and the attempt is
logged with `cause: no_reason`. A successful detokenization is logged with its reason.
Tests: `test_c3_*` (3 tests).

**4) Tampering with the audit log is located.** Each entry commits to the hash of its
predecessor. `verify_chain` returns the 0-based index of the first entry that fails to
hash or fails to chain. Verified both in-process and over the API against an exported,
then edited, chain.
Tests: `test_c4_*` (3 tests).

**5) Retention cleanup and consent withdrawal.** Retention is 180 days by default
(`PII_RETENTION_DAYS`). Past the window a record is anonymized — PII stripped, aggregate
kept — and a deletion record names the trigger and the reason. Consent withdrawal deletes
immediately regardless of age. Time is injected, so the tests fast-forward by
construction rather than sleeping.
Tests: `test_c5_*` (4 tests).

**6) Cross-city / cross-station access refused, with a case per role.** `recruiter` and
`station_manager` are scoped to a station; `operations` to a city; `admin` and `auditor`
are global. Viewing full data needs the `view_full` power *and* a stated reason; export
needs the `export` power *and* an approved approval id. `auditor` is read-only.
Tests: `test_c6_*` (9 tests, covering all five roles plus the export path).

**7) Dependency scan and OWASP self-test, no unaddressed high-severity items.**
`reports/dependency_scan.txt` is produced by `pip-audit` over the pinned dependency set and
carries a machine-checkable `unaddressed_high_severity: 0`, which a test asserts.
`reports/owasp_self_test.md` maps the module to the OWASP Top 10 (2021) with the test that
demonstrates each control, and lists residual risk rather than claiming full coverage.

**8) Unit tests pass with a single command.** `make test`, or `python3 -m pytest -q`:
**32 passed**. The suite is the verification record; there is no separate document to trust.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `PII_KMS` | `local` | `local` or `vault` |
| `PII_KMS_DIR` | `/tmp/pii-vault-kms` | key directory for the local adapter (mode 0700) |
| `PII_RETENTION_DAYS` | `180` | retention window |
| `VAULT_ADDR`, `VAULT_TOKEN`, `VAULT_MOUNT` | — | HashiCorp Vault connection |

## Using the anonymization library from Tasks 1 and 3

```python
from pii_vault import Masker

masker = Masker()
result = masker.mask("联系人：李四，手机号 13900139000，身份证 110101199003071233")
# result.masked -> "联系人：[name_1]，手机号 [phone_1]，身份证 [id_1]"
# result.mapping -> {"[name_1]": "李四", "[phone_1]": "13900139000", "[id_1]": "..."}

original = masker.unmask(result.masked, result.mapping)   # controlled environment only
```

The same function is exposed over HTTP at `POST /v1/mask`, which is the integration point
for Tasks 1 and 3 without importing this package.

## Identity in this reference build

Roles arrive as request headers (`x-role`, `x-actor`, `x-city`, `x-station`). That is a
test seam so the suite can exercise every role without a live identity provider. In
production the verified token from the platform's IdP replaces it; the mapping is isolated
in `rbac.principal_from_headers` and nothing else reads identity from the request.

## Not implemented, and said so

Anomaly alerting thresholds, rate limiting, and a live Vault integration are out of scope
for this delivery. The events an alerting layer needs are recorded; the thresholds belong
to the integrating party. See `reports/owasp_self_test.md`, *Residual risk*.
