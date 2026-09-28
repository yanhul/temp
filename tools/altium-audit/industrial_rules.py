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

def evaluate(config_path: Path | None):
    cfg = _load(config_path)
    if cfg is None:
        return {"status": "BLOCKED", "reason": "industrial rule authority/config is missing",
                "standards": NORMATIVE, "missing": PLACEMENT_KEYS + ROUTING_KEYS}
    rules = cfg.get("industrial_rules")
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
