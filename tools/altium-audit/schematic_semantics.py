#!/usr/bin/env python3
"""Evidence-first schematic semantic checks.

This module never invents part numbers or pin functions. It compares the
authoritative schematic object metadata and compiled netlist against itself,
and emits BLOCK/FAIL when the design contains contradictions that can be
proven without a human intent database.
"""
from __future__ import annotations
import re
from typing import Any

def _field(obj: Any, *keys: str):
    if isinstance(obj, dict):
        for k in keys:
            if obj.get(k) is not None:
                return obj[k]
    for k in keys:
        try:
            v = getattr(obj, k)
            if v is not None:
                return v
        except Exception:
            pass
    return None

def _text(v):
    if v is None:
        return None
    if isinstance(v, (str, int, float)):
        s=str(v).strip()
        return s or None
    return str(v).strip() or None

def _children(obj):
    for k in ("parameters","children","pins","properties"):
        v=_field(obj,k)
        if v is not None:
            try:
                yield from list(v)
            except Exception:
                pass

def _prop_map(obj):
    out={}
    for c in _children(obj):
        name=_text(_field(c,"name","parameter_name","key","key_name"))
        value=_text(_field(c,"text","value","parameter_value"))
        if name and value:
            out[name.strip().lower()]=value
    return out

KNOWN_PIN_COUNTS = {
    "ESP32S3WROOM1": 41,
    "ESP32S3WROOM1U": 41,
    "HCPL0600": 8,
    "HCPL3120": 8,
    "PC817": 4,
}

def _pin_count(c):
    pins=_field(c,"pins")
    if pins is not None:
        try:
            return len(list(pins))
        except Exception:
            pass
    vals=[]
    for x in _children(c):
        kind=type(x).__name__.lower()
        if "pin" in kind:
            vals.append(x)
    return len(vals) if vals else None

def _component_identity(c):
    props=_prop_map(c)
    ref=_text(_field(c,"designator","refdes","reference")) or props.get("designator")
    value=_text(_field(c,"value","component_value","display_value")) or props.get("value")
    lib=_text(_field(c,"library_reference","lib_reference","library_ref","library_name","name","symbol_name"))
    footprint=_text(_field(c,"footprint","footprint_name")) or props.get("footprint")
    mpn=None
    for k in ("mpn","partnumber","part_number","manufacturer part number","manufacturer_part_number","manufacturerpartnumber"):
        if props.get(k):
            mpn=props[k]; break
    if mpn is None:
        mpn=_text(_field(c,"mpn","partnumber","part_number","manufacturer_part_number"))
    return {"ref":ref,"value":value,"library":lib,"footprint":footprint,"mpn":mpn,"properties":props,"pin_count":_pin_count(c)}

def _norm_part(s):
    if not s: return None
    return re.sub(r"[^A-Z0-9]+","",s.upper())

def inspect_components(components):
    identities=[]
    for c in components or []:
        i=_component_identity(c)
        if i["ref"]:
            identities.append(i)
    return identities

def run(components, netlist, add):
    """Run contradiction checks; add is the runner finding sink."""
    identities=inspect_components(components)
    for i in identities:
        ref=i["ref"]
        part=_norm_part(i["mpn"] or i["value"])
        if part in KNOWN_PIN_COUNTS and i["pin_count"] is not None and i["pin_count"] != KNOWN_PIN_COUNTS[part]:
            add(
                f"G2-SCH-PINCOUNT-{ref}","BLOCKER","schematic","FAIL",
                f"Authoritative part {i['mpn'] or i['value']!r} is documented as {KNOWN_PIN_COUNTS[part]} pins, but the parsed schematic symbol exposes {i['pin_count']} pins.",
                "VERIFIED",ref)
        lib=_norm_part(i["library"])
        if part and lib and part != lib:
            generic={"RES","R","CAP","C","IND","L","DIODE","LED","D","TRANSISTOR","Q","CONN","CONNECTOR"}
            if lib not in generic and part not in generic:
                add(
                    f"G2-SCH-IDENTITY-{ref}","BLOCKER","schematic","FAIL",
                    f"Schematic part identity conflicts with library symbol: part/value/MPN={i['mpn'] or i['value']!r}, library={i['library']!r}.",
                    "VERIFIED",ref)
        if i["mpn"] and i["value"] and _norm_part(i["mpn"]) != _norm_part(i["value"]):
            add(
                f"G2-SCH-MPN-VALUE-{ref}","HIGH","schematic","WARN",
                f"MPN={i['mpn']!r} and Value={i['value']!r} differ; manufacturer identity must be resolved explicitly before functional authorization.",
                "FACT",ref)
        if not i["value"] and not i["mpn"] and i["library"]:
            add(
                f"G2-SCH-NO-PART-VALUE-{ref}","MEDIUM","schematic","UNKNOWN",
                f"No authoritative Value/MPN field was exposed for library symbol {i['library']!r}.",
                "FACT",ref)

    nets=(netlist or {}).get("nets",[]) or []
    for n in nets:
        name=_text(n.get("name")) or "<unnamed>"
        terms=n.get("terminals",[]) or []
        if not terms:
            add(f"G2-NET-EMPTY-{name}","HIGH","schematic","FAIL",
                f"Compiled net {name!r} contains no terminals.","VERIFIED",name)
            continue
        outputs=[t for t in terms if str(t.get("pin_type","")).upper()=="OUTPUT"]
        inputs=[t for t in terms if str(t.get("pin_type","")).upper() in {"INPUT","CLOCK","IO"}]
        if len(outputs)>1:
            ids=", ".join(f"{t.get('designator')}.{t.get('pin')}" for t in outputs)
            add(f"G2-NET-OUTPUT-CONFLICT-{name}","BLOCKER","schematic","FAIL",
                f"Net {name!r} has multiple OUTPUT terminals: {ids}.","VERIFIED",name)
        if outputs and not inputs and len(terms)>1:
            add(f"G2-NET-OUTPUT-NO-CONSUMER-{name}","MEDIUM","schematic","WARN",
                f"Net {name!r} has an OUTPUT but no INPUT/CLOCK/IO consumer among {len(terms)} compiled terminals.",
                "INFERRED",name)
    return identities

__all__=["run","inspect_components"]
