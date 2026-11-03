# SwishrJobs delivery artifacts

Public, verifiable work produced by SwishrJobs. Each directory is a self-contained
deliverable: the artifact, the evidence behind any claim, and the tests or measurements
that back it.

| Directory | What it is |
|---|---|
| [`pii-vault-compliance/`](pii-vault-compliance/) | Personal-information vault and compliance module: field-level AES-256-GCM, a reversible anonymization library, RBAC with city/station scoping, a hash-chained audit log and retention handling. Runnable FastAPI service, 36 acceptance tests, and a mutation prover that breaks the module 12 ways to show every break is caught. Measured masking metrics, dependency scan and OWASP self-test included. |
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

`reports/masking_metrics.json` holds the measured figures and `scripts/evaluate_masking.py`
reproduces them, so the numbers can be checked rather than taken on trust.
