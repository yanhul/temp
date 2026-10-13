# REA Next — evidence-graph prototype

Status: **prototype / not yet benchmarked against REA**.

This is an independently owned experiment, not a fork or modification of `morluto/rea`.
It starts with the highest-leverage foundation: artifact-bound evidence lineage.
It does not implement a decompiler, execute target binaries, or claim parity with REA.

## Included

- Evidence records bound to one SHA-256 artifact digest.
- Parent references must exist before a child can be added.
- Verification records require a named verifier, environment digest, and observation lineage.
- Inferences cannot self-promote to verified facts.
- Missing, contradictory, or merely inferred evidence cannot produce `PASS`; absent required verification yields `INCONCLUSIVE`.
- Deterministic lineage traversal and standard-library unit tests.
- Explicit file-offset ↔ VA mapping; rejects gaps, overlaps, virtual-only bytes, and raw padding rather than guessing.
- Read-only PE32/PE32+ header parsing for image base, section table, and alignment metadata. Malformed signatures, truncated fields, invalid bounds, and unsupported optional headers fail closed.

## Run tests

```sh
cd experiments/rea_next
python -m unittest -v
```

## Remaining gated steps

1. Expand PE parser negative tests and validate against independently sourced real PE fixtures with known header/section values.
2. Add provider adapters that preserve provider/version/configuration and never silently fall back.
3. Add a hypothesis planner that selects the next probe by expected uncertainty reduction, cost, and risk.
4. Add semantic/version diff and behavioral reconstruction tests.
5. Benchmark against REA on the same authorized artifacts and independent ground truth.

## Safety and acceptance

Read-only by default. Do not load or execute untrusted artifacts as part of this module.
A future AIOS adapter must use the AIOS contract/permit/attempt/receipt/verification chain; this module is not an authority source.
Do not report speed or accuracy gains until reproducible paired benchmarks support them.
