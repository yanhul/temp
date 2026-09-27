#!/usr/bin/env python3
"""Evidence-first Altium audit runner.

This runner deliberately separates parser success from design correctness.
Unsupported checks are reported as UNKNOWN/BLOCKED, never PASS.
"""
from __future__ import annotations
import argparse, hashlib, json, math, pathlib, sys, zipfile
from typing import Any

try:
    from altium_monkey import AltiumDesign
except Exception as exc:
    print(f"BLOCKED G1: cannot import altium_monkey: {exc}", file=sys.stderr)
    raise

def field(obj: Any, *keys: str):
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

def as_name(obj: Any):
    v = field(obj, "designator", "refdes", "reference", "name", "component", "id")
    return str(v) if v is not None else None

def add(findings, fid, severity, domain, status, evidence, confidence="VERIFIED", obj=None):
    findings.append({
        "id": fid, "severity": severity, "domain": domain, "status": status,
        "object": obj, "evidence": evidence, "confidence": confidence,
    })

def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def reconstruct(parts, out):
    parts = sorted(parts.glob("part_*.txt"))
    if not parts:
        raise RuntimeError("no b64parts/part_*.txt found")
    import base64
    raw = b"".join(p.read_bytes().strip() for p in parts)
    out.write_bytes(base64.b64decode(raw, validate=True))
    return parts

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, type=pathlib.Path)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--archive", type=pathlib.Path)
    ap.add_argument("--source-sha256", type=str)
    args = ap.parse_args()
    root, out = args.root, args.out
    out.mkdir(parents=True, exist_ok=True)
    findings = []

    prjs = sorted(root.rglob("*.PrjPcb"))
    schs = sorted(root.rglob("*.SchDoc"))
    pcbs = sorted(root.rglob("*.PcbDoc"))
    if not prjs or not schs or not pcbs:
        missing = [p for p, xs in (("*.PrjPcb",prjs),("*.SchDoc",schs),("*.PcbDoc",pcbs)) if not xs]
        add(findings,"G0-REQUIRED-FILES","BLOCKER","intake","UNKNOWN",
            "Required Altium files missing: " + ", ".join(missing),"FACT")
        write_outputs(out, {"status":"BLOCKED","gates":{"G0_INTAKE":"UNKNOWN"},"findings":findings})
        return 2

    archive_hash = sha256(args.archive) if args.archive and args.archive.exists() else None
    if args.source_sha256 and archive_hash:
        if archive_hash.lower() == args.source_sha256.lower():
            add(findings,"G0-ARCHIVE-HASH","INFO","intake","VERIFIED",
                f"Archive SHA256 matches declared source hash {archive_hash}.","VERIFIED")
        else:
            add(findings,"G0-ARCHIVE-HASH","BLOCKER","intake","FAIL",
                f"Archive SHA256 {archive_hash} does not match declared source hash {args.source_sha256}.","VERIFIED")
    else:
        add(findings,"G0-ARCHIVE-HASH","BLOCKER","intake","UNKNOWN",
            "No authoritative source SHA256 was supplied; archive byte identity cannot be proven.","FACT")

    try:
        design = AltiumDesign.from_prjpcb(str(prjs[0]))
        payload = design.to_json(include_pnp=True, include_compile_metadata=True, include_indexes=True)
        pcb = design.load_pcbdoc()
        netlist_obj = design.to_netlist()
        netlist_text = netlist_obj.to_json_text()
        netlist = json.loads(netlist_text)
        add(findings,"G1-PARSE","INFO","parse","VERIFIED",
            f"Loaded project {prjs[0].name}, schematic count={len(schs)}, PCB count={len(pcbs)}.","VERIFIED")
    except Exception as exc:
        add(findings,"G1-PARSE","BLOCKER","parse","UNKNOWN",
            f"Authoritative parser load failed: {type(exc).__name__}: {exc}","FACT")
        write_outputs(out, {"status":"BLOCKED","gates":{"G0_INTAKE":"VERIFIED","G1_PARSE":"UNKNOWN"},"findings":findings})
        return 2

    diagnostics = payload.get("diagnostics") or []
    compile_data = payload.get("compile")
    if compile_data is None:
        add(findings,"G2-COMPILE","BLOCKER","compile","UNKNOWN",
            "Parser emitted no compile metadata.","FACT")
    elif diagnostics:
        add(findings,"G2-DIAGNOSTICS","HIGH","compile","FAIL",
            f"{len(diagnostics)} compile diagnostic record(s) emitted.","VERIFIED")
    else:
        add(findings,"G2-COMPILE","INFO","compile","VERIFIED",
            "Compile metadata is present and diagnostics are empty.","VERIFIED")

    sch_components = payload.get("components", []) or []
    pcb_components = list(getattr(pcb, "components", []) or [])
    srefs = {as_name(x) for x in sch_components if as_name(x)}
    prefs = {as_name(x) for x in pcb_components if as_name(x)}
    for ref in sorted(srefs - prefs):
        add(findings,f"G3-SCH-ONLY-{ref}","HIGH","connectivity","FAIL",
            "Schematic reference absent from parsed PCB component set.","VERIFIED",ref)
    for ref in sorted(prefs - srefs):
        add(findings,f"G3-PCB-ONLY-{ref}","HIGH","connectivity","FAIL",
            "PCB reference absent from parsed schematic component set.","VERIFIED",ref)
    if srefs == prefs:
        add(findings,"G3-REFDES","INFO","connectivity","VERIFIED",
            f"Schematic/PCB references reconcile: {len(srefs)} common references.","VERIFIED")
    else:
        add(findings,"G3-REFDES","BLOCKER","connectivity","FAIL",
            f"Reference mismatch: {len(srefs-prefs)} schematic-only; {len(prefs-srefs)} PCB-only.","VERIFIED")

    # Authoritative terminal join.
    nl_nets = netlist.get("nets", []) or []
    sch_pin_to_net = {}
    for n in nl_nets:
        nn = field(n,"name","uid")
        for t in field(n,"terminals") or []:
            ref, pin = field(t,"designator","refdes","reference"), field(t,"pin","pin_designator","number")
            if ref is not None and pin is not None:
                sch_pin_to_net[(str(ref),str(pin))] = None if nn is None else str(nn)
    pcb_nets = list(getattr(pcb,"nets",[]) or [])
    pcb_pads = list(getattr(pcb,"pads",[]) or [])
    ref_by_idx = {i: as_name(c) for i,c in enumerate(pcb_components)}
    net_by_idx = {i: field(n,"name","net_name","netname","uid") for i,n in enumerate(pcb_nets)}
    pcb_pin_to_net = {}
    unresolved = 0
    for pad in pcb_pads:
        ci, pin, ni = field(pad,"component_index"), field(pad,"designator","pad_designator","number"), field(pad,"net_index")
        # Board-level / component-less pads (e.g. mechanical or standalone pads)
        # cannot correspond to a schematic terminal and must not poison SCH↔PCB
        # terminal reconciliation.
        if ci is None:
            continue
        if pin is None or ni is None:
            unresolved += 1
            continue
        ref = ref_by_idx.get(int(ci))
        if ref is not None:
            pcb_pin_to_net[(str(ref),str(pin))] = net_by_idx.get(int(ni))
    common = set(sch_pin_to_net) & set(pcb_pin_to_net)
    mismatches = [(k,sch_pin_to_net[k],pcb_pin_to_net[k]) for k in sorted(common)
                  if sch_pin_to_net[k] is not None and pcb_pin_to_net[k] is not None
                  and sch_pin_to_net[k].strip().upper() != str(pcb_pin_to_net[k]).strip().upper()]
    missing = set(sch_pin_to_net) - set(pcb_pin_to_net)
    extra = set(pcb_pin_to_net) - set(sch_pin_to_net)
    for (ref,pin),a,b in mismatches[:200]:
        add(findings,f"G3-PIN-NET-{ref}-{pin}","HIGH","connectivity","FAIL",
            f"Schematic net={a!r}, PCB pad net={b!r}.","VERIFIED",f"{ref}.{pin}")
    if missing or unresolved:
        add(findings,"G3-PIN-MISSING-ON-PCB","BLOCKER","connectivity","UNKNOWN",
            f"{len(missing)} schematic terminals lack normalized PCB pads; {unresolved} pads were structurally unresolved.","FACT")
    if extra:
        add(findings,"G3-PAD-NOT-IN-SCH","HIGH","connectivity","FAIL",
            f"{len(extra)} PCB pad terminals lack schematic terminal counterparts.","VERIFIED")
    if common and not mismatches and not missing and not extra and not unresolved:
        add(findings,"G3-PIN-NET","INFO","connectivity","VERIFIED",
            f"Full terminal join verified for {len(common)} SCH↔PCB terminal pairs.","VERIFIED")
    elif not common:
        add(findings,"G3-PIN-NET","BLOCKER","connectivity","UNKNOWN",
            "No normalized terminal/pad intersection was available for authoritative reconciliation.","FACT")

    counts = {}
    for attr in ("components","pads","vias","tracks","arcs","fills","regions","texts","nets","rules"):
        try: counts[attr] = len(getattr(pcb, attr))
        except Exception: counts[attr] = None

    # Deterministic subset of PCB rule checks.
    rules = list(getattr(pcb,"rules",[]) or [])
    enabled = [r for r in rules if getattr(r,"enabled",True)]
    add(findings,"G4-RULE-INVENTORY","INFO","pcb","VERIFIED",
        f"Parsed {len(rules)} PCB rules; {len(enabled)} enabled.","VERIFIED")
    def mil(v):
        try:
            s=str(v).strip().lower().replace("mil","").strip()
            return float(s)
        except Exception:
            return None
    width_rule = next((r for r in enabled if str(getattr(r,"rule_kind","")).lower()=="width"),None)
    minw = mil(field(width_rule,"minimum_width","min_width")) if width_rule else None
    if minw is not None:
        bad=[]
        for i,t in enumerate(list(getattr(pcb,"tracks",[]) or [])):
            w=mil(getattr(t,"width_mils",None))
            if w is not None and w < minw: bad.append((i,w))
        if bad:
            for i,w in bad[:200]:
                add(findings,f"G4-TRACK-WIDTH-{i}","HIGH","pcb","FAIL",
                    f"Track width {w:g}mil < rule minimum {minw:g}mil.","VERIFIED",f"track#{i}")
        else:
            add(findings,"G4-TRACK-WIDTH","INFO","pcb","VERIFIED",
                f"Evaluated {len(list(getattr(pcb,'tracks',[]) or []))} tracks against minimum width {minw:g}mil.","VERIFIED")
    else:
        add(findings,"G4-TRACK-WIDTH","BLOCKER","pcb","UNKNOWN",
            "Authoritative minimum Width rule field is not exposed; preferred width is not treated as a minimum.","FACT")

    # Electrical structural checks.
    single = [n for n in nl_nets if len(n.get("terminals",[]) or []) == 1]
    for n in single[:200]:
        add(findings,f"G5-SINGLE-NET-{n.get('name','UNKNOWN')}","MEDIUM","electrical","FAIL",
            f"Net {n.get('name')!r} has exactly one compiled terminal; intentionality is not established.","VERIFIED",n.get("name"))
    outputs=[]
    for n in nl_nets:
        outs=[t for t in n.get("terminals",[]) or [] if str(t.get("pin_type","")).upper()=="OUTPUT"]
        if len(outs)>1: outputs.append((n,outs))
    for n,outs in outputs:
        ids=", ".join(f"{t.get('designator')}.{t.get('pin')}" for t in outs)
        add(findings,f"G5-OUTPUT-CONFLICT-{n.get('name','UNKNOWN')}","HIGH","electrical","FAIL",
            f"Net {n.get('name')!r} contains multiple OUTPUT pins: {ids}.","VERIFIED",n.get("name"))
    if not single: add(findings,"G5-SINGLE-PIN-NETS","INFO","electrical","VERIFIED","No single-terminal compiled nets.","VERIFIED")
    if not outputs: add(findings,"G5-OUTPUT-CONFLICTS","INFO","electrical","VERIFIED","No definite OUTPUT↔OUTPUT conflict found from pin semantics.","VERIFIED")
    add(findings,"G5-INTENT-COVERAGE","BLOCKER","electrical","UNKNOWN",
        "Protection, level compatibility, biasing, decoupling and project-specific power intent are not derivable from generic connectivity alone.","FACT")
    add(findings,"G6-PHYSICAL","BLOCKER","physical","UNKNOWN",
        "Full DRC/mechanical geometry equivalence is not implemented; unsupported checks remain UNKNOWN.","FACT")
    add(findings,"G7-FUNCTIONAL","BLOCKER","functional","UNKNOWN",
        "Functional correctness requires explicit design intent and cannot be inferred from parser structure alone.","FACT")

    gates = {
        "G0_INTAKE": "VERIFIED" if not any(f["id"]=="G0-ARCHIVE-HASH" and f["status"]!="VERIFIED" for f in findings) else "BLOCKED",
        "G1_PARSE":"VERIFIED",
        "G2_COMPILE":"VERIFIED" if compile_data is not None and not diagnostics else ("FAIL" if diagnostics else "UNKNOWN"),
        "G3_CONNECTIVITY":"VERIFIED" if not any(f["id"].startswith("G3-") and f["status"] in ("FAIL","UNKNOWN","BLOCKED") for f in findings) else "BLOCKED",
        "G4_PCB":"VERIFIED" if not any(f["id"].startswith("G4-") and f["status"] in ("FAIL","UNKNOWN","BLOCKED") for f in findings) else "BLOCKED",
        "G5_ELECTRICAL":"BLOCKED","G6_PHYSICAL":"BLOCKED","G7_FUNCTIONAL":"BLOCKED","G8_REPORT":"VERIFIED"
    }
    status = "FAIL" if any(f["status"]=="FAIL" and f["severity"] in ("HIGH","BLOCKER") for f in findings) else "BLOCKED"
    result = {
        "schema":"altium-audit/v2","status":status,"project":str(prjs[0]),
        "source_sha256":archive_hash,"gates":gates,"counts":counts,
        "findings":findings,"diagnostics":diagnostics,
        "lineage":{"project":str(prjs[0]),"schematic_files":[str(x) for x in schs],
                   "pcb_files":[str(x) for x in pcbs]}
    }
    (out/"design.json").write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding="utf-8")
    (out/"netlist.json").write_text(netlist_text,encoding="utf-8")
    (out/"pcb_probe.txt").write_text(json.dumps({"counts":counts,"rules":len(rules),
        "pcb_attributes":sorted(x for x in dir(pcb) if not x.startswith("_"))},indent=2),encoding="utf-8")
    (out/"g4_probe.json").write_text(json.dumps({"rule_count":len(rules),"enabled_rule_count":len(enabled),
        "width_rule_exposed":minw is not None,"width_rule_field":"minimum_width" if minw is not None else None,"counts":counts},indent=2),encoding="utf-8")
    report=["# Altium Audit Report","","**Overall:** "+status,"","## Gates"]
    report += [f"- **{k}**: {v}" for k,v in gates.items()]
    report += ["","## Findings"]
    for f in findings:
        report += [f"### {f['id']} — {f['severity']} / {f['status']}",
                    f"- Domain: {f['domain']}",f"- Object: {f['object']}",
                    f"- Evidence: {f['evidence']}",f"- Confidence: {f['confidence']}",""]
    (out/"report.md").write_text("\n".join(report),encoding="utf-8")
    (out/"summary.json").write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding="utf-8")
    (out/"findings.json").write_text(json.dumps(findings,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps({"status":status,"gates":gates},indent=2))
    return 0 if status=="BLOCKED" else 1

def write_outputs(out, summary):
    out.mkdir(parents=True,exist_ok=True)
    (out/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    (out/"report.md").write_text("# Altium Audit Report\n\n"+json.dumps(summary,indent=2),encoding="utf-8")

if __name__ == "__main__":
    raise SystemExit(main())
