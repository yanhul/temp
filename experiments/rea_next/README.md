# REA Next — evidence-graph prototype

Status: **prototype / not yet benchmarked against REA**.

This is an independently owned experiment, not a fork or modification of `morluto/rea`.
It starts with the highest-leverage foundation: artifact-bound, append-only evidence lineage.
It deliberately does not implement a decompiler, execute target binaries, or claim parity with REA.

## Included

- Evidence records bound to one SHA-256 artifact digest.
- Parent references must exist before a child can be added.
- Verification records require a named verifier, environment digest, and observation lineage.
- Inferences cannot self-promote to verified facts.
- Missing, contradictory, or merely inferred evidence cannot produce `PASS`; absent required verification yields `INCONCLUSIVE`.
- Deterministic lineage traversal and standard-library unit tests.
- Explicit file-offset ↔ VA mapping from caller-supplied section metadata; rejects gaps, overlaps, and virtual-only bytes instead of guessing.

## Run tests

```sh
cd experiments/rea_next
python -m unittest -v
```

## Next gated steps

1. Extend address mapping with format-specific parsers and independently verified fixtures; current mapper requires trusted caller-supplied section metadata.
2. Add provider adapters that preserve provider/version/configuration and never silently fall back.
3. Add a hypothesis planner that selects the next probe by expected uncertainty reduction, cost, and risk.
4. Add semantic/version diff and behavioral reconstruction tests.
5. Benchmark against REA on the same authorized artifacts and independent ground truth.

## Safety and acceptance

Read-only by default. Do not load or execute untrusted artifacts as part of this module.
A future AIOS adapter must use the AIOS contract/permit/attempt/receipt/verification chain; this module is not an authority source.
Do not report speed or accuracy gains until reproducible paired benchmarks support them.
