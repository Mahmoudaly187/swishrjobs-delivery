# First real use of mailschema 0.3.2: writing and validating a MAP 0.3 description

- **Install and versions.** `node v24.21.0`, `npm 11.21.0`, package `mailschema@0.3.2`
  (`npm install mailschema@0.3.2`, then every command through `npx mailschema@0.3.2`).
  No other tool was needed; a MAP description is plain JSON.
- **Commands run, in order.**
  1. `curl -sL https://mailschema.org/registry/map-0.3.json -o reg.json` — read the Registry.
  2. `curl -sL https://mailschema.org/artifacts/map-0.3/contracts/publication-approval-0.1.json -o contract.json` — the contract for the type I picked, `publication-approval`.
  3. `npx mailschema@0.3.2 contract contract.json` — printed `Valid type contract https://mailschema.org/types/publication-approval 0.1` and `sha-256:de91a49de4cba91209be253456e7c56709791fff877a060560d4eada0cc9468c`, which I copied into `type.contractDigest`.
  4. Wrote my own `map-0.3-description.json` for a release page of mine (`urn:swishrjobs:content:reliability-page`, revision `r2`), not a copy of the Registry example.
  5. `npx mailschema@0.3.2 description map-0.3-description.json --contract contract.json` — printed `Valid MAP 0.3 description urn:uuid:6f0b2d84-1c7e-4a52-9b3f-2e7a5d10c948` and the digest on the second line.
- **Minutes from install to a valid description.** About 8 minutes: the install was seconds; most of it went on reading the contract's `detailsSchema` and writing a description that satisfies its conditionals.
- **Field broken on purpose, and the exact error.** I shortened `details.content.digest` to 63 hex characters. `npx mailschema@0.3.2 description broken.json --contract contract.json` printed exactly this on standard error and exited 1:
  ```
  /details/content/digest: must match pattern "^sha-256:[0-9a-f]{64}$"
  ```
  I then put the 64-character digest back and re-ran step 5 to confirm the digest below.
- **The step that slowed me most.** Working out the `destinations` conditional. `visibility` is an enum, and only `restricted` pulls in the required `audience.id`/`audience.revision`. The contract's `detailsSchema` expresses that as an `if`/`then` on the item schema, so reading the raw schema told me less than the validator did; the fastest path was to try `restricted` without an audience and read the two errors it returns (`must have required property 'audience'` and `must match "then" schema`).
- **Defect or doc gap, with an exact repro.** Without `--contract`, the CLI reports a description as valid even when the `type.contractDigest` it names is not the digest of any real contract. Repro:
  1. Set `type.contractDigest` in the description to `sha-256:0000000000000000000000000000000000000000000000000000000000000000`.
  2. Run `npx mailschema@0.3.2 description bad.json` (no `--contract`).
  3. It exits 0 and prints `Valid MAP 0.3 description urn:uuid:...` plus a digest.
  Only `--contract <contract.json>` catches it, and there the message is `/type/contractDigest: does not match`. The README does scope contract checks to `--contract`, and it tells readers to "pin them by digest", so the behaviour is defensible; the gap is that the success line reads as though the named contract was checked, and the second line prints the *description's* digest, not the contract's. A caller who treats "Valid MAP 0.3 description" as "the contract this names is real" is wrong. What I tried: the same description with `--contract` (fails correctly), a wrong type against the right contract (fails with `/type: names ... not this contract`), and a wrong `profile` (fails with `/profile: must be "https://mailschema.org/profiles/map/0.3"`).
- **One change I would make.** Make the success line say what was actually checked, for example `Valid MAP 0.3 description urn:uuid:... (core rules only; contract not checked)` when `--contract` is absent, and name the contract and its digest when it is present. That costs one line and removes the only way this run could mislead a reader.

Digest of the valid description, from step 5 (the CLI's second line, identical to `digest()` from the package):

```
sha-256:e53232c0cd78a5686e480b4aad6c54387dc4f998b5161710141aa5e4027e6ef0
```
