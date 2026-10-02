#!/usr/bin/env python3
"""Generic schematic semantic/identity audit.

This layer deliberately sits above parser/compile/connectivity.  It checks
whether the compiled schematic has enough trustworthy component/pin/net
semantics to authorize downstream PCB work.  It never invents design intent.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any


KNOWN_PIN_TYPES = {
    "INPUT", "OUTPUT", "BIDIRECTIONAL", "PASSIVE", "POWER",
    "OPENCOLLECTOR", "OPEN_COLLECTOR", "OPENDRAIN", "OPEN_DRAIN",
    "TRISTATE", "TRI_STATE", "HI_Z", "OPENEMITTER", "OPEN_EMITTER",
    "UNSPECIFIED", "NO_CONNECT", "IO", "I/O", "I_O", "I/O/T", "I_O_T",
    "P", "NC",
}


def _add(findings, fid, severity, domain, status, evidence, confidence="VERIFIED", obj=None):
    findings.append({
        "id": fid,
        "severity": severity,
        "domain": domain,
        "status": status,
        "object": obj,
        "evidence": evidence,
        "confidence": confidence,
    })


def _text(v):
    return str(v).strip() if v is not None else ""


def _component_map(rows):
    out = {}
    for row in rows or []:
        ref = _text(row.get("designator"))
        if ref:
            out.setdefault(ref, []).append(row)
    return out


def audit(design: dict[str, Any], netlist: dict[str, Any],
          functional_intent: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    components = list((design or {}).get("components", []) or [])
    nl_components = list((netlist or {}).get("components", []) or [])
    nets = list((netlist or {}).get("nets", []) or [])

    # Component identity is the first semantic boundary. A parser can load a
    # symbol while still leaving BOM/physical identity incomplete.
    cmap = _component_map(components)
    for ref, rows in sorted(cmap.items()):
        if len(rows) > 1:
            _add(findings, f"SCH-COMP-DUPLICATE-{ref}", "BLOCKER", "component_identity",
                 "FAIL", f"Design JSON contains {len(rows)} component records for {ref!r}.",
                 "VERIFIED", ref)

    required_fields = ("footprint", "library_ref")
    for row in components:
        ref = _text(row.get("designator")) or "<MISSING>"
        if ref == "<MISSING>":
            _add(findings, "SCH-COMP-MISSING-DESIGNATOR", "BLOCKER", "component_identity",
                 "FAIL", "A schematic component has no authoritative designator.", "VERIFIED", ref)
        params = row.get("parameters") or {}
        effective_value = _text(params.get("Value")) or _text(row.get("value")) or _text(params.get("Comment"))
        if not effective_value:
            _add(findings, f"SCH-COMP-MISSING-VALUE-{ref}", "BLOCKER", "component_identity",
                 "BLOCKED", f"{ref} has no authoritative component value/MPN identity.", "FACT", ref)
        for key in required_fields:
            if not _text(row.get(key)):
                _add(findings, f"SCH-COMP-MISSING-{key.upper()}-{ref}", "BLOCKER",
                     "component_identity", "BLOCKED",
                     f"{ref} has no authoritative {key}; component identity is incomplete.",
                     "FACT", ref)
        # Detect semantic identity drift between the displayed part identity and
        # concrete BOM/MPN metadata. Generic library aliases such as Res1/Cap2
        # are intentionally ignored; concrete disagreements are not.
        display = _text(row.get("value"))
        concrete = []
        for key in ("Value", "MPN", "Manufacturer_Part_Number", "Manufacturer Part Number",
                    "ManufacturerPartNumber", "PartNumber"):
            value = _text(params.get(key))
            if value and value not in concrete:
                concrete.append(value)
        generic_display = display.upper() in {"RES1", "CAP", "CAP2", "INDUCTOR", "CONNECTOR 10", "*", "?"}
        if display and not generic_display:
            for value in concrete:
                if value and value.lower() != display.lower():
                    _add(findings, f"SCH-COMPONENT-IDENTITY-DRIFT-{ref}", "HIGH",
                         "component_identity", "BLOCKED",
                         f"{ref}: displayed value={display!r} conflicts with concrete parameter identity={value!r}.",
                         "FACT", ref)
                    break
        if display in {"*", "?"}:
            _add(findings, f"SCH-COMPONENT-PLACEHOLDER-VALUE-{ref}", "MEDIUM",
                 "component_identity", "BLOCKED",
                 f"{ref} uses placeholder value {display!r}; physical part identity is unresolved.",
                 "FACT", ref)
        if row.get("ambiguous_physical_designator"):
            _add(findings, f"SCH-COMP-AMBIGUOUS-{ref}", "BLOCKER", "component_identity",
                 "BLOCKED", "Compiled component identity is explicitly ambiguous for this occurrence.",
                 "FACT", ref)
        classification = row.get("classification") or {}
        if not _text(classification.get("type")) or not _text(classification.get("prefix")):
            _add(findings, f"SCH-COMP-CLASSIFICATION-{ref}", "HIGH", "component_identity",
                 "BLOCKED", "Component classification is missing; pin/function semantics cannot be safely interpreted.",
                 "FACT", ref)

    nlmap = _component_map(nl_components)
    for ref, rows in sorted(nlmap.items()):
        if len(rows) > 1:
            _add(findings, f"SCH-NL-DUPLICATE-COMPONENT-{ref}", "BLOCKER", "component_identity",
                 "FAIL", f"Compiled netlist contains {len(rows)} component summaries for {ref!r}.",
                 "VERIFIED", ref)

    design_refs = set(cmap)
    netlist_refs = set(nlmap)
    for ref in sorted(design_refs - netlist_refs):
        _add(findings, f"SCH-DESIGN-ONLY-{ref}", "BLOCKER", "component_identity", "BLOCKED",
             "Design component has no compiled-netlist component identity.", "FACT", ref)
    for ref in sorted(netlist_refs - design_refs):
        _add(findings, f"SCH-NETLIST-ONLY-{ref}", "BLOCKER", "component_identity", "BLOCKED",
             "Compiled-netlist component has no design component identity.", "FACT", ref)

    # Cross-check the stable semantic fields that should survive into the
    # compiled netlist. Differences are real semantic drift, not formatting.
    for ref in sorted(design_refs & netlist_refs):
        d, n = cmap[ref][0], nlmap[ref][0]
        for key in ("value", "footprint", "library_ref"):
            dv, nv = _text(d.get(key)), _text(n.get(key))
            if dv and nv and dv != nv:
                _add(findings, f"SCH-COMPONENT-{key.upper()}-DRIFT-{ref}", "HIGH",
                     "component_identity", "FAIL",
                     f"{ref}: design={dv!r}, compiled_netlist={nv!r}.", "VERIFIED", ref)

    # Library reference is another identity authority. A concrete displayed
    # part name must not silently disagree with a concrete library symbol.
    generic_library_tokens = {"RES1", "CAP", "CAP2", "INDUCTOR", "HEADER 2", "HEADER 3", "HEADER 13", "CON10"}
    for row in components:
        ref = _text(row.get("designator"))
        display = _text(row.get("value"))
        lib = _text(row.get("library_ref"))
        if not ref or not display or not lib:
            continue
        if display.upper() in {"*", "?", *generic_library_tokens}:
            continue
        # Normalize package suffixes only for a conservative same-family test.
        dnorm = "".join(ch for ch in display.upper() if ch.isalnum())
        lnorm = "".join(ch for ch in lib.upper() if ch.isalnum())
        if dnorm and lnorm and dnorm not in lnorm and lnorm not in dnorm:
            _add(findings, f"SCH-COMPONENT-LIBRARY-DRIFT-{ref}", "HIGH",
                 "component_identity", "BLOCKED",
                 f"{ref}: displayed part={display!r} conflicts with library_ref={lib!r}.",
                 "FACT", ref)

    # Optional authoritative part/pin contracts are generated from datasheets or
    # other identified manufacturer evidence. They are not inferred from names.
    contracts = (functional_intent or {}).get("components", {}) if functional_intent else {}
    for ref, contract in sorted(contracts.items()):
        rows = cmap.get(ref, [])
        if not rows:
            _add(findings, f"SCH-CONTRACT-MISSING-COMP-{ref}", "BLOCKER", "functional",
                 "BLOCKED", "Functional contract names a component absent from the compiled schematic.",
                 "FACT", ref)
            continue
        row = rows[0]
        expected_parts = [str(x).strip().lower() for x in contract.get("part_numbers", []) if str(x).strip()]
        params = row.get("parameters") or {}
        actual_ids = {_text(row.get("value")).lower(), _text(params.get("Value")).lower(),
                      _text(params.get("MPN")).lower(), _text(params.get("Manufacturer_Part_Number")).lower(),
                      _text(params.get("Manufacturer Part Number")).lower(), _text(params.get("PartNumber")).lower()}
        actual_ids.discard("")
        if expected_parts and not any(p in actual_ids for p in expected_parts):
            _add(findings, f"SCH-CONTRACT-PART-MISMATCH-{ref}", "BLOCKER", "functional",
                 "FAIL",
                 f"{ref}: contract expects one of {expected_parts!r}; compiled identity fields are {sorted(actual_ids)!r}.",
                 "VERIFIED", ref)
        expected_pin_count = contract.get("pin_count")
        actual_pin_count = (row.get("classification") or {}).get("pin_count")
        if expected_pin_count is not None and actual_pin_count is not None and int(actual_pin_count) != int(expected_pin_count):
            _add(findings, f"SCH-CONTRACT-PINCOUNT-{ref}", "BLOCKER", "functional",
                 "FAIL",
                 f"{ref}: contract pin_count={expected_pin_count}, schematic symbol pin_count={actual_pin_count}.",
                 "VERIFIED", ref)
        pin_contract = {str(k): str(v) for k, v in (contract.get("pins") or {}).items()}
        if pin_contract:
            for net in nets:
                for term in net.get("terminals", []) or []:
                    if _text(term.get("designator")) != ref:
                        continue
                    pin = _text(term.get("pin"))
                    expected_name = pin_contract.get(pin)
                    if expected_name is None:
                        continue
                    actual_name = _text(term.get("pin_name"))
                    if actual_name and actual_name != expected_name:
                        _add(findings, f"SCH-CONTRACT-PINNAME-{ref}-{pin}", "BLOCKER", "functional",
                             "FAIL",
                             f"{ref}.{pin}: contract={expected_name!r}, schematic={actual_name!r}.",
                             "VERIFIED", f"{ref}.{pin}")

    # Terminal identity must be one-to-one. A pin appearing on two nets is a
    # concrete semantic contradiction even when every individual net is legal.
    pin_nets: dict[tuple[str, str], list[str]] = defaultdict(list)
    unknown_pin_types = []
    missing_pin_names = []
    missing_pin_types = []
    missing_refs = []

    for net in nets:
        net_name = _text(net.get("name")) or _text(net.get("uid")) or "<UNNAMED>"
        terminals = list(net.get("terminals", []) or [])
        if not terminals:
            _add(findings, f"SCH-NET-NO-TERMINALS-{net_name}", "BLOCKER", "net_semantics",
                 "BLOCKED", f"Compiled net {net_name!r} has no terminals.", "FACT", net_name)
        for term in terminals:
            ref = _text(term.get("designator") or term.get("refdes") or term.get("reference"))
            pin = _text(term.get("pin") or term.get("pin_designator") or term.get("number"))
            pin_name = _text(term.get("pin_name"))
            pin_type = _text(term.get("pin_type")).upper().replace("-", "_")
            if not ref:
                missing_refs.append((net_name, pin))
                continue
            if ref not in design_refs:
                _add(findings, f"SCH-TERM-UNKNOWN-COMP-{ref}-{pin}-{net_name}", "BLOCKER",
                     "pin_semantics", "FAIL",
                     f"Terminal {ref}.{pin or '?'} on {net_name!r} references no compiled component.",
                     "VERIFIED", f"{ref}.{pin}")
            if not pin:
                _add(findings, f"SCH-TERM-MISSING-PIN-{ref}-{net_name}", "BLOCKER",
                     "pin_semantics", "BLOCKED",
                     f"Terminal on {net_name!r} has no authoritative pin number.", "FACT", ref)
            if not pin_name:
                missing_pin_names.append((ref, pin, net_name))
            if not pin_type:
                missing_pin_types.append((ref, pin, net_name))
            elif pin_type not in KNOWN_PIN_TYPES:
                unknown_pin_types.append((ref, pin, pin_type, net_name))
            if ref and pin:
                pin_nets[(ref, pin)].append(net_name)

    for ref, pin in sorted(pin_nets):
        names = sorted(set(pin_nets[(ref, pin)]))
        if len(names) > 1:
            _add(findings, f"SCH-PIN-MULTI-NET-{ref}-{pin}", "BLOCKER", "pin_semantics",
                 "FAIL", f"{ref}.{pin} appears on multiple compiled nets: {names!r}.",
                 "VERIFIED", f"{ref}.{pin}")

    for ref, pin, net_name in missing_pin_names:
        _add(findings, f"SCH-PIN-MISSING-NAME-{ref}-{pin}-{net_name}", "HIGH", "pin_semantics",
             "BLOCKED", f"{ref}.{pin} has no compiled pin_name; pin function cannot be identified.",
             "FACT", f"{ref}.{pin}")
    for ref, pin, net_name in missing_pin_types:
        _add(findings, f"SCH-PIN-MISSING-TYPE-{ref}-{pin}-{net_name}", "HIGH", "pin_semantics",
             "BLOCKED", f"{ref}.{pin} has no compiled pin_type; electrical direction cannot be established.",
             "FACT", f"{ref}.{pin}")
    for ref, pin, pin_type, net_name in unknown_pin_types:
        _add(findings, f"SCH-PIN-UNKNOWN-TYPE-{ref}-{pin}", "HIGH", "pin_semantics",
             "BLOCKED", f"{ref}.{pin} has unsupported pin_type={pin_type!r} on {net_name!r}.",
             "FACT", f"{ref}.{pin}")

    # Electrical contradictions. These are authoritative only when pin
    # semantics are authoritative; no source/sink capability is invented for
    # PASSIVE or POWER pins.
    output_conflicts = []
    for net in nets:
        name = _text(net.get("name")) or _text(net.get("uid")) or "<UNNAMED>"
        terms = list(net.get("terminals", []) or [])
        outputs = [t for t in terms if _text(t.get("pin_type")).upper() in {"OUTPUT", "OPENCOLLECTOR", "OPEN_COLLECTOR", "OPENDRAIN", "OPEN_DRAIN"}]
        if len(outputs) > 1:
            output_conflicts.append((name, outputs))
    for name, outputs in output_conflicts:
        ids = ", ".join(f"{_text(t.get('designator'))}.{_text(t.get('pin'))}" for t in outputs)
        _add(findings, f"SCH-NET-MULTI-DRIVER-{name}", "BLOCKER", "electrical", "FAIL",
             f"Net {name!r} contains multiple driver-class pins: {ids}.", "VERIFIED", name)

    # Single-terminal nets are suspicious by construction. They can be valid
    # testpoints/NCs, so the generic engine blocks authority until explicit
    # intent (NC/testpoint/waiver) exists rather than guessing.
    for net in nets:
        name = _text(net.get("name")) or _text(net.get("uid")) or "<UNNAMED>"
        terms = list(net.get("terminals", []) or [])
        if len(terms) == 1:
            _add(findings, f"SCH-NET-SINGLE-TERMINAL-{name}", "HIGH", "net_semantics",
                 "BLOCKED", f"Net {name!r} has one compiled terminal; intentional NC/testpoint intent is not established.",
                 "FACT", name)

    # Functional correctness is not derivable from connectivity. Require an
    # explicit authority packet when the project asks for a functional gate.
    # This is deliberately strict: absence of intent is not a PASS.
    if functional_intent is None:
        _add(findings, "SCH-FUNCTIONAL-INTENT-MISSING", "BLOCKER", "functional",
             "BLOCKED",
             "No authoritative functional-intent packet was supplied. Connectivity alone cannot prove that a component, pin, net, or topology performs the intended function.",
             "FACT")
    else:
        coverage = _text(functional_intent.get("coverage")).lower()
        if coverage != "full_schematic":
            _add(findings, "SCH-FUNCTIONAL-COVERAGE-INCOMPLETE", "BLOCKER", "functional", "BLOCKED",
                 f"Functional authority coverage={coverage or 'unspecified'}; full_schematic coverage is required for authority PASS.",
                 "FACT")
        else:
            _add(findings, "SCH-FUNCTIONAL-INTENT", "INFO", "functional", "VERIFIED",
                 "Functional-intent packet declares full-schematic coverage.", "VERIFIED")

    if not findings:
        _add(findings, "SCH-SEMANTIC-SWEEP", "INFO", "schematic", "VERIFIED",
             "Generic component/pin/net semantic sweep produced no contradictions.", "VERIFIED")

    return findings
