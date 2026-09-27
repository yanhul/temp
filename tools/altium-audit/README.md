# Altium Audit Kit

Reusable evidence-first static/structural audit pipeline for Altium Designer projects.

## Runner
The executable audit logic lives in `audit_runner.py`; the GitHub Action is only the orchestration layer.

### Intake
1. Supply an archive containing `*.PrjPcb`, `*.SchDoc`, and `*.PcbDoc`.
2. If the archive cannot be committed directly, split its base64 bytes into ordered `b64parts/part_*.txt`.
3. Reconstruct the archive in CI.
4. Run `audit_runner.py`.
5. Review artifacts; parser/compile success is never a design PASS.

### Evidence gates
- G0 INTAKE: required files + optional authoritative source SHA256.
- G1 PARSE: project/schematic/PCB load.
- G2 COMPILE: diagnostics and compile metadata.
- G3 CONNECTIVITY: SCH↔PCB references and terminal/pad net reconciliation.
- G4 PCB: native rule inventory plus deterministic checks that have sufficient parser fields.
- G5 ELECTRICAL: conservative net/pin semantic checks.
- G6 PHYSICAL: geometry/mechanical coverage; unsupported checks remain UNKNOWN.
- G7 FUNCTIONAL: explicit design-intent review; DRC/ERC-clean is not functional correctness.
- G8 REPORT: machine-readable and human-readable evidence.

## Status semantics
- **FAIL** = verified issue.
- **BLOCKED** = a required gate cannot be proven with available evidence.
- **UNKNOWN** = insufficient evidence.
- **PASS** is intentionally reserved for a future run in which every applicable gate has authoritative evidence.

## Artifacts
`summary.json`, `netlist.json`, `design.json`, `pcb_probe.txt`, `g4_probe.json`, `findings.json`, `report.md`.

## Reuse
For another Altium project, replace only the project intake/archive. Do not copy project-specific findings or hard-code refdes/net names into the runner.


## Reusable-kit boundary

The kit is project-agnostic. Project-specific intake belongs in the repository-level `altium-audit.config.json`.

For a new project:
1. copy this directory unchanged;
2. copy `PROJECT_CONFIG.example.json` to `altium-audit.config.json`;
3. set `project_id`, `source_archive`, and `base64_parts_dir`;
4. use `workflow-template.yml` as the CI adapter;
5. never add project-specific refdes/net/coordinate expectations to `audit_runner.py`.

See `REUSE_RUNBOOK.md` for the standard lifecycle and evidence contract.
