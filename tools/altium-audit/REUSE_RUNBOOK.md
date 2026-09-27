# Reusable Altium Audit Runbook

## Purpose
This kit is the reusable audit standard. A new Altium project supplies only project intake/configuration; the audit engine remains project-agnostic.

## Architecture
1. Kit / engine — parser adapters, evidence collection, deterministic checks, gate evaluation.
2. Project config — archive name, project ID, source hash, and optional audit profile.
3. CI adapter — reconstructs and validates the exact source archive, invokes the engine, preserves artifacts, and enforces final status.

Never put project-specific refdes, net names, footprints, coordinates, or expected counts into the engine.

## Standard lifecycle
INTAKE -> PARSE -> COMPILE -> CONNECTIVITY -> PCB -> ELECTRICAL -> PHYSICAL -> FUNCTIONAL -> REPORT

Every gate emits machine-readable evidence.

## Status semantics
- VERIFIED: available authoritative evidence proves the stated property.
- FAIL: a concrete violation was verified.
- BLOCKED: a required property cannot be proven with available evidence.
- UNKNOWN: evidence is insufficient; use when the individual check is indeterminate.
- PASS: reserved for a complete audit where every required gate is proven and no verified violation exists.

A parser limitation must never be converted into PASS.

## Required evidence lineage
source archive SHA256 -> parsed object -> check -> finding -> gate -> report

The report must distinguish FACT, VERIFIED, INFERRED, and ASSUMPTION.

## Gate contract
### G0 — Intake
Prove required Altium source files exist, reconstructed archive is byte-identical to the authoritative source when supplied, and source SHA256 is recorded.

### G1 — Parse
Prove project/schematic/PCB can be loaded by the pinned parser. Record parser version.

### G2 — Compile
Collect compile metadata and parser diagnostics. Compile success is not design correctness.

### G3 — Connectivity
Reconcile schematic references <-> PCB references, schematic terminals <-> PCB pads, and schematic net <-> PCB pad net. Unresolved parser metadata must not manufacture false failures.

### G4 — PCB rules
Collect native rule inventory and run only checks whose rule scope and object fields are exposed. Do not claim full Altium DRC without an authoritative DRC engine.

### G5 — Electrical
Use conservative structural evidence: single-terminal nets, definite output/output conflicts, named supply/ground inventory, and directly observable decoupling. Do not infer source capability merely from generic/passive pin type.

### G6 — Physical
Run deterministic geometry checks supported by exposed geometry: board outline, implicit polygon closure, component placement bounds, and primitive/routing bounds where coordinates are authoritative. Clearance/hole/component checks require both geometry and applicable rule values. Full mechanical/DRC equivalence remains BLOCKED unless an authoritative DRC result is supplied.

### G7 — Functional
Require explicit design intent. Review power sequencing, protection, voltage-level compatibility, termination/bias, current/thermal paths, connector polarity, sensitive interfaces, and reset/boot behavior.

### G8 — Report
Publish summary.json, findings.json, design.json, netlist.json, probe files, report.md, and runner exit status.

## Reuse procedure
1. Copy tools/altium-audit/ unchanged.
2. Copy PROJECT_CONFIG.example.json to a project-level config.
3. Set only project_id, source_archive, and source-hash policy.
4. Put the Altium archive and ordered b64parts/ under the CI intake convention.
5. Run the standard workflow.
6. Inspect summary.json first, then findings.json, then probes.
7. If a gate is BLOCKED, add an evidence adapter/check rather than weakening the gate.
8. Never copy findings from one project to another.

## Reusable-improvement rule
A change belongs in the kit only if it works without project-specific identifiers, has deterministic evidence, has a regression fixture or CI proof, preserves status semantics, and does not turn unsupported checks into PASS. Project-specific exceptions belong in project config or a separate adapter.
