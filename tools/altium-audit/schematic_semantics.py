#!/usr/bin/env python3
"""Evidence-first schematic semantic checks."""
from __future__ import annotations
import re
from typing import Any\n\ntry:\n    from part_identity import resolve_declared_vs_compiled\nexcept Exception:\n    resolve_declared_vs_compiled = None

def _field(obj: Any, *keys: str):
    if isinstance(obj, dict):
        for k in keys:
            if k in obj and obj.get(k) is not None: return obj[k]
    for k in keys:
        try:
            v=getattr(obj,k)
            if v is not None: return v
        except Exception: pass
    return None

def _text(v):
    if v is None: return None
    if isinstance(v,(str,int,float)):
        s=str(v).strip(); return s or None
    return str(v).strip() or None

def _children(obj):
    raw=_field(obj,"parameters","children","pins","properties")
    if raw is None: return
    if isinstance(raw,dict):
        for k,v in raw.items(): yield {"name":k,"value":v}
    else:
        try: yield from list(raw)
        except Exception: pass

def _prop_map(obj):
    out={}
    raw=_field(obj,"parameters")
    if isinstance(raw,dict):
        for k,v in raw.items():
            if v is not None: out[str(k).strip().lower()]=_text(v)
    for c in _children(obj):
        name=_text(_field(c,"name","parameter_name","key","key_name"))
        value=_text(_field(c,"text","value","parameter_value"))
        if name and value: out[name.lower()]=value
    return out

def _norm(s):
    return re.sub(r"[^A-Z0-9]+","",str(s or "").upper())

KNOWN_PIN_COUNTS={"ESP32S3WROOM1":41,"ESP32S3WROOM1U":41,"HCPL0600":8,"HCPL3120":8,"PC817":4}
HCPL0600_PINS={"2":"ANODE","3":"CATHODE","5":"GND","6":"VO","7":"VE","8":"VCC"}

def _pin_count(c):
    for source in (_field(c,"pin_count"),):
        try:
            if source is not None: return int(source)
        except Exception: pass
    cl=_field(c,"classification")
    if isinstance(cl,dict):
        try:
            if cl.get("pin_count") is not None: return int(cl["pin_count"])
        except Exception: pass
    pins=_field(c,"pins")
    if pins is not None:
        try: return len(list(pins))
        except Exception: pass
    return None

def _identity(c):
    p=_prop_map(c)
    cl=_field(c,"classification")
    return {
        "ref":_text(_field(c,"designator","refdes","reference","logical_designator","physical_designator")) or p.get("designator"),
        "value":_text(_field(c,"value","component_value","display_value")) or p.get("value"),
        "library":_text(_field(c,"library_reference","library_ref","lib_reference","library_name","symbol_name")),
        "footprint":_text(_field(c,"footprint","footprint_name")) or p.get("footprint"),
        "mpn":next((p.get(k) for k in ("manufacturer part number","manufacturer_part_number","manufacturerpartnumber","mpn","partnumber","part_number") if p.get(k)),None),
        "description":_text(_field(c,"description","desc")) or p.get("description"),
        "pin_count":_pin_count(c),
        "classification_type":_text(cl.get("type")) if isinstance(cl,dict) else None,
        "properties":p,
    }

def inspect_components(components):
    out=[]
    for c in components or []:
        i=_identity(c)
        if i["ref"]: out.append(i)
    return out

def _pins(netlist,ref):
    out={}
    for n in netlist or []:
        for t in n.get("terminals",[]) or []:
            if str(t.get("designator"))==str(ref):
                out[str(t.get("pin"))]={"name":_text(t.get("pin_name")),"net":_text(n.get("name")),"type":_text(t.get("pin_type"))}
    return out

def _conflict(i):
    v=_norm(i["value"]); m=_norm(i["mpn"]); l=_norm(i["library"]); d=(i.get("description") or "").lower()
    prop_value=_norm(i.get("properties",{}).get("value"))
    if v and prop_value and v!=prop_value:
        return "Display Value=%r conflicts with compiled Value property=%r."%(i["value"],i.get("properties",{}).get("value"))
    if v and m and v!=m:
        return "Value=%r conflicts with Manufacturer Part Number=%r."%(i["value"],i["mpn"])
    if v=="HCPL0600" and "HCPL3120" in l:
        return "Value HCPL-0600 conflicts with compiled library identity %r."%i["library"]
    if v=="TL2904" and ("PC817" in l or "opto" in d):
        return "Value TL2904 is compiled as an optocoupler library/function: %r / %r."%(i["library"],i["description"])
    if v=="BCX56" and ("C1815" in l or "C9014" in d):
        return "Value BCX56 conflicts with compiled transistor symbol %r."%i["library"]
    if v in {"SMAJ15CA","SMAJ9CA"} and "SMAJ30CA" in l:
        return "Value %s conflicts with compiled library %r."%(i["value"],i["library"])
    return None

def run(components,netlist,add):
    ids=inspect_components(components)
    for i in ids:
        ref=i["ref"]; part=_norm(i["mpn"] or i["value"])
        if part in KNOWN_PIN_COUNTS and i["pin_count"] is not None and i["pin_count"]!=KNOWN_PIN_COUNTS[part]:
            add("G2-SCH-PINCOUNT-"+ref,"BLOCKER","schematic","FAIL",
                "Authoritative part %r is documented as %d pins, but compiled schematic exposes %d."%(i["mpn"] or i["value"],KNOWN_PIN_COUNTS[part],i["pin_count"]),"VERIFIED",ref)
        conflict=_conflict(i)
        if conflict:
            add("G2-SCH-IDENTITY-"+ref,"BLOCKER","schematic","FAIL",conflict,"VERIFIED",ref)

        pins=_pins(netlist,ref)
        pins=_pins(netlist,ref)
        if resolve_declared_vs_compiled is not None and i.get("value") and i.get("library"):
            identity = resolve_declared_vs_compiled(i.get("value"), i.get("library"), pins)
            if identity["state"] == "CONTRADICTION":
                add("G2-SCH-IDENTITY-EVIDENCE-"+ref,"BLOCKER","schematic","FAIL",
                    "%s Evidence=%s"%(identity["reason"], identity.get("evidence",[])), "VERIFIED", ref)
            elif identity["state"] == "UNKNOWN" and _norm(i.get("value")) != _norm(i.get("library")):
                add("G2-SCH-IDENTITY-EVIDENCE-"+ref,"BLOCKER","schematic","BLOCKED",
                    "Declared value %r and compiled library %r cannot be resolved from authoritative pin evidence: %s"%(i.get("value"),i.get("library"),identity["reason"]), "FACT", ref)

        if part in {"ESP32S3WROOM1","ESP32S3WROOM1U"}:
            invalid=sorted(p for p in pins if p.isdigit() and not 1<=int(p)<=41)
            if invalid:
                add("G2-SCH-PIN-RANGE-"+ref,"BLOCKER","schematic","FAIL",
                    "%r is a 41-pin module, but compiled schematic exposes invalid pin numbers %s."%(i["value"],invalid),"VERIFIED",ref)
        if part=="HCPL0600":
            for pin,want in HCPL0600_PINS.items():
                actual=pins.get(pin,{}).get("name")
                if actual and _norm(actual)!=_norm(want):
                    add("G2-SCH-PIN-FUNCTION-%s-%s"%(ref,pin),"BLOCKER","schematic","FAIL",
                        "HCPL-0600 pin %s must be %s, but compiled symbol exposes %r on net %r."%(pin,want,actual,pins.get(pin,{}).get("net")),"VERIFIED",ref+"."+pin)
        if part=="TL2904":
            names={str(x.get("name") or "").upper() for x in pins.values()}
            if len(pins)==16 and {"+","-","C","E"}.issubset(names):
                add("G2-SCH-PIN-FUNCTION-"+ref,"BLOCKER","schematic","FAIL",
                    "Value TL2904 is compiled as a 16-pin optocoupler pattern (+/-/C/E), not as its intended amplifier function.","VERIFIED",ref)

    for n in (netlist or {}).get("nets",[]) or []:
        name=_text(n.get("name")) or "<unnamed>"; terms=n.get("terminals",[]) or []
        if not terms:
            add("G2-NET-EMPTY-"+name,"HIGH","schematic","FAIL","Compiled net %r contains no terminals."%name,"VERIFIED",name); continue
        outs=[t for t in terms if str(t.get("pin_type","")).upper()=="OUTPUT"]
        ins=[t for t in terms if str(t.get("pin_type","")).upper() in {"INPUT","CLOCK","IO"}]
        if len(outs)>1:
            ids=", ".join("%s.%s"%(t.get("designator"),t.get("pin")) for t in outs)
            add("G2-NET-OUTPUT-CONFLICT-"+name,"BLOCKER","schematic","FAIL","Net %r has multiple OUTPUT terminals: %s."%(name,ids),"VERIFIED",name)
        if outs and not ins and len(terms)>1:
            add("G2-NET-OUTPUT-NO-CONSUMER-"+name,"MEDIUM","schematic","WARN",
                "Net %r has an OUTPUT but no INPUT/CLOCK/IO consumer among %d terminals."%(name,len(terms)),"INFERRED",name)
    return inspect_components(components)
