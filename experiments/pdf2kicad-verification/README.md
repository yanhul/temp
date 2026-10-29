# PDF schematic to KiCad verification sandbox

This directory is an isolated copy of the converter under review. It does not replace the existing tools/altium-audit implementation and does not mutate any source PDF, schematic, or PCB.

## Modules
- pdfx.py: PDF vector/text extraction; preserves page['texts'] and adds page['tokens'] with per-character x coordinates.
- padsx.py: decodes hidden PI records using token positions when available; falls back to text-line positions.
- netsx.py: heuristic wire topology, pad endpoint/mid-segment checks, snap and mid-attachment diagnostics.
- main.py: CLI, wire/pad ratio sanity warning, unattached/ambiguous/mid-segment/snap-refused report.
- gen.py, kcx.py: emits a generic KiCad 9 DRAFT with generic passive symbols, not recovered library symbols.
- validate_output.py: syntax and warning checks; parser success is not electrical correctness.
- dump_debug.py: CSV diagnostics.
- verify_netlist.py: compares pin-set topology against ground-truth CSV; it does not compare net names.

## Usage
Install dependencies (pdfminer.six, pypdf, kiutils) and KiCad 9 CLI as needed, then run from this directory:

    python main.py input.pdf -o out_kicad
    python validate_output.py out_kicad
    python dump_debug.py input.pdf debug
    python verify_netlist.py out_kicad/input.kicad_sch ground_truth.csv

## Verification status
This branch is for integration and testing. It is NOT PASS for electrical correctness until run against the real PDF and compared with an authoritative reference netlist. The wire-color heuristic and generic AUTO:* symbols remain known limitations. Mid-segment proximity is geometric evidence only. Refdes-based snap refusal is heuristic and is not authoritative pin ownership.
