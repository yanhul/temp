# Altium Audit Protocol

## 1. Intake
Baseline audit requires exactly the design sources needed for structural review:
- mandatory: `*.SchDoc`, `*.PcbDoc`
- optional: `*.PrjPcb` for authoritative project-level rules/settings

Missing project file must not prevent schematic/PCB placement/routing audit.

## 2. Schematic
Inspect compile diagnostics, connectivity, pin semantics, references, footprints, power, decoupling, pullups/pulldowns, connector pinout and sensitive nets.

## 3. PCB / Placement
Audit directly from PcbDoc:
- board outline and containment
- component geometry/bounds and overlap
- component-to-component clearance evidence
- mounting holes / keepouts when parser fields expose them
- connector/switch access geometry
- Top/Bottom and orientation
- functional grouping when design intent is supplied
- placement-created routing corridors and choke points
- connector/switch access and local congestion using generic object classes; no project-specific refdes are encoded in the kit

A generic clearance number is never invented. If no authoritative minimum exists, report measured geometry and mark the design-rule conclusion UNKNOWN.

## 4. PCB / Routing
Audit directly from PcbDoc:
- unrouted/ratsnest evidence
- track/via/layer transitions
- route topology per net
- dangling/stub signals where evidence permits
- width/clearance against exposed authoritative rules
- keepout interaction
- GND/power/clock/differential/communication net inventory
- connector -> protection -> transceiver/MCU -> load flow when net/intent evidence supports it
- routing choke points

## 5. Cross-domain
Reconcile SCH refdes <-> PCB refdes and SCH pin/net <-> PCB pad/net.

## 6. Evidence limits
Two files can VERIFY geometry, connectivity, placement and exposed routing facts. They do not by themselves prove:
- 100% Altium DRC equivalence
- full 3D mechanical collision without 3D model data
- SI/timing
- project-specific intent

## 7. Finding contract
Every Placement/Routing finding carries:
- severity
- domain
- status
- exact object/refdes/net where available
- measured/observed evidence
- confidence label

Never report parser success as design PASS.
