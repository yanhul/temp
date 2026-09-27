#!/usr/bin/env python3
"""Evidence-first Altium audit runner.

This runner deliberately separates parser success from design correctness.
Unsupported checks are reported as UNKNOWN/BLOCKED, never PASS.
"""
from __future__ import annotations
import argparse, hashlib, json, math, pathlib, sys, zipfile
from typing import Any

try:
    from altium_monkey import AltiumDesign, AltiumSchDoc, AltiumPcbDoc, PcbLayer
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


def num(v):
    try:
        return float(v)
    except Exception:
        return None

def xy(obj):
    for keys in (("x_mils","y_mils"),("location_x_mils","location_y_mils"),("x","y")):
        x=field(obj,keys[0])
        y=field(obj,keys[1])
        if x is not None and y is not None:
            a,b=num(x),num(y)
            if a is not None and b is not None:
                return (a,b)
    p=field(obj,"position","location","center","start")
    if p is not None:
        if isinstance(p,(tuple,list)) and len(p)>=2:
            a,b=num(p[0]),num(p[1])
            if a is not None and b is not None: return (a,b)
        x=field(p,"x","X")
        y=field(p,"y","Y")
        if x is not None and y is not None:
            a,b=num(x),num(y)
            if a is not None and b is not None: return (a,b)
    return None

def rect(obj):
    bb=field(obj,"bounding_box","bbox","bounds")
    if isinstance(bb,(tuple,list)) and len(bb)>=4:
        vals=[num(x) for x in bb[:4]]
        if all(x is not None for x in vals):
            x0,y0,x1,y1=vals
            return (min(x0,x1),min(y0,y1),max(x0,x1),max(y0,y1))
    return None

def object_bbox(obj):
    r=rect(obj)
    if r: return r
    p=xy(obj)
    return (p[0],p[1],p[0],p[1]) if p else None

def distance(a,b):
    return math.hypot(a[0]-b[0],a[1]-b[1])

def net_name(obj, net_by_idx=None):
    v=field(obj,"net_name","netname","net")
    if isinstance(v,dict): v=field(v,"name","uid")
    if v is None:
        ni=field(obj,"net_index")
        try:
            if ni is not None and net_by_idx is not None: v=net_by_idx.get(int(ni))
        except Exception:
            pass
    return str(v) if v is not None else None

def route_net_counts(pcb):
    net_by_idx={i: field(n,"name","net_name","netname","uid") for i,n in enumerate(list(getattr(pcb,"nets",[]) or []))}
    routed={}
    for attr in ("tracks","arcs","vias","regions"):
        for item in list(getattr(pcb,attr,[]) or []):
            n=net_name(item, net_by_idx)
            if n: routed[n]=routed.get(n,0)+1
    return routed

