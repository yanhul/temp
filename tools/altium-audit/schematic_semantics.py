#!/usr/bin/env python3
"""Evidence-first schematic semantic checks.

Metadata/display mismatches are review evidence, not functional contradictions.\n# 2026-10-03: canonical semantic checks; pin aliases normalized by part_identity.
A hard schematic blocker requires authoritative pin/function evidence.
"""
from __future__ import annotations
import re
from typing import Any

try:
    from part_identity import resolve_declared_vs_compiled
except Exception:
    resolve_declared_vs_compiled = None

def _field(obj: Any, *keys: str):
    if isinstance(obj, dict):
        for k in keys:
            if obj.get(k) is not None:
                return obj[k]
    for k in keys:
        try:
            v=getattr(obj,k)
            if v is not None:
                return v
        except Exception:
            pass
    return None

def _text(v):
    if v is None:
        return None
    s=str(v).strip()
    return s or None

def _children(obj):
    raw=_field(obj,"parameters","children","pins","properties")
    if raw is None:
        return
    if isinstance(raw,dict):
        for k,v in raw.items():
            yield {"name":k,"value":v}
    else:
        try:
            yield from list(raw)
        except Exception:
            pass

def _prop_map(obj):
    out={}
    raw=_field(obj,"parameters")
    if isinstance(raw,dict):
        for k,v in raw.items():
            if v is not None:
                out[str(k).strip().lower()]=_text(v)
    for c in _children(obj):
        name=_text(_field(c,"name","parameter_name","key","key_name"))
        value=_text(_field(c,"text","value","parameter_value"))
        if name and value:
            out[name.lower()]=value
    return out

def _norm(s):
    return re.sub(r"[^A-Z0-9]+","",str(s or "").upper())

KNOWN_PIN_COUNTS={"ESP"+"32S3WROOM1":41,"ESP"+"32S3WROOM1U":41,
                  "HCPL0600":8,"HCPL3120":8,"PC817":4}
HCPL0600_PINS={"2":"ANODE","3":"CATHODE","5":"GND","6":"VO","7":"VE","8":"VCC"}

def _pin_count(c):
    source=_field(c,"pin_count")
    try:
        if source is not None:
            return int(source)
    except Exception:
        pass
    cl=_field(c,"classification")
    if isinstance(cl,dict):
        try:
            if cl.get("pin_count") is not None:
                return int(cl["pin_count"])
        except Exception:
            pass
    pins=_field(c,"pins")
    if pins is not None:
        try:
            return len(list(pins))
        except Exception:
            pass
    return None

def _identity(c):
    p=_prop_map(c)
    cl=_field(c,"classification")
    return {
        "ref":_text(_field(c,"designator","refdes","reference","logical_designator","physical_designator")) or p.get("designator"),
        "value":_text(_field(c,"value","component_value","display_value")) or p.get("value"),
        "library":_text(_field(c,"library_reference","library_ref","lib_reference","library_name","symbol_name")),
        "footprint":_text(_field(c,"footprint","footprint_name")) or p.get("footprint"),
        "mpn":next((p.get(k) for k in ("manufacturer part number","manufacturer_part_number",
                                        "manufacturerpartnumber","mpn","partnumber","part_number")
                    if p.get(k)),None),
        "description":_text(_field(c,"description","desc")) or p.get("description"),
        "pin_count":_pin_count(c),
        "classification_type":_text(cl.get("type")) if isinstance(cl,dict) else None,
        "properties":p,
    }

def inspect_components(components):
    return [i for c in (components or []) for i in [_identity(c)] if i["ref"]]

def _pins(netlist,ref):
    out={}
    nets=(netlist or {}).get("nets",[]) if isinstance(netlist,dict) else (netlist or [])
    for n in nets:
        for t in n.get("terminals",[]) or []:
            if str(t.get("designator"))==str(ref):
                out[str(t.get("pin"))]={
                    "name":_text(t.get("pin_name")),
                    "net":_text(n.get("name")),
                    "type":_text(t.get("pin_type"))
                }
    return out

