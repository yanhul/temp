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