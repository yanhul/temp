# Altium Audit Protocol

## 1. Intake
Verify archive integrity, required files, project references and extracted paths.

## 2. Schematic
Inspect:
- ERC-like compile diagnostics
- unconnected/single-pin nets
- GND/VCC/power-input/output semantics
- pin-type conflicts
- net labels and hierarchical connectivity
- references/values/duplicates
- footprints
- decoupling
- pullups/pulldowns
- connector pinout
- differential/sensitive nets

Single-pin nets are SUSPECT only until context proves intentional.

## 3. PCB
Inspect:
- component/pad/net mapping
- tracks, vias, arcs, fills, regions
- layer assignment
- unrouted connectivity
- shorts/clearance where geometry/API exposes enough evidence
- track width and via policy
- GND plane/pour connectivity
- thermal relief
- pad-to-pin mapping
- silkscreen/mechanical conflicts
- mounting holes and board outline
- creepage/clearance when applicable

## 4. Cross-domain
Build a reconciliation:
SCH component/refdes <-> PCB component/refdes
SCH pin/net <-> PCB pad/net
footprint expected <-> actual footprint
missing/extra/unmatched objects

## 5. Functional review
Check circuit intent independently of formal DRC/ERC:
power sequencing, protection, level compatibility, termination, reset/boot, analog sensitivity, current paths, thermal/current capacity and connector polarity.

## 6. Evidence discipline
Each finding must contain:
- severity
- domain
- exact object/refdes/net/pin
- observed evidence
- why it matters
- confidence: VERIFIED / INFERRED / ASSUMPTION
- recommended verification in Altium when parser coverage is insufficient

Never report a parser success as a design PASS.