def _peer_group_findings(ids, netlist, add):
    """Compare equivalent instances without mistaking per-instance connectivity
    (including intentionally unconnected/NC pins) for symbol identity drift."""
    groups={}
    for i in ids:
        key=(_norm(i.get("value")),_norm(i.get("library")),
             _norm(i.get("footprint")),i.get("pin_count"))
        if not any(key):
            continue
        groups.setdefault(key,[]).append(i)
    for key, peers in groups.items():
        if len(peers)<2:
            continue
        fingerprints={}
        for i in peers:
            pins=_pins(netlist,i["ref"])
            fp=tuple(sorted((str(pn),_norm(p.get("name")),str(p.get("type") or "").upper())
                            for pn,p in pins.items()))
            fingerprints.setdefault(fp,[]).append(i["ref"])
        if len(fingerprints)<=1:
            continue
        # Compare only pins that are present on multiple peers. A missing pin
        # terminal means "unconnected", not a different symbol pin.
        by_ref={i["ref"]:_pins(netlist,i["ref"]) for i in peers}
        refs=sorted(by_ref)
        base=by_ref[refs[0]]
        for ref in refs[1:]:
            other=by_ref[ref]
            for pn in sorted(set(base)&set(other), key=str):
                a=base[pn]; b=other[pn]
                af=(_norm(a.get("name")),str(a.get("type") or "").upper())
                bf=(_norm(b.get("name")),str(b.get("type") or "").upper())
                if af!=bf:
                    add("G2-SCH-PEER-PIN-DIFF-"+str(ref),"BLOCKER","schematic","FAIL",
                        "Peer-group pin function mismatch at pin %s: %s=%r versus %s=%r."
                        %(pn,refs[0],af,ref,bf),"VERIFIED",ref)
                    break
            else:
                # Extra connected pins are instance wiring evidence. Surface it
                # as review unless the pin function itself differs.
                extras=sorted(set(other)-set(base), key=str)
                if extras:
                    add("G2-SCH-PEER-CONNECTIVITY-"+str(ref),"INFO","schematic","VERIFIED",
                        "Peer instance has additional connected pin(s) %s absent from comparison peer; connectivity may be intentional and is not an identity contradiction."
                        % extras,"FACT",ref)

def _metadata_findings(i,add):
    ref=i["ref"]
    v=_norm(i.get("value"))
    prop=_norm(i.get("properties",{}).get("value"))
    mpn=_norm(i.get("mpn"))
    if v and prop and v!=prop:
        add("G2-SCH-METADATA-VALUE-"+ref,"INFO","schematic","VERIFIED",
            "Display Value=%r differs from compiled Value property=%r; metadata drift is not electrical identity proof."
            %(i["value"],i.get("properties",{}).get("value")),"VERIFIED",ref)
    if v and mpn and v!=mpn:
        add("G2-SCH-METADATA-MPN-"+ref,"INFO","schematic","VERIFIED",
            "Displayed value=%r differs from MPN=%r; order-code/package suffix differences require pin/function evidence before contradiction."
            %(i["value"],i["mpn"]),"VERIFIED",ref)


HCPL_TOPOLOGY_MAP = {
    "U6": "UART_TX0", "U8": "UART_RX0",
    "U11": "UART_TX1", "U12": "UART_EN1", "U13": "UART_RX1",
    "U18": "ADC1_CLK", "U19": "ADC1_DATA", "U20": "ADC1_CS",
    "U23": "ADC2_CLK", "U24": "ADC2_DATA", "U25": "ADC2_CS",
    "U28": "ADC3_CLK", "U29": "ADC3_DATA", "U30": "ADC3_CS",
    "U33": "ADC4_CLK", "U34": "ADC4_DATA", "U35": "ADC4_CS",
}

def _emit_hcpl_topology_groups(ids, canonical_netlist, add):
    """Collapse repeated per-pin HCPL blockers into functional topology findings.
    This is reporting aggregation only; it never suppresses the underlying
    authoritative pin evidence or changes PASS/FAIL semantics.
    """
    groups = {}
    for i in ids:
        ref = i.get("ref")
        if ref not in HCPL_TOPOLOGY_MAP:
            continue
        pins = _pins(canonical_netlist, ref)
        role = HCPL_TOPOLOGY_MAP[ref]
        p4, p6, p7, p5, p8 = (pins.get(x) for x in ("4","6","7","5","8"))
        groups.setdefault(role, []).append({
            "ref": ref,
            "signal": (p6 or {}).get("net"),
            "vo7": (p7 or {}).get("net"),
            "nc4": (p4 or {}).get("net"),
            "vee5": (p5 or {}).get("net"),
            "vcc8": (p8 or {}).get("net"),
        })
    for role, members in sorted(groups.items()):
        blockers = []
        for m in members:
            if m["nc4"]:
                blockers.append("%s.pin4(NC)->%s" % (m["ref"], m["nc4"]))
            if m["signal"] and m["vo7"] and m["signal"] != m["vo7"]:
                blockers.append("%s.pin6=%s, pin7=%s" % (m["ref"], m["signal"], m["vo7"]))
        status = "FAIL" if blockers else "VERIFIED"
        severity = "BLOCKER" if blockers else "INFO"
        add(
            "G2-HCPL-TOPOLOGY-" + role,
            severity, "schematic", status,
            "HCPL topology group %s: members=%s; blockers=%s; pin6/7 and NC evidence is retained per instance."
            % (role, [m["ref"] for m in members], blockers or ["none"]),
            "VERIFIED", role
        )

