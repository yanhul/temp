# Altium Audit Kit

Reusable evidence-first static/structural audit pipeline for Altium Designer projects.

## Single entrypoint

`python audit_kit.py --input <project-folder> --output <output-folder>`

Optional repair/verify loop:

`python audit_kit.py --input <project-folder> --output <output-folder> --repair`

### Input contract
- exactly one `*.SchDoc`
- exactly one `*.PcbDoc`
- optional one `*.PrjPcb`

The kit discovers the files itself. Project name, refdes, net names and blocker IDs are not hard-coded.

### Lifecycle

`INTAKE -> AUDIT -> EVIDENCE -> [PLAN -> AUTHORIZE -> APPLY] -> VERIFY`

Repair is fail-closed: no authoritative authorization means no mutation; the source PcbDoc is never overwritten; repair happens only on a working copy; the repaired board is re-audited by the same runner.

### Outputs
- `intake.json`
- `audit-initial/`
- `routing_repair_plan.json` when repair is requested
- `repair_receipt.json` when a mutation is applied
- `audit-verify/` after repair
- `summary.json` final machine-readable result

Placement and routing are first-class audit layers. Unsupported evidence remains UNKNOWN/BLOCKED/PARTIAL; parser success alone never means design PASS.

## Reuse layout

```
temp/
  tools/altium-audit/       # reusable kit
    audit_kit.py            # single entrypoint
    audit_runner.py
    execution_contract.py
    routing_repair_plan.py
    routing_repair_authorize.py
    routing_repair_apply.py
    audit_manifest.json
    ...
  <project-to-audit>/       # input fixture only
    board.SchDoc
    board.PcbDoc
    board.PrjPcb             # optional
```

See `AUDIT_PROTOCOL.md` and `REUSE_RUNBOOK.md`.

## Placement profiles

The placement engine has two execution profiles over one generic algorithm:

- **GENERIC**: requires an authority packet that declares fixed anchors and manufacturing/mechanical constraints.
- **QI9**: uses `authority/QI9-2604-A01-placement.json`; J1/J2/J3/J4/J5/J7/U15 are hard anchors and cannot be moved, rotated or layer-swapped.

Both profiles run the same sequence:

`FIXED ANCHORS -> INPUT SUFFICIENCY -> FUNCTIONAL ZONES -> FREE COMPONENT PLACEMENT -> ROTATION/TOP-BOTTOM -> CLEARANCE/ASSEMBLY -> ROUTING FEASIBILITY -> VERIFY`

The placement engine is planning-only until a separate mutation authority/backend is implemented. A placement candidate is not a manufacturing PASS.

## PDF schematic input

A schematic PDF can enter through `pdf_schematic.py`. The bridge reuses installed PDF/OCR/KiCad tools and delegates reconstruction to an external authoritative backend; it never guesses connectivity. See `PDF_SCHEMATIC.md`.
