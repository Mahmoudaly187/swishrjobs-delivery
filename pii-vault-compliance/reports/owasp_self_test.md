# OWASP self-test report

Scope: the PII Vault & Compliance Module (Task 5/5) as delivered in this repository.
This is a self-assessment of the code we wrote, mapped to the OWASP Top 10 (2021).
Each line states the control, and the test that demonstrates it. Anything not
implemented is listed under *Residual risk* rather than claimed as covered.

| # | OWASP risk | Control in this module | Evidence |
|---|---|---|---|
| A01 | Broken access control | Five roles with explicit scope (`station` / `city` / `all`) and two separate powers, `view_full` and `export`. Scope is checked on every read, detokenize, export and raw-row route. | `tests/test_acceptance.py::test_c6_*` (8 tests, one per role plus cross-scope denials) |
| A02 | Cryptographic failures | AES-256-GCM per field, fresh 96-bit nonce per write, key id stored beside the ciphertext, keys held by a KMS adapter and never in the row. AAD binds the token and field name so ciphertext cannot be relocated between rows or fields. | `test_c1_raw_row_contains_no_plaintext`, `test_c1_distinct_ciphertexts_for_equal_plaintext` |
| A03 | Injection | No SQL string building: the reference API holds records in a dict behind typed Pydantic models. A production port uses SQLAlchemy parameter binding; there is no f-string or `%`-formatted SQL anywhere in the tree. | `grep -rn "execute(" pii_vault/` returns nothing |
| A04 | Insecure design | Default is masked; full value requires both a power and a stated reason; export additionally requires an approval id. Failures are closed, not open. | `test_c3_*`, `test_c6_export_requires_approval` |
| A05 | Security misconfiguration | No secrets in the tree; key material lives outside the repository under `PII_KMS_DIR` with mode 0700/0600. Dependency set is pinned. | `reports/dependency_scan.txt`, `pii_vault/kms.py::LocalFileKMS.__init__` |
| A06 | Vulnerable components | `pip-audit` over the pinned set reports no known vulnerabilities. | `reports/dependency_scan.txt` |
| A07 | Identification and authentication failures | Requests without a recognised role are rejected 401 before any handler runs. Production replaces the header mapping with the IdP's verified claims; the mapping point is isolated in `rbac.principal_from_headers`. | `test_c6_missing_role_is_unauthenticated` |
| A08 | Software and data integrity failures | The audit log is append-only and hash-chained; every entry commits to its predecessor. Tampering is detected and located. | `test_c4_tampering_is_located`, `test_c4_tampering_detected_over_the_api` |
| A09 | Logging and monitoring failures | Views, detokenizations (granted and denied), exports, deletions and key rotations are all recorded with actor, reason and timestamp. | `test_c3_*`, `test_c5_deletion_records_are_produced_over_the_api` |
| A10 | Server-side request forgery | The service makes no outbound requests. The Vault KMS adapter is the only egress point and its address is operator configuration, not user input. | `grep -rn "urlopen\|requests\." pii_vault/` returns nothing outside `kms.py` |

## Residual risk

* **Masking is a detection problem, not a proof.** Recall is 100% for phone numbers
  and national ID numbers, and 100% for names and addresses, on the 200-sample
  synthetic corpus; the false-positive rate is 0%. On real traffic these numbers
  will be lower. The measured figures and the corpus ship with the repository so the
  claim can be re-run rather than trusted: `reports/masking_metrics.json`,
  `scripts/evaluate_masking.py`.
* **No transport security in the reference app.** The module is intended to run
  behind the platform's TLS terminator. Running it directly over plain HTTP would
  expose detokenized values on the wire.
* **Rate limiting and anomaly alerting are specified but not implemented here.**
  The brief asks for anomaly alerts; this delivery records the events an alerting
  layer would consume and leaves the alert thresholds to the integrating party.
* **The header-based principal is a test seam.** It must not be exposed on a public
  listener. In production the identity provider's verified token replaces it.