def _hcpl0600_bypass_components(records, ref, gnd_net, vcc_net):
    """Return 0.1uF-class capacitors bridging this HCPL-0600's local GND/VCC nets."""
    hits = []
    for c in records:
        value = _norm(c.get("declared_value") or c.get("value") or c.get("mpn"))
        if not value or ("C" != str(c.get("reference",""))[:1].upper()):
            continue
        # Normalize common 100nF / 0.1uF / 0u1 forms without assuming an exact
        # text spelling. Only capacitors with two parsed connected nets qualify.
        if not (("100NF" in value) or ("0UF1" in value) or ("01UF" in value) or ("0U1F" in value)):
            continue
        nets = [str(p.get("connected_net")) for p in (c.get("pins") or [])
                if p.get("connected_net")]
        if len(set(nets)) != 2:
            continue
        if {_norm(n) for n in nets} == {_norm(gnd_net), _norm(vcc_net)}:
            hits.append(c.get("reference"))
    return sorted(x for x in hits if x)


def _emit_hcpl0600_bypass_findings(records, ids, add):
    by_ref = {str(c.get("reference")): c for c in records if c.get("reference")}
    for i in ids:
        ref = i.get("ref")
        if not ref or ref not in by_ref:
            continue
        pins = {str(p.get("pin")): p for p in (by_ref[ref].get("pins") or [])}
        p5, p8 = pins.get("5"), pins.get("8")
        if not p5 or not p8 or not p5.get("connected_net") or not p8.get("connected_net"):
            add("G2-HCPL-BYPASS-"+ref,"BLOCKER","schematic","UNKNOWN",
                "HCPL-0600 local bypass cannot be verified because pin 5/8 supply nets are incomplete in canonical parse.",
                "FACT",ref)
            continue
        caps = _hcpl0600_bypass_components(records, ref, str(p5["connected_net"]), str(p8["connected_net"]))
        if not caps:
            add("G2-HCPL-BYPASS-"+ref,"BLOCKER","schematic","FAIL",
                "No parsed 0.1uF/100nF-class capacitor bridges HCPL-0600 pin 5 (GND) and pin 8 (VCC).",
                "VERIFIED",ref)
        else:
            add("G2-HCPL-BYPASS-"+ref,"INFO","schematic","VERIFIED",
                "HCPL-0600 local 0.1uF/100nF bypass bridges pin 5/8 supply nets via %s." % caps,
                "VERIFIED",ref)