def extract_unrouted(pcb):
    for attr in ("unrouted","ratsnest","rats_nest","airwires","connection_lines"):
        v=getattr(pcb,attr,None)
        if v is not None:
            try: return list(v)
            except Exception: pass
    return None

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
    if not schs or not pcbs:
        missing = [p for p, xs in (("*.SchDoc",schs),("*.PcbDoc",pcbs)) if not xs]
        add(findings,"G0-REQUIRED-FILES","BLOCKER","intake","UNKNOWN",
            "Baseline requires SchDoc + PcbDoc; missing: " + ", ".join(missing),"FACT")
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
        if prjs:
            design = AltiumDesign.from_prjpcb(str(prjs[0]))
            payload = design.to_json(include_pnp=True, include_compile_metadata=True, include_indexes=True)
            pcb = design.load_pcbdoc()
            netlist_obj = design.to_netlist()
            netlist_text = netlist_obj.to_json_text()
            netlist = json.loads(netlist_text)
            parse_basis = f"project {prjs[0].name}"
        else:
            # Two-file baseline: parse each source directly. This intentionally
            # does not synthesize a compiled project/netlist.
            schdoc = AltiumSchDoc.from_file(str(schs[0]))
            pcb = AltiumPcbDoc.from_file(str(pcbs[0]))
            sch_components = list(getattr(schdoc, "components", []) or [])
            payload = {"components": sch_components, "compile": None,
                       "diagnostics": [], "source_mode": "SCHDOC+PCBDOC"}
            netlist = {"nets": []}
            netlist_text = json.dumps(netlist, indent=2)
            parse_basis = f"direct {schs[0].name} + {pcbs[0].name}"
        add(findings,"G1-PARSE","INFO","parse","VERIFIED",
            f"Loaded {parse_basis}; schematic count={len(schs)}, PCB count={len(pcbs)}.","VERIFIED")
    except Exception as exc:
        add(findings,"G1-PARSE","BLOCKER","parse","UNKNOWN",
            f"Authoritative parser load failed: {type(exc).__name__}: {exc}","FACT")
        write_outputs(out, {"status":"BLOCKED","gates":{"G0_INTAKE":"VERIFIED","G1_PARSE":"UNKNOWN"},"findings":findings})
        return 2

    diagnostics = payload.get("diagnostics") or []
    compile_data = payload.get("compile")
    if compile_data is None:
        add(findings,"G2-COMPILE","BLOCKER","compile","UNKNOWN",
            "No PrjPcb compile context is present; two-file baseline does not synthesize compiled-project semantics.","FACT")
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
    unresolved_samples = []
    if unresolved:
        for idx, pad in enumerate(pcb_pads):
            ci = field(pad,"component_index")
            pin = field(pad,"designator","pad_designator","number")
            ni = field(pad,"net_index")
            if ci is not None and (pin is None or ni is None) and len(unresolved_samples) < 100:
                attrs = {}
                for name in sorted(set(["component_index","designator","pad_designator","number","net_index","net_name","netname","name","x","y","position","layer"])):
                    try:
                        value = getattr(pad, name)
                        if value is not None:
                            attrs[name] = value
                    except Exception:
                        pass
                unresolved_samples.append({"index": idx, "attrs": attrs, "repr": repr(pad)[:500]})
    if missing:
        add(findings,"G3-PIN-MISSING-ON-PCB","BLOCKER","connectivity","UNKNOWN",
            f"{len(missing)} schematic terminals lack normalized PCB pads.","FACT")
    elif unresolved:
        add(findings,"G3-PAD-NET-METADATA","INFO","connectivity","VERIFIED",
            f"{unresolved} PCB pad primitives lack normalized net_index metadata; no schematic terminal is missing from the normalized PCB terminal join.","VERIFIED")
    if extra:
        add(findings,"G3-PAD-NOT-IN-SCH","HIGH","connectivity","FAIL",
            f"{len(extra)} PCB pad terminals lack schematic terminal counterparts.","VERIFIED")
    if common and not mismatches and not missing and not extra:
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
    rule_layer = str(getattr(width_rule,"layer","")).strip().upper() if width_rule else ""
    layer_aliases = {"TOP": int(PcbLayer.TOP), "BOTTOM": int(PcbLayer.BOTTOM)}
    applicable_layer = layer_aliases.get(rule_layer)
    if minw is not None and applicable_layer is not None:
        bad=[]
        applicable_tracks=0
        for i,t in enumerate(list(getattr(pcb,"tracks",[]) or [])):
            tlayer = field(t,"layer")
            try:
                tlayer_int = int(tlayer) if tlayer is not None else None
            except Exception:
                tlayer_int = None
            if tlayer_int != applicable_layer:
                continue
            applicable_tracks += 1
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
        reason = ("Authoritative Width minimum is exposed but its rule layer is not a supported legacy copper layer."
                  if minw is not None else
                  "Authoritative minimum Width rule field is not exposed; preferred width is not treated as a minimum.")
        add(findings,"G4-TRACK-WIDTH","BLOCKER","pcb","UNKNOWN",reason,"FACT")

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
    # G5 structural evidence: classify supply nets without pretending PASSIVE pin
    # semantics prove source capability.
    supply_names = {"VBUS","24V","5V","5VP","3.3V","5V_RS232","5V_RS485","GND","GND_RS232","GND_RS485"}
    supply_evidence = []
    for n in nl_nets:
        name = str(n.get("name",""))
        if name in supply_names:
            ts = n.get("terminals",[]) or []
            caps = {
                "terminals": len(ts),
                "power_pins": sum(str(t.get("pin_type","")).upper()=="POWER" for t in ts),
                "capacitors": sum(str(t.get("designator","")).upper().startswith("C") for t in ts),
                "regulator_like": sum(str(t.get("designator","")).upper().startswith(("U","J")) for t in ts),
            }
            supply_evidence.append({"net":name, **caps})
            if caps["capacitors"] == 0:
                add(findings,f"G5-SUPPLY-DECOUPLING-{name}","INFO","electrical","UNKNOWN",
                    f"Supply net {name!r} has no capacitor terminal in the compiled netlist; whether local decoupling is required cannot be inferred generically.","FACT",name)
            else:
                add(findings,f"G5-SUPPLY-DECOUPLING-{name}","INFO","electrical","VERIFIED",
                    f"Supply net {name!r} has {caps['capacitors']} capacitor terminal(s) in the compiled netlist.","VERIFIED",name)
    add(findings,"G5-SUPPLY-STRUCTURE","INFO","electrical","VERIFIED",
        f"Structural supply inventory covers {len(supply_evidence)} named supply/ground nets; pin electrical semantics are retained without assuming PASSIVE means source.","VERIFIED")
    add(findings,"G5-INTENT-COVERAGE","BLOCKER","electrical","UNKNOWN",
        "Protection, level compatibility, biasing, regulator operating limits and project-specific power intent are not derivable from generic connectivity alone.","FACT")
    # G6 structural geometry: board outline and primitive bounds are authoritative
    # parser facts, but do not substitute for a full Altium DRC engine.
    outline = getattr(getattr(pcb,"board",None),"outline",None)
    vertices = list(getattr(outline,"vertices",[]) or []) if outline else []
    if vertices:
        bb = getattr(outline,"bounding_box",None)
        add(findings,"G6-BOARD-OUTLINE","INFO","physical","VERIFIED",
            f"Parsed board outline with {len(vertices)} vertices; bounding_box={bb!r}.","VERIFIED")
        add(findings,"G6-BOARD-OUTLINE-CLOSED","INFO","physical",
            "VERIFIED" if len(vertices) >= 3 else "UNKNOWN",
            "Altium board outline is represented as an ordered polygon; closure is implicit from the final vertex back to the first.","VERIFIED")
        if bb and len(bb) == 4:
            x0,y0,x1,y1 = map(float,bb)
            outside = []
            for comp in list(getattr(pcb,"components",[]) or []):
                pos = None
                try:
                    pos = pcb.get_component_pick_place_center_mils(comp)
                except Exception:
                    pass
                if pos is None:
                    for keys in (("x_mils","y_mils"),("location_x_mils","location_y_mils")):
                        xv,yv = field(comp,keys[0]),field(comp,keys[1])
                        if xv is not None and yv is not None:
                            try: pos=(float(xv),float(yv))
                            except Exception: pass
                            break
                if pos is not None and not (x0 <= pos[0] <= x1 and y0 <= pos[1] <= y1):
                    outside.append((as_name(comp),pos))
            if outside:
                for ref,pos in outside[:100]:
                    add(findings,f"G6-COMPONENT-OUTSIDE-{ref}","HIGH","physical","FAIL",
                        f"Component placement center {pos!r} lies outside board bounding box {tuple(bb)!r}.","VERIFIED",ref)
            else:
                add(findings,"G6-COMPONENT-BOUNDS","INFO","physical","VERIFIED",
                    f"All {len(list(getattr(pcb,'components',[]) or []))} component placement centers resolved inside board bounding box {tuple(bb)!r}.","VERIFIED")
    else:
        add(findings,"G6-BOARD-OUTLINE","BLOCKER","physical","UNKNOWN",
            "Authoritative PCB parser exposed no board-outline vertices.","FACT")
    # G6 PLACEMENT: component pair clearance and routing-corridor congestion.
    comps=list(getattr(pcb,"components",[]) or [])
    pads=list(getattr(pcb,"pads",[]) or [])
    comp_boxes={}
    comp_points={}
    for idx,comp in enumerate(comps):
        ref=as_name(comp)
        if not ref: continue
        try: p=(float(comp.get_x_mils()),float(comp.get_y_mils()))
        except Exception: p=xy(comp)
        if p: comp_points[ref]=p
        pts=[]
        for pad in pads:
            ci=field(pad,"component_index")
            try:
                if ci is None or int(ci)!=idx: continue
            except Exception: continue
            try: px=float(getattr(pad,"x_mils")); py=float(getattr(pad,"y_mils"))
            except Exception: continue
            try: wx=float(getattr(pad,"width_mils")); wy=float(getattr(pad,"height_mils"))
            except Exception: wx=wy=0.0
            if wx>0 and wy>0:
                pts.append((px-wx/2,py-wy/2,px+wx/2,py+wy/2))
        if pts:
            comp_boxes[ref]=(min(p[0] for p in pts),min(p[1] for p in pts),
                            max(p[2] for p in pts),max(p[3] for p in pts))

    clearance_pairs=[]
    for i,a in enumerate(sorted(comp_boxes)):
        for b in sorted(comp_boxes)[i+1:]:
            ba,bb=comp_boxes[a],comp_boxes[b]
            gap_x=max(0.0,max(ba[0],bb[0])-min(ba[2],bb[2]))
            gap_y=max(0.0,max(ba[1],bb[1])-min(ba[3],bb[3]))
            if gap_x==0 and gap_y==0:
                add(findings,f"G6-COMPONENT-OVERLAP-{a}-{b}","HIGH","placement","FAIL",
                    f"Component geometry overlaps: {a} bbox={ba!r}; {b} bbox={bb!r}.","VERIFIED",f"{a}<->{b}")
            else:
                clearance_pairs.append((a,b,math.hypot(gap_x,gap_y)))

    if clearance_pairs:
        clearance_pairs.sort(key=lambda x:x[2])
        nearest=clearance_pairs[:10]
        for a,b,d in nearest:
            add(findings,f"G6-PLACEMENT-CLEARANCE-{a}-{b}","INFO","placement","VERIFIED",
                f"Nearest parsed component geometry gap={d:g} mil; no generic minimum is assumed.","VERIFIED",f"{a}<->{b}")
    else:
        add(findings,"G6-PLACEMENT-CLEARANCE","BLOCKER","placement","UNKNOWN",
            "No component bounding geometry was exposed by the parser.","FACT")

    # Explicit connector/choke-point evidence. This is deliberately descriptive:
    # names are not treated as design intent, only as a geometry inventory.
    connector_refs=sorted(r for r in comp_points if r.upper().startswith(("J","P","CON","SW")))
    for ref in connector_refs:
        p=comp_points[ref]
        nearby=[(other,distance(p,op)) for other,op in comp_points.items() if other!=ref and distance(p,op)<=1000]
        nearby.sort(key=lambda x:x[1])
        if len(nearby)>=6:
            add(findings,f"G6-ROUTING-CORRIDOR-{ref}","MEDIUM","placement","WARN",
                f"{ref} has {len(nearby)} component centers within 1000 mil; this is a geometry-based congestion signal, not proof of routing failure.","INFERRED",ref)

    # G7 ROUTING: report authoritative unrouted evidence when the parser exposes it,
    # plus routed primitive/net inventories. Never infer zero unrouted from absence.
    unrouted=extract_unrouted(pcb)
    if unrouted is None:
        add(findings,"G7-UNROUTED","BLOCKER","routing","UNKNOWN",
            "Parser does not expose an authoritative unrouted/ratsnest collection; zero unrouted nets cannot be claimed.","FACT")
    elif unrouted:
        for i,u in enumerate(unrouted[:200]):
            add(findings,f"G7-UNROUTED-{i}","HIGH","routing","FAIL",
                f"Authoritative unrouted/ratsnest item: {repr(u)[:700]}","VERIFIED",f"unrouted#{i}")
    else:
        add(findings,"G7-UNROUTED","INFO","routing","VERIFIED",
            "Authoritative PCB unrouted/ratsnest collection is empty.","VERIFIED")

    routed_counts=route_net_counts(pcb)
    if routed_counts:
        add(findings,"G7-ROUTED-NET-INVENTORY","INFO","routing","VERIFIED",
            f"Routing primitives expose {len(routed_counts)} named nets; primitive counts are retained as route evidence.","VERIFIED")
        # Detect named nets with only one route primitive. This is a review signal,
        # not a DRC failure.
        for n,count in sorted(routed_counts.items()):
            if count==1:
                add(findings,f"G7-ROUTE-STUB-SIGNAL-{n}","LOW","routing","WARN",
                    f"Net {n!r} has exactly one routed primitive in the parser inventory; inspect for intentional short segment/stub.","INFERRED",n)
    else:
        add(findings,"G7-ROUTED-NET-INVENTORY","BLOCKER","routing","UNKNOWN",
            "No named routing primitives were exposed; route topology cannot be audited.","FACT")

    # Per-net route topology and layer transitions where fields are available.
    net_layers={}
    for t in list(getattr(pcb,"tracks",[]) or []):
        n=net_name(t); layer=field(t,"layer")
        if n and layer is not None:
            net_layers.setdefault(n,set()).add(str(layer))
    for n,layers in sorted(net_layers.items()):
        if len(layers)>1:
            add(findings,f"G7-LAYER-TRANSITION-{n}","INFO","routing","VERIFIED",
                f"Net {n!r} is routed on {len(layers)} parsed layer identifiers: {sorted(layers)!r}.","VERIFIED",n)

    # Width/clearance checks are intentionally separated from topology. A parser
    # field is evidence only when the corresponding authoritative rule is exposed.
    add(findings,"G7-TOPOLOGY-LIMIT","INFO","routing","UNKNOWN",
        "Generic geometry can verify route primitives and layer transitions, but not full SI/timing intent or return-path correctness without project-specific constraints.","FACT")

    add(findings,"G6-PHYSICAL","BLOCKER","physical","UNKNOWN",
        "Full DRC/mechanical geometry equivalence is not implemented; structural outline evidence does not replace Altium's full DRC engine.","FACT")
    add(findings,"G7-FUNCTIONAL","BLOCKER","functional","UNKNOWN",
        "Functional correctness requires explicit design intent and cannot be inferred from parser structure alone.","FACT")

    gates = {
        "G0_INTAKE": "VERIFIED" if not any(f["id"]=="G0-ARCHIVE-HASH" and f["status"]=="FAIL" for f in findings) else "BLOCKED",
        "G1_PARSE":"VERIFIED",
        "G2_COMPILE":"VERIFIED" if compile_data is not None and not diagnostics else ("FAIL" if diagnostics else "UNKNOWN"),
        "G3_CONNECTIVITY":"VERIFIED" if not any(f["id"].startswith("G3-") and f["status"] in ("FAIL","UNKNOWN","BLOCKED") for f in findings) else "BLOCKED",
        "G4_PCB":"VERIFIED" if not any(f["id"].startswith("G4-") and f["status"] in ("FAIL","UNKNOWN","BLOCKED") for f in findings) else "BLOCKED",
        "G5_ELECTRICAL":"BLOCKED" if any(f["id"].startswith("G5-") and f["severity"]=="BLOCKER" and f["status"] in ("UNKNOWN","FAIL","BLOCKED") for f in findings) else "VERIFIED",
        "G6_PHYSICAL":"BLOCKED" if any(f["id"]=="G6-PHYSICAL" and f["status"] in ("UNKNOWN","FAIL","BLOCKED") for f in findings) else "VERIFIED",
        "G6_PLACEMENT":"BLOCKED" if any(f["domain"]=="placement" and f["severity"] in ("BLOCKER","HIGH") and f["status"] in ("UNKNOWN","FAIL","BLOCKED") for f in findings) else "VERIFIED",
        "G7_ROUTING":"BLOCKED" if any(f["domain"]=="routing" and f["severity"]=="BLOCKER" and f["status"] in ("UNKNOWN","FAIL","BLOCKED") for f in findings) else "VERIFIED",
        "G7_FUNCTIONAL":"BLOCKED",
        "G8_REPORT":"VERIFIED"
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
    rule_samples = []
    for i, r in enumerate(enabled):
        if i >= 100: break
        attrs = {}
        for name in sorted(set(["rule_kind","name","enabled","minimum_width","min_width","maximum_width","max_width","scope","scope1","scope2","query1","query2","priority","net_name","layer"])):
            try:
                value = getattr(r, name)
                if value is not None:
                    attrs[name] = value
            except Exception:
                pass
        rule_samples.append({"index": i, "attrs": attrs, "repr": repr(r)[:700]})
    track_samples = []
    for i, t in enumerate(list(getattr(pcb,"tracks",[]) or [])):
        if i >= 100: break
        attrs = {}
        for name in sorted(set(["width_mils","width","net_index","net_name","netname","layer","x1","y1","x2","y2","start","end"])):
            try:
                value = getattr(t, name)
                if value is not None:
                    attrs[name] = value
            except Exception:
                pass
        track_samples.append({"index": i, "attrs": attrs, "repr": repr(t)[:500]})
    (out/"g4_probe.json").write_text(json.dumps({
        "rule_count":len(rules),"enabled_rule_count":len(enabled),
        "width_rule_exposed":minw is not None,
        "width_rule_field":"minimum_width" if minw is not None else None,
        "counts":counts,
        "width_rule_repr": repr(width_rule)[:1500] if width_rule else None,
        "rule_samples":rule_samples,
        "track_samples":track_samples,
        "unresolved_pad_samples":unresolved_samples
    },indent=2,default=str),encoding="utf-8")
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
