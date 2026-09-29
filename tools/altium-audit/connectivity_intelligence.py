#!/usr/bin/env python3
"""Connectivity intelligence for evidence-first placement planning.

This module is advisory: it never mutates a PCB and never upgrades heuristic
classification to authoritative design intent.
"""
from __future__ import annotations
import json
import re
from collections import defaultdict
from pathlib import Path

_HIGH = ("USB", "USB_D+", "USB_D-", "CLK", "CLOCK", "XTAL", "OSC", "DIFF", "ETH", "MII", "RMII", "LVDS")
_POWER = ("VBUS", "VCC", "VDD", "VSS", "GND", "AGND", "DGND", "5V", "3V3", "3.3V", "12V", "24V", "VIN", "VOUT")
_RESET = ("RESET", "RST", "EN", "ENABLE")
_ANALOG = ("ADC", "DAC", "ANALOG", "SENSE", "FB", "REF")
_CONTROL = ("UART", "RX", "TX", "I2C", "SPI", "CAN", "GPIO", "SCL", "SDA", "MOSI", "MISO", "CS")
_DIGITAL = ("DATA", "D0", "D1", "D2", "D3", "D4", "D5", "D6", "D7", "IO")


def _tokens(name: str) -> str:
    return re.sub(r"[^A-Z0-9_+\-\.]", "_", str(name).upper())


def classify_net(name: str) -> dict:
    n = _tokens(name)
    def hit(items): return any(x in n for x in items)
    if hit(_HIGH): cls, crit = "HIGH_SPEED", "HIGH"
    elif hit(_POWER): cls, crit = ("GROUND" if any(x in n for x in ("GND","AGND","DGND")) else "POWER"), "HIGH"
    elif hit(_RESET): cls, crit = "RESET", "HIGH"
    elif hit(_ANALOG): cls, crit = "ANALOG", "MEDIUM"
    elif hit(_CONTROL): cls, crit = "CONTROL", "MEDIUM"
    elif hit(_DIGITAL): cls, crit = "DIGITAL", "LOW"
    else: cls, crit = "UNKNOWN", "UNKNOWN"
    return {"class": cls, "criticality": crit, "basis": "net-name heuristic"}


def build(netlist: dict) -> dict:
    nets = list((netlist or {}).get("nets", []) or [])
    component_nets = defaultdict(list)
    normalized = []
    for raw in nets:
        name = raw.get("name") or raw.get("uid") or "UNKNOWN"
        name = str(name)
        terminals = list(raw.get("terminals", []) or [])
        refs = sorted({str(t.get("designator") or t.get("refdes") or t.get("reference"))
                       for t in terminals
                       if t.get("designator") is not None or t.get("refdes") is not None or t.get("reference") is not None})
        c = classify_net(name)
        rec = {
            "name": name,
            "terminal_count": len(terminals),
            "components": refs,
            "class": c["class"],
            "criticality": c["criticality"],
            "classification_confidence": "HEURISTIC" if c["class"] != "UNKNOWN" else "UNKNOWN",
            "classification_basis": c["basis"],
            "placement_affinity": "STRONG" if len(refs) == 2 and c["criticality"] == "HIGH" else
                                  "MEDIUM" if len(refs) <= 4 and c["criticality"] in ("HIGH","MEDIUM") else
                                  "WEAK"
        }
        normalized.append(rec)
        for ref in refs:
            component_nets[ref].append(name)

    pair_weights = defaultdict(float)
    pair_evidence = defaultdict(list)
    class_weight = {"HIGH": 5.0, "MEDIUM": 3.0, "LOW": 1.0, "UNKNOWN": 0.25}
    for n in normalized:
        refs = n["components"]
        if len(refs) < 2: continue
        # A large bus should not create quadratic false affinity between every
        # component. Pair affinity is capped by a small per-net contribution.
        contribution = class_weight[n["criticality"]] / max(1.0, min(len(refs), 8) - 1)
        for i, a in enumerate(refs):
            for b in refs[i+1:]:
                key = tuple(sorted((a,b)))
                pair_weights[key] += contribution
                pair_evidence[key].append({"net": n["name"], "class": n["class"], "criticality": n["criticality"]})

    affinities = []
    for (a,b), weight in sorted(pair_weights.items(), key=lambda x: (-x[1], x[0])):
        affinities.append({
            "a": a, "b": b, "weight": round(weight, 4),
            "evidence": pair_evidence[(a,b)][:20],
            "status": "SUGGESTED",
            "authority": "derived_from_compiled_netlist"
        })

    clusters = []
    # Deterministic connected components over non-trivial affinities.
    adj = defaultdict(set)
    for p in affinities:
        if p["weight"] >= 3.0:
            adj[p["a"]].add(p["b"]); adj[p["b"]].add(p["a"])
    seen = set()
    for ref in sorted(adj):
        if ref in seen: continue
        stack=[ref]; group=[]; seen.add(ref)
        while stack:
            x=stack.pop(); group.append(x)
            for y in sorted(adj[x]):
                if y not in seen: seen.add(y); stack.append(y)
        if len(group) > 1:
            clusters.append({"components": sorted(group), "status": "SUGGESTED", "basis": "connectivity affinity"})

    return {
        "schema": "altium-connectivity-intelligence.v1",
        "status": "VERIFIED" if nets else "BLOCKED",
        "authority": "compiled_netlist" if nets else "UNAVAILABLE",
        "classification_policy": "heuristic; never treated as authoritative electrical intent",
        "nets": normalized,
        "component_nets": {k: sorted(v) for k,v in sorted(component_nets.items())},
        "component_affinity": affinities,
        "functional_clusters": clusters,
        "placement_constraints": {
            "strong_affinity": [x for x in affinities if x["weight"] >= 5.0],
            "medium_affinity": [x for x in affinities if 3.0 <= x["weight"] < 5.0],
            "unknown_intent": [x["name"] for x in normalized if x["class"] == "UNKNOWN"]
        }
    }


def write(netlist_path: Path, out: Path) -> dict:
    data = json.loads(netlist_path.read_text(encoding="utf-8"))
    result = build(data)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


if __name__ == "__main__":
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument("--netlist",required=True,type=Path)
    ap.add_argument("--out",required=True,type=Path)
    a=ap.parse_args()
    result=write(a.netlist,a.out)
    print(json.dumps({"status":result["status"],"nets":len(result["nets"]),"affinity_pairs":len(result["component_affinity"]),"clusters":len(result["functional_clusters"])}))
    raise SystemExit(0 if result["status"]=="VERIFIED" else 1)