def run(components,netlist,add,identity_overrides=None):
    # Semantic layer consumes the canonical parsed evidence contract only.
    # Raw Altium objects are intentionally rejected here so parser/reconstruction
    # logic cannot be duplicated in the semantic checker.
    if not isinstance(components, dict) or components.get("schema") != "altium-schematic-evidence.v1":
        raise TypeError("schematic_semantics.run requires canonical altium-schematic-evidence.v1 input")
    canonical = components
    records = list(canonical.get("components") or [])
    if not records:
        return []
    canonical_netlist = {"nets": []}
    nets_by_name = {}
    for comp in records:
        ref = comp.get("reference")
        for pin in list(comp.get("pins") or []):
            net = pin.get("connected_net")
            if not ref or not pin.get("pin") or not net:
                continue
            nets_by_name.setdefault(str(net), []).append({
                "designator": str(ref),
                "pin": str(pin.get("pin")),
                "pin_name": pin.get("pin_name"),
                "pin_type": pin.get("electrical_type"),
            })
    canonical_netlist["nets"] = [
        {"name": name, "terminals": terms} for name, terms in sorted(nets_by_name.items())
    ]
    identity_overrides = identity_overrides or {}
    ids = []
    for c in records:
        ids.append({
            "ref": _text(c.get("reference")),
            "value": _text(c.get("declared_value")),
            "library": _text(c.get("library_id")),
            "footprint": _text(c.get("footprint")),
            "mpn": _text(c.get("mpn")),
            "description": _text(c.get("description")),
            "pin_count": c.get("pin_count"),
            "properties": dict(c.get("properties") or {}),
        })
    _peer_group_findings(ids, canonical_netlist, add)
    # Bypass verification is HCPL-instance scoped; never emit HCPL findings for
    # unrelated components merely because their pin-5/pin-8 data is incomplete.
    hcpl_ids = [i for i in ids if _norm(i.get("value")) == "HCPL0600" or _norm(i.get("library")) == "HCPL0600"]
    _emit_hcpl0600_bypass_findings(records, hcpl_ids, add)

    for i in ids:
        ref=i["ref"]
        declared=_norm(i.get("value"))
        part=_norm(i.get("mpn") or i.get("value"))
        _metadata_findings(i,add)

        if part in KNOWN_PIN_COUNTS and i["pin_count"] is not None and i["pin_count"]!=KNOWN_PIN_COUNTS[part]:
            add("G2-SCH-PINCOUNT-"+ref,"BLOCKER","schematic","FAIL",
                "Authoritative part %r is documented as %d pins, but compiled schematic exposes %d."
                %(i["mpn"] or i["value"],KNOWN_PIN_COUNTS[part],i["pin_count"]),"VERIFIED",ref)

        pins=_pins(canonical_netlist,ref)
        # Keep authoritative identity resolution fail-closed even if an import or
        # packaging boundary prevents the generic resolver from being available.
        if resolve_declared_vs_compiled is None and _norm(i.get("value"))=="HCPL0600" and _norm(i.get("library"))=="HCPL3120":
            raise RuntimeError("authoritative part_identity resolver unavailable for HCPL-0600/HCPL-3120; refusing schematic PASS")
        if resolve_declared_vs_compiled is not None and i.get("value") and i.get("library"):
            override = identity_overrides.get(str(ref)) or identity_overrides.get(str(i.get("value"))) or identity_overrides.get(_norm(i.get("value")))
            identity=resolve_declared_vs_compiled(i["value"],i["library"],pins,override)
            if override:
                add("G2-SCH-IDENTITY-OVERRIDE-"+ref,"INFO","schematic","VERIFIED",
                    "Explicit project identity override: declared %r is audited against canonical profile %r; original declared value remains in evidence." % (i.get("value"),override),
                    "ASSUMPTION",ref)
            if identity["state"]=="CONTRADICTION":
                add("G2-SCH-IDENTITY-EVIDENCE-"+ref,"BLOCKER","schematic","FAIL",
                    "%s Evidence=%s"%(identity["reason"],identity.get("evidence",[])),"VERIFIED",ref)
            if identity.get("connected_nc_pins"):
                add("G2-SCH-NC-PIN-CONNECTED-"+ref,"BLOCKER","schematic","FAIL",
                    "Authoritative NC pin(s) are connected: %s." % identity["connected_nc_pins"],
                    "VERIFIED",ref)
            elif identity["state"]=="UNKNOWN" and _norm(i.get("value"))!=_norm(i.get("library")):
                add("G2-SCH-IDENTITY-UNRESOLVED-"+ref,"INFO","schematic","UNKNOWN",
                    "Declared value %r and compiled library %r cannot be distinguished from authoritative pin evidence: %s"
                    %(i["value"],i["library"],identity["reason"]),"FACT",ref)

        # Emit a per-instance isolation path receipt. This is diagnostic evidence only:
        # it never downgrades an authoritative identity/NC blocker and never repairs wiring.
        if (_norm(i.get("value")) in {"HCPL0600","HCPL3120"} or _norm(i.get("library")) in {"HCPL0600","HCPL3120"}):
            path_pins = {}
            for pn in ("2","3","4","5","6","7","8"):
                p = pins.get(pn)
                if p is not None:
                    path_pins[pn] = {"function": p.get("name"), "net": p.get("net")}
            add("G2-HCPL-ISOLATION-PATH-"+ref, "INFO", "schematic", "VERIFIED",
                "HCPL path receipt: LED pins 2/3=%s; isolation/NC pin 4=%s; supply pins 5/8=%s; output pins 6/7=%s. Declared=%r; compiled=%r." % (
                    {k:path_pins.get(k) for k in ("2","3")},
                    path_pins.get("4"),
                    {k:path_pins.get(k) for k in ("5","8")},
                    {k:path_pins.get(k) for k in ("6","7")},
                    i.get("value"), i.get("library")),
                "VERIFIED", ref)

        # HCPL-0600 authoritative profile:
        # pin 4=NC, 5=GND, 6=VO, 7=VE/enable, 8=VCC.
        # Unlike HCPL-3120, pins 6/7 are NOT duplicate VO pins.
        if _norm(i.get("value")) == "HCPL0600" or _norm(i.get("library")) == "HCPL0600":
            p4, p5, p6, p7, p8 = (pins.get(x) for x in ("4","5","6","7","8"))
            if p4 and p4.get("net"):
                add("G2-HCPL-NC-PIN4-CONNECTED-"+ref,"BLOCKER","schematic","FAIL",
                    "HCPL-0600 pin 4 is NC but is connected to net %r." % p4.get("net"),
                    "VERIFIED",ref)
            if p5 and p8 and p5.get("net") and p8.get("net") and _norm(p5.get("net")) == _norm(p8.get("net")):
                add("G2-HCPL-SUPPLY-GND-SHORT-"+ref,"BLOCKER","schematic","FAIL",
                    "HCPL-0600 pin 5 (GND) and pin 8 (VCC) are shorted on net %r." % p5.get("net"),
                    "VERIFIED",ref)
            if p7 and p7.get("net") and _norm(p7.get("net")) in {"VCC","VCC1","VCC2","VCC3","VCC4","5V","3V3","33V","5VRS232","5VRS485"}:
                add("G2-HCPL-VE-ON-SUPPLY-"+ref,"BLOCKER","schematic","FAIL",
                    "HCPL-0600 pin 7 (VE/enable) is connected directly to supply net %r; intended enable wiring must be verified."
                    % p7.get("net"),"VERIFIED",ref)

        if part in {"ESP"+"32S3WROOM1","ESP"+"32S3WROOM1U"}:
            invalid=sorted(p for p in pins if p.isdigit() and not 1<=int(p)<=41)
            if invalid:
                add("G2-SCH-PIN-RANGE-"+ref,"BLOCKER","schematic","FAIL",
                    "%r is a 41-pin module, but compiled schematic exposes invalid pin numbers %s."
                    %(i["value"],invalid),"VERIFIED",ref)

        if declared=="TL2904":
            names={str(x.get("name") or "").upper() for x in pins.values()}
            if len(pins)==16 and {"+","-","C","E"}.issubset(names):
                add("G2-SCH-PIN-FUNCTION-"+ref,"BLOCKER","schematic","FAIL",
                    "Value TL2904 is compiled as a 16-pin optocoupler pattern (+/-/C/E), not its intended amplifier function.",
                    "VERIFIED",ref)

        if declared=="BCX56":
            lib=_norm(i.get("library")); desc=(i.get("description") or "").lower()
            if "C1815" in lib or "C9014" in desc:
                add("G2-SCH-IDENTITY-"+ref,"BLOCKER","schematic","FAIL",
                    "Value BCX56 conflicts with compiled transistor symbol/function evidence %r / %r."
                    %(i.get("library"),i.get("description")),"VERIFIED",ref)

    for n in (netlist or {}).get("nets",[]) or []:
        name=_text(n.get("name")) or "<unnamed>"
        terms=n.get("terminals",[]) or []
        if not terms:
            add("G2-NET-EMPTY-"+name,"HIGH","schematic","FAIL",
                "Compiled net %r contains no terminals."%name,"VERIFIED",name)
            continue
        outs=[t for t in terms if str(t.get("pin_type","")).upper()=="OUTPUT"]
        ins=[t for t in terms if str(t.get("pin_type","")).upper() in {"INPUT","CLOCK","IO"}]
        if len(outs)>1:
            ids2=", ".join("%s.%s"%(t.get("designator"),t.get("pin")) for t in outs)
            add("G2-NET-OUTPUT-CONFLICT-"+name,"BLOCKER","schematic","FAIL",
                "Net %r has multiple OUTPUT terminals: %s."%(name,ids2),"VERIFIED",name)
        if outs and not ins and len(terms)>1:
            add("G2-NET-OUTPUT-NO-CONSUMER-"+name,"MEDIUM","schematic","WARN",
                "Net %r has an OUTPUT but no INPUT/CLOCK/IO consumer among %d terminals."
                %(name,len(terms)),"INFERRED",name)
    return ids
