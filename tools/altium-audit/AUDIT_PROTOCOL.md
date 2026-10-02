# Altium Audit Kit Contract

## 1. Input contract
`*.SchDoc` + `*.PcbDoc` are mandatory. `*.PrjPcb` is optional and is evidence for project-level rules/settings. Input discovery is extension-based; filenames and reference designators are never configuration.

## 2. Normalized evidence semantics
- `VERIFIED`: authoritative parser/evidence supports the claim.
- `UNKNOWN`: required evidence is unavailable, or only a non-authoritative fallback exists.
- `INCOMPLETE`: evidence exists but a required closure item is missing.
- `BLOCKED`: the policy/authority gate forbids the next action.
- `TOPOLOGY_UNRESOLVED`: disconnected copper is observed, but the intended topology/placement decision is not established. It is never permission to bridge.
- `PASS`: all required gates for the requested stage are verified.
- `FAIL`: execution/verification produced a demonstrated failed condition.
- `INCONCLUSIVE`: execution completed but evidence did not establish PASS or FAIL.

Parser success is not design PASS.

## 2.1 Schematic semantic authority
Before any PCB planning, mutation, placement lock, or routing repair, the compiled schematic must pass the semantic authority gate.

The semantic sweep checks, at minimum:
- component identity: designator, value, footprint, library reference and compiled identity;
- component uniqueness and schematic/netlist identity reconciliation;
- pin identity: component reference, pin number, pin name and electrical pin type;
- one-pin/one-net consistency and multiple-driver conflicts;
- single-terminal nets, which remain BLOCKED until intentional NC/testpoint/waiver intent is authoritative;
- functional intent authority. Connectivity and parser output do not prove that a component, pin, net or topology performs the intended circuit function.

Missing functional intent is BLOCKED, not PASS. The kit must therefore stop before PCB execution when G2_SCHEMATIC != VERIFIED.

A functional-intent packet may be supplied through project configuration, but the generic engine never invents one from component names, popularity, or net-name heuristics. Heuristics can provide review evidence but cannot create authority.

## 3. Placement
Placement evidence must come through the parser adapter/interface. Direct component geometry can support `VERIFIED` placement evidence. Pad-geometry fallback is evidence only and remains `UNKNOWN` for placement decision purposes until authoritative component placement evidence exists.
The engine must not infer functional grouping, preferred component locations, routing corridors, or mechanical intent from a particular fixture.

## 4. Routing / topology
Audit:
- unrouted/ratsnest evidence when exposed by the parser;
- tracks, vias, layers and topology;
- width/clearance only against authoritative exposed rules;
- keepouts/copper-area interactions when evidence exists;
- net-level graph connectivity.

A disconnected graph may generate a plan candidate, but the plan remains `TOPOLOGY_UNRESOLVED` and `candidate_topology=NOT_SELECTED` until an authoritative decision/evidence artifact establishes the intended topology.

## 5. Authorization and mutation
`PLAN` is non-mutating and cannot create authority.
`AUTHORIZE` may set `mutation_authorized=true` only when:
1. the finding is authoritative;
2. the candidate endpoints belong to distinct proven components of the same net;
3. applicable clearance evidence is authoritative;
4. the candidate passes independent geometry checks;
5. source identity/lineage is recorded.

`APPLY` must fail closed without that authorization. The source PcbDoc is never overwritten.

## 6. Verification and retry
Every mutation produces a receipt containing source/output identity and applied/rejected operations. Verification reparses the mutated copy. Retry operates only on the verified working copy and preserves attempt history. No retry may convert `UNKNOWN` or `TOPOLOGY_UNRESOLVED` directly into authorization.

## 7. Terminal result
The reusable kit always emits `summary.json` with `terminal_status` in:
`PASS | FAIL | BLOCKED | INCONCLUSIVE | UNKNOWN`.

The terminal artifact must include the input identity, planning evidence, gate results, and repair/attempt lineage when mutation was requested.

## 8. Reuse gate
Clean-room reuse is proven only when a different input directory can be supplied with renamed/different project files and the same engine reaches a terminal result without engine edits. A passing clean-room run proves execution independence; it does not imply the design itself is correct.

## 9. Evidence limits
Two files can verify parser-exposed geometry, connectivity and routing facts. They do not by themselves prove complete Altium DRC equivalence, full 3D mechanical collision, SI/timing, or undocumented project intent.

## 10. Strict industrial placement/routing gate

The kit uses an explicit industrial-rule authority layer before placement lock or routing closure. The baseline references are IPC-2221C/IPC-2222 for board design, IPC-7352 for land-pattern/mounting guidance, IPC-2152 for current-carrying capacity, IPC-6012F for rigid-board fabrication performance, and IPC-A-610J/J-STD-001J for assembly acceptability. These are references, not invented numeric defaults. IPC identifies IPC-7352 as the current land-pattern guideline and notes that company/board-technology adjustments may be required.

The project/fabricator/assembly authority must provide each applicable placement/routing rule as either:
- APPLICABLE with an authoritative value/values and evidence; or
- NOT_APPLICABLE with explicit evidence.

Required placement rule domains:
- component clearance
- board-edge clearance
- courtyard
- keepout
- assembly access

Required routing rule domains:
- trace width
- trace clearance
- via rules
- layer stack
- current capacity

Missing or invalid authority is BLOCKED; the engine must not invent a number from a generic IPC reference.

Placement LOCK additionally requires authoritative component position, board bounds, and zero parsed component-envelope overlap.

Routing VERIFIED requires the industrial-rule authority gate plus closed parsed topology. Full DRC, SI/timing, impedance, return-path and other design-specific requirements remain separate gates unless their authoritative evidence and enforcement are implemented.

A parser-success or geometrically connected board is therefore never sufficient for an industrial PASS.

## 11. Placement execution profiles

Placement has two explicit profiles over the same engine:

### GENERIC
- Project/fabricator authority supplies the fixed-anchor registry.
- The engine discovers the rest of the components from the PcbDoc and classifies them only when the authority permits.
- Missing fixed-anchor/mechanical/assembly authority is BLOCKED.
- No project reference designators are embedded in the engine.

### WORKLOAD-SPECIFIC
- A workload authority packet supplies the fixed-anchor registry and any functional zones.
- Anchor position, orientation, layer and mechanical envelope are immutable only where the packet declares them fixed.
- All other parser-confirmed components are optimizable under the authority packet unless another mechanical anchor is declared.
- Functional zones are derived from authority plus compiled connectivity; the optimizer moves FREE components toward the fixed frame, never the reverse.

The workload-specific profile is an authority packet, not a project-specific algorithm. The same placement engine and sufficiency gate are used by both profiles.

## 12. Input sufficiency gate

Sufficiency is operation-specific. The engine must emit a machine-readable decision before placement planning:
- VERIFIED: authoritative evidence exists;
- MISSING: required input is absent;
- UNKNOWN: input exists but cannot establish the required fact;
- NOT_APPLICABLE: explicitly evidenced as not applicable;
- BLOCKED: a required authority is missing or invalid.

Minimum placement authority covers board outline, component geometry/position, connectivity, fixed-anchor registry, mechanical envelopes/courtyard, keepouts and assembly access. Missing required authority blocks placement optimization; it is never replaced by a guessed default.
