# Altium Audit Kit

Reusable evidence-first static/structural audit pipeline for Altium Designer projects.

## Baseline input
- **Required:** one `*.SchDoc` and one `*.PcbDoc`
- **Optional:** `*.PrjPcb` when project-level rules/settings are needed

Placement and routing are first-class audit layers. They are not reduced to “component is inside board”.

## Gates
- G0 INTAKE
- G1 PARSE
- G2 COMPILE
- G3 CONNECTIVITY
- G4 PCB RULE EVIDENCE
- G5 ELECTRICAL
- G6 PHYSICAL
- G6 PLACEMENT
- G7 ROUTING
- G7 FUNCTIONAL
- G8 REPORT

### Placement
The runner records board containment, component geometry, pairwise overlap/clearance evidence, connector-area congestion signals and routing-corridor/choke-point evidence where parser fields permit.

### Routing
The runner records authoritative unrouted/ratsnest evidence, routed primitive/net inventory, layer transitions and topology limitations. It never claims zero unrouted from missing API data.

### Evidence boundary
`PrjPcb` upgrades project-rule evidence. Its absence must not block the baseline SchDoc+PcbDoc placement/routing audit.

Full Altium DRC equivalence, 3D collision completeness, SI/timing and design intent remain UNKNOWN/BLOCKED unless authoritative evidence is available.

See `AUDIT_PROTOCOL.md` and `REUSE_RUNBOOK.md`.
