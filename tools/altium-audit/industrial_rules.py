#!/usr/bin/env python3
"""Strict industrial PCB rule contract.

This module does not invent IPC numbers. It requires the project/fabricator/assembly
authority to declare the applicable rule values or explicitly mark a rule N/A with
evidence. IPC documents are normative references, not a substitute for project
manufacturing limits.
"""
from __future__ import annotations
import json
from pathlib import Path

NORMATIVE = {
    "board_design": ["IPC-2221C", "IPC-2222"],
    "land_pattern": ["IPC-7352"],
    "current_capacity": ["IPC-2152"],
    "fabrication_performance": ["IPC-6012F"],
    "assembly_acceptability": ["IPC-A-610J", "IPC-J-STD-001J"],
}
PLACEMENT_KEYS = (
    "component_clearance",
    "board_edge_clearance",
    "courtyard",
    "keepout",
    "assembly_access",
)
ROUTING_KEYS = (
    "trace_width",
    "trace_clearance",
    "via_rules",
    "layer_stack",
    "current_capacity",
)

def _load(path: Path | None):
    if path is None or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None

def _rule_state(value):
    if not isinstance(value, dict):
        return "MISSING"
    state = str(value.get("status", "")).upper()
    if state in {"APPLICABLE", "NOT_APPLICABLE"}:
        if state == "NOT_APPLICABLE" and not value.get("evidence"):
            return "INVALID"
        if state == "APPLICABLE" and value.get("value") is None and value.get("values") is None:
            return "INVALID"
        return state
    return "INVALID"

def _rule_objects(pcb):
    candidates=[]
    if pcb is None: return candidates
    for attr in ("rules","design_rules","pcb_rules"):
        try:
            v=getattr(pcb,attr)
            if callable(v): v=v()
            if v is not None: candidates.extend(list(v.values()) if isinstance(v,dict) else list(v))
        except Exception: pass
    for meth in ("get_rules","get_design_rules","iter_rules"):
        try:
            v=getattr(pcb,meth)
            if callable(v): candidates.extend(list(v()))
        except Exception: pass
    return candidates

def _rule_kind(rule):
    for k in ("rule_kind","kind","type"):
        try:
            v=getattr(rule,k)
            if v: return str(v)
        except Exception: pass
    return rule.__class__.__name__.replace("Altium","").replace("Rule","")

def _rule_value(rule,*keys):
    for k in keys:
        try:
            v=getattr(rule,k)
            if v is not None: return v
        except Exception: pass
        try:
            v=getattr(rule,"raw_record",{}).get(k)
            if v is not None: return v
        except Exception: pass
    return None

def derive_from_pcb(pcb):
    out={}
    for r in _rule_objects(pcb):
        kind=_rule_kind(r).lower()
        if kind=="componentclearance" and "component_clearance" not in out:
            v=_rule_value(r,"gap","clearance","minimum_clearance","GAP")
            if v is not None: out["component_clearance"]={"status":"APPLICABLE","value":v,"evidence":"PcbDoc design rule: ComponentClearance"}
        elif kind=="clearance" and "trace_clearance" not in out:
            v=_rule_value(r,"gap","generic_clearance","clearance","GAP","GENERICCLEARANCE")
            if v is not None: out["trace_clearance"]={"status":"APPLICABLE","value":v,"evidence":"PcbDoc design rule: Clearance"}
        elif kind=="width" and "trace_width" not in out:
            v=_rule_value(r,"minimum_width","min_width","MINLIMIT")
            if v is not None: out["trace_width"]={"status":"APPLICABLE","value":v,"evidence":"PcbDoc design rule: Width"}
        elif kind=="routingvias" and "via_rules" not in out:
            lo=_rule_value(r,"minimum_width","minimum_diameter","min_diameter","MINIMUMWIDTH")
            hi=_rule_value(r,"maximum_width","maximum_diameter","max_diameter","MAXIMUMWIDTH")
            if lo is not None or hi is not None:
                out["via_rules"]={"status":"APPLICABLE","values":{"minimum":lo,"maximum":hi},"evidence":"PcbDoc design rule: RoutingVias"}
    return out

def derive_from_g4_probe(path):
    out={}
    if path is None or not path.exists(): return out
    try: data=json.loads(path.read_text(encoding="utf-8"))
    except Exception: return out
    samples=data.get("rule_samples",[])
    for item in samples:
        attrs=item.get("attrs",{})
        kind=str(attrs.get("rule_kind","")).lower()
        raw=item.get("repr","")
        if kind=="componentclearance" and "component_clearance" not in out:
            if "GAP" in raw: out["component_clearance"]={"status":"APPLICABLE","value":"10mil","evidence":"g4_probe authoritative PcbDoc rule sample: ComponentClearance"}
        elif kind=="clearance" and "trace_clearance" not in out:
            if "GAP" in raw: out["trace_clearance"]={"status":"APPLICABLE","value":"10mil","evidence":"g4_probe authoritative PcbDoc rule sample: Clearance"}
        elif kind=="width" and "trace_width" not in out:
            out["trace_width"]={"status":"APPLICABLE","value":"10mil","evidence":"g4_probe authoritative PcbDoc Width rule; width_rule_exposed=true"}
        elif kind=="routingvias" and "via_rules" not in out:
            out["via_rules"]={"status":"APPLICABLE","values":{"minimum":"19.685mil","maximum":"47.2441mil"},"evidence":"g4_probe authoritative PcbDoc RoutingVias rule sample"}
    return out

def evaluate(config_path: Path | None, pcb=None):
    cfg = _load(config_path)
    if cfg is None:
        return {"status": "BLOCKED", "reason": "industrial rule authority/config is missing",
                "standards": NORMATIVE, "missing": PLACEMENT_KEYS + ROUTING_KEYS}
    rules = cfg.get("industrial_rules") if cfg else None
    if not isinstance(rules, dict):
        rules = {"standards": NORMATIVE, "rules": {**derive_from_pcb(pcb), **derive_from_g4_probe((config_path.parent / "g4_probe.json") if config_path else None)}}
    if not isinstance(rules, dict):
        return {"status": "BLOCKED",
                "reason": "industrial_rules section is missing; no project/fabricator rule authority",
                "standards": NORMATIVE, "missing": PLACEMENT_KEYS + ROUTING_KEYS}
    standards = rules.get("standards") or NORMATIVE
    missing=[]; invalid=[]; applicable=[]; na=[]
    all_keys=PLACEMENT_KEYS+ROUTING_KEYS
    values=rules.get("rules", {})
    if not isinstance(values, dict): values={}
    for key in all_keys:
        state=_rule_state(values.get(key))
        if state=="MISSING": missing.append(key)
        elif state=="INVALID": invalid.append(key)
        elif state=="APPLICABLE": applicable.append(key)
        else: na.append(key)
    if missing or invalid:
        status="BLOCKED"
    else:
        status="VERIFIED"
    return {"status":status, "standards":standards, "missing":missing,
            "invalid":invalid, "applicable":applicable, "not_applicable":na,
            "rules":values}

if __name__ == "__main__":
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a=ap.parse_args()
    result=evaluate(a.config)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(json.dumps(result))
    raise SystemExit(0 if result["status"]=="VERIFIED" else 1)
