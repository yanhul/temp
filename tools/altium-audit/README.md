# Altium Audit Kit

Reusable static/structural audit pipeline for Altium Designer projects.

## Intake
1. Export/zip the project containing `*.PrjPcb`, `*.SchDoc`, and `*.PcbDoc`.
2. Put the archive into the audit runner (or split it into `b64parts/part_*.txt` when GitHub file-size limits require it).
3. Run the GitHub Actions audit.
4. Do not call PASS from parser success alone.

## Evidence gates
- G0 INTAKE: archive reconstructs byte-for-byte and expected Altium files exist.
- G1 PARSE: project/schematic/PCB load successfully.
- G2 COMPILE: diagnostics, component/net counts, references and connectivity are extracted.
- G3 CONNECTIVITY: schematic netlist vs PCB connectivity/component mapping is checked.
- G4 PCB: pads, vias, tracks, pours/regions, layers and mechanical data are inspected.
- G5 ELECTRICAL: power, GND, single-pin nets, suspicious pins, pullups/pulldowns, decoupling and connector pinout are reviewed.
- G6 PHYSICAL: shorts, unrouted items, clearances, widths, vias, copper/pad overlaps, silkscreen and mounting constraints are checked where parser evidence permits.
- G7 FUNCTIONAL: design-intent review; DRC/ERC-clean is never treated as functional correctness.
- G8 REPORT: every finding is FACT / VERIFIED / INFERRED / ASSUMPTION with source evidence.

## Status
- PASS = all applicable gates have evidence.
- BLOCKED = parser/data/API coverage prevents a required gate.
- FAIL = verified design issue.
- UNKNOWN = insufficient evidence; never silently convert to PASS.

## Output
Produce:
- `summary.json`
- `netlist.json`
- `design.json`
- `pcb_probe.txt`
- human-readable findings report

This kit is intentionally evidence-first and reusable across projects.
