#!/usr/bin/env python3
"""Evidence-first schematic semantic checks.

This module distinguishes generic library-symbol names from authoritative part
identity. It uses compiled design metadata (Value, MPN, classification, and
description) when available and fails closed only on contradictions that can
actually be proven.
"""
from __future__ import annotations
import re
from typing import Any

def _field(obj: Any, *keys: str):
    if isinstance(obj, dict):
        for k in keys:
            if k in obj and obj.get(k) is not None:
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
    if v is None: return None
    if isinstance(v,(str,int,float)):
        s=str(v).strip()
        return s or None
    return str(v).strip() or None

def _children(obj):
    for k in ("parameters","children","pins","properties"):
        v=_field(obj,k)
        if v is None: continue
        if isinstance(v,dict):
            for name,value in v.items():
                yield {"name":name,"value":value}
        else:
            try: yield from list(v)
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
        if name and value: out[name.strip().lower()]=value
    return out

KNOWN_PIN_COUNTS = {
    "ESP32S3WROOM1": 41,
    "ESP32S3WROOM1U": 41,
    "HCPL0600": 8,
    "HCPL3120": 8,
    "PC817": 4,
}

GENERIC_LIBRARY_TOKENS = {
    "RES","R","CAP","C","IND","L","DIODE","LED","D","TRANSISTOR","Q",
    "CONN","CONNECTOR","HEADER","XTAL","FUSE","CRYSTAL"
}

def _norm_part(s):
    if not s: return None
    return re.sub(r"[^A-Z0-9]+","",str(s).upper())

def _pin_count(c):
    direct=_field(c,"pin_count")
    try:
        if direct is not None: return int(direct)
    except Exception: pass
    classification=_field(c,"classification")
    if isinstance(classification,dict):
        try:
            if classification.get("pin_count") is not None:
                return int(classification["pin_count"])
        except Exception: pass
    pins=_field(c,"pins")
    if pins is not None:
        try: return len(list(pins))
        except Exception: pass
    vals=[]
    for x in _children(c):
        if "pin" in type(x).__name__.lower(): vals.append(x)
    return len(vals) if vals else None

def _component_identity(c):
    props=_prop_map(c)
    ref=_text(_field(c,"designator","refdes","reference","logical_designator","physical_designator")) or props.get("designator")
    value=_text(_field(c,"value","component_value","display_value")) or props.get("value")
    lib=_text(_field(c,"library_reference","library_ref","lib_reference","library_name","symbol_name"))
    footprint=_text(_field(c,"footprint","footprint_name")) or props.get("footprint")
    desc=_text(_field(c,"description","desc")) or props.get("description")
    mpn=None
    for k in ("manufacturer part number","manufacturer_part_number","manufacturerpartnumber","mpn","partnumber","part_number","supplier part number-1"):
        if props.get(k): mpn=props[k]; break
    classification=_field(c,"classification")
    ctype=_text(classification.get("type")) if isinstance(classification,dict) else None
    return {
        "ref":ref,"value":value,"library":lib,"footprint":footprint,"mpn":mpn,
        "description":desc,"classification_type":ctype,"properties":props,
        "pin_count":_pin_count(c),
    }

def inspect_components(components):
    return [_component_identity(c) for c in (components or []) if _component_identity(c)["ref"]]

def _is_generic_library(lib):
    n=_norm_part(lib)
    if not n: return True
    return n in GENERIC_LIBRARY_TOKENS or any(n.startswith(x) and len(n)<=len(x)+3 for x in GENERIC_LIBRARY_TOKENS)

def _known_conflict(i):
    """Return a concise, evidence-backed identity contradiction or None."""
    ref=i["ref"]; value=_norm_part(i["value"]); mpn=_norm_part(i["mpn"]); lib=_norm_part(i["library"])
    desc=(i.get("description") or "").lower()
    # Explicit manufacturer identity wins over display Value.
    if value and mpn and value != mpn:
        return ("VALUE_MPN", f"Value={i['value']!r} conflicts with Manufacturer Part Number={i['mpn']!r}.")
    if value and lib:
        # Concrete optocoupler / IC family contradictions are unambiguous.
        if value == "HCPL0600" and "HCPL3120" in lib:
            return ("LIBRARY_PART", f"Value={i['value']!r} is an HCPL-0600, but library/compiled symbol is {i['library']!r}.")
        if value == "TL2904" and ("PC817" in lib or "OPTO" in desc):
            return ("LIBRARY_FUNCTION", f"Value={i['value']!r} conflicts with library/description {i['library']!r} / {i.get('description')!r}.")
        if value == "BCX56" and ("C1815" in lib or "C9014" in desc):
            return ("LIBRARY_PART", f"Value={i['value']!r} conflicts with library symbol {i['library']!r}.")
        if value in {"SMAJ15CA","SMAJ9CA"} and "SMAJ30CA" in lib:
            return ("LIBRARY_PART", f"Value={i['value']!r} conflicts with library symbol {i['library']!r}.")
    return None

def run(components, netlist, add):
    identities=inspect_components(components)
    for i in identities:
        ref=i["ref"]
        part=_norm_part(i["mpn"] or i["value"])
        if part in KNOWN_PIN_COUNTS and i["pin_count"] is not None and i["pin_count"] != KNOWN_PIN_COUNTS[part]:
            add(f"G2-SCH-PINCOUNT-{ref}","BLOCKER","schematic","FAIL",
                f"Authoritative part {i['mpn'] or i['value']!r} is documented as {KNOWN_PIN_COUNTS[part]} pins, but compiled schematic classification exposes {i['pin_count']} pins.",
                "VERIFIED",ref)
        conflict=_known_conflict(i)
        if conflict:
            kind,evidence=conflict
            sev="BLOCKER" if kind in {"LIBRARY_PART","LIBRARY_FUNCTION"} else "HIGH"
            add(f"G2-SCH-IDENTITY-{ref}","BLOCKER" if sev=="BLOCKER" else "HIGH",
                "schematic","FAIL",evidence,"VERIFIED",ref)
        if not i["value"] and not i["mpn"] and i["library"]:
            add(f"G2-SCH-NO-PART-VALUE-{ref}","MEDIUM","schematic","UNKNOWN",
                f"No authoritative Value/MPN field was exposed for library symbol {i['library']!r}.","FACT",ref)

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
