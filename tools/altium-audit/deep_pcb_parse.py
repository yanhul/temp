#!/usr/bin/env python3
"""Manus-style deep PCB parse: inventory, normalized records, SVG previews, and evidence limits.

This is an inspection/export stage only. It never edits the source PcbDoc and never
claims DRC/routing closure from parser success.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, math
from collections import Counter
from pathlib import Path

try:
    from altium_monkey import AltiumPcbDoc
except Exception as exc:
    raise SystemExit(f"BLOCKED: cannot import altium_monkey: {exc}")

COLLECTIONS = (
    "components", "nets", "pads", "tracks", "arcs", "vias", "connections",
    "unrouted", "ratsnest", "rules", "classes", "polygons", "regions", "fills",
    "texts", "strings", "board_shapes", "keepouts", "component_bodies",
    "shapebased_component_bodies", "differential_pairs", "models", "rooms",
)

def get(obj, *names):
    if isinstance(obj, dict):
        for name in names:
            if obj.get(name) is not None: return obj[name]
    for name in names:
        try:
            value = getattr(obj, name)
            if callable(value): continue
            if value is not None: return value
        except Exception: pass
    return None

def num(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except Exception: return None

def xy(obj):
    for xk, yk in (("x_mils","y_mils"), ("location_x_mils","location_y_mils"),
                   ("x","y"), ("center_x_mils","center_y_mils")):
        x, y = num(get(obj,xk)), num(get(obj,yk))
        if x is not None and y is not None:
            # Altium raw database coordinates sometimes leak through as 1e4 mils.
            if (abs(x) > 1e6 or abs(y) > 1e6) and xk in ("x","y"): x,y=x/10000,y/10000
            return [x,y]
    p = get(obj,"position","location","center","start")
    if isinstance(p,(tuple,list)) and len(p)>=2:
        x,y=num(p[0]),num(p[1])
        if x is not None and y is not None:return [x,y]
    if p is not None:
        x,y=num(get(p,"x","X")),num(get(p,"y","Y"))
        if x is not None and y is not None:return [x,y]
    return None

def endpoints(obj):
    for keys in (("x1","y1","x2","y2"), ("start_x_mils","start_y_mils","end_x_mils","end_y_mils")):
        vals=[num(get(obj,k)) for k in keys]
        if all(v is not None for v in vals): return [[vals[0],vals[1]],[vals[2],vals[3]]]
    a,b=get(obj,"start"),get(obj,"end")
    a,b=xy(a) if a is not None else None,xy(b) if b is not None else None
    return [a,b] if a is not None and b is not None else None

def scalar(value):
    if value is None or isinstance(value,(str,int,float,bool)): return value
    if isinstance(value,(tuple,list)): return [scalar(v) for v in value[:100]]
    if isinstance(value,dict): return {str(k):scalar(v) for k,v in list(value.items())[:100] if not str(k).startswith("_")}
    return str(value)[:300]

def obj_record(obj, index):
    attrs={}
    for name in (
        "name","designator","refdes","reference","value","comment","footprint","pattern",
        "library","x","y","x_mils","y_mils","rotation","rotation_degrees","side","layer",
        "layer_name","layer_id","net","net_name","netname","net_index","_net_index",
        "component_index","pad_number","number","pin","width","width_mils","diameter",
        "diameter_mils","hole_size","hole_size_mils","start","end","x1","y1","x2","y2",
        "bounding_box","bbox","bounds","outline_vertices","vertices","enabled","rule_kind",
    ):
        v=get(obj,name)
        if v is not None: attrs[name]=scalar(v)
    pos=xy(obj)
    ep=endpoints(obj)
    if pos is not None: attrs["normalized_xy_mils"]=pos
    if ep is not None: attrs["normalized_endpoints_mils"]=ep
    attrs["index"]=index
    attrs["object_type"]=type(obj).__name__
    return attrs

def safe_name(v):
    s=str(v or "UNKNOWN")
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)[:80]

def write_csv(path, rows):
    keys=sorted({k for row in rows for k in row})
    with path.open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=keys or ["empty"],extrasaction="ignore");w.writeheader()
        for row in rows:w.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in row.items()})

def render_svg(path, primitives, width=1600, height=1100):
    pts=[]
    for p in primitives:
        if p.get("xy"): pts.append(p["xy"])
        if p.get("endpoints"): pts.extend(p["endpoints"])
    if not pts:
        path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500"><text x="20" y="30">No normalized geometry exposed by parser</text></svg>',encoding="utf-8")
        return
    xs=[p[0] for p in pts];ys=[p[1] for p in pts]
    xmin,xmax=min(xs),max(xs);ymin,ymax=min(ys),max(ys)
    dx=max(xmax-xmin,1);dy=max(ymax-ymin,1);margin=35
    scale=min((width-2*margin)/dx,(height-2*margin)/dy)
    def xy_px(p):return (margin+(p[0]-xmin)*scale,height-margin-(p[1]-ymin)*scale)
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
           '<rect width="100%" height="100%" fill="#fff"/>',
           f'<text x="20" y="22" font-family="sans-serif" font-size="14">Parser geometry preview — {len(primitives)} objects; units assumed mils where exposed</text>']
    for p in primitives:
        if p.get("endpoints"):
            a,b=map(xy_px,p["endpoints"])
            parts.append(f'<line x1="{a[0]:.2f}" y1="{a[1]:.2f}" x2="{b[0]:.2f}" y2="{b[1]:.2f}" stroke="#2463a6" stroke-width="1.2"/>')
        elif p.get("xy"):
            x,y=xy_px(p["xy"])
            color="#267b48" if p["kind"]=="components" else "#b33" if p["kind"]=="pads" else "#555"
            r=4 if p["kind"]=="components" else 3 if p["kind"]=="pads" else 2
            parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{r}" fill="{color}"/>')
            if p.get("label"):
                parts.append(f'<text x="{x+5:.2f}" y="{y-4:.2f}" font-family="sans-serif" font-size="9" fill="#222">{p["label"]}</text>')
    parts.append('</svg>')
    path.write_text("\n".join(parts),encoding="utf-8")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--pcb",required=True,type=Path);ap.add_argument("--out",required=True,type=Path)
    a=ap.parse_args();src=a.pcb.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
    if not src.is_file():raise SystemExit(f"PCB not found: {src}")
    digest=hashlib.sha256(src.read_bytes()).hexdigest()
    pcb=AltiumPcbDoc.from_file(str(src))
    inventory={}; rows={}; api={}
    for name in COLLECTIONS:
        try:
            value=getattr(pcb,name,None)
            if callable(value): value=value()
            if value is None: continue
            items=list(value)
            inventory[name]={"count":len(items),"status":"EXPOSED"}
            rows[name]=[obj_record(o,i) for i,o in enumerate(items)]
        except Exception as exc:
            inventory[name]={"count":None,"status":"ERROR","error":str(exc)[:500]}
    for name in sorted(x for x in dir(pcb) if not x.startswith("_")):
        try:
            v=getattr(pcb,name)
            api[name]={"type":type(v).__name__,"callable":callable(v)}
        except Exception as exc:api[name]={"error":str(exc)[:200]}
    components=rows.get("components",[]);nets=rows.get("nets",[])
    write_csv(out/"components.csv",components);write_csv(out/"nets.csv",nets)
    for name,items in rows.items():
        with (out/f"{name}.jsonl").open("w",encoding="utf-8") as f:
            for item in items:f.write(json.dumps(item,ensure_ascii=False,default=str)+"\n")
    primitives=[]
    for kind in ("components","tracks","arcs","pads","vias","regions","polygons","fills","connections"):
        for row in rows.get(kind,[]):
            p={"kind":kind,"layer":row.get("layer_name",row.get("layer",row.get("layer_id"))),
               "net":row.get("net_name",row.get("netname",row.get("net_index")))}
            if kind=="components":
                p["label"]=str(row.get("designator") or row.get("refdes") or row.get("reference") or row.get("name") or "")
            if row.get("normalized_xy_mils"):p["xy"]=row["normalized_xy_mils"]
            if row.get("normalized_endpoints_mils"):p["endpoints"]=row["normalized_endpoints_mils"]
            if "xy" in p or "endpoints" in p:primitives.append(p)
    render_svg(out/"board-overview.svg",primitives)
    layers=sorted({safe_name(p.get("layer")) for p in primitives if p.get("layer") is not None})
    layer_dir=out/"layers"
    layer_dir.mkdir(parents=True,exist_ok=True)
    for layer in layers:
        render_svg(layer_dir/f"{layer}.svg",[p for p in primitives if safe_name(p.get("layer"))==layer])
    (out/"parser-object-api.json").write_text(json.dumps(api,indent=2,ensure_ascii=False),encoding="utf-8")
    summary={
      "schema":"altium-deep-parse/v1","status":"PARSED_WITH_LIMITS","source":{"path":src.name,"size_bytes":src.stat().st_size,"sha256":digest},
      "parser":"altium-monkey.AltiumPcbDoc","inventory":inventory,
      "component_count":len(components),"net_count":len(nets),"geometry_record_count":len(primitives),
      "outputs":["components.csv","nets.csv","board-overview.svg","layers/","parser-object-api.json","<collection>.jsonl"],
      "evidence_limits":["A missing collection means the parser does not expose it; it does not prove zero objects.",
      "SVG is a geometry preview, not a fabrication drawing or DRC result.",
      "Unrouted count is authoritative only if the parser exposes an unrouted/ratsnest collection.",
      "No placement, connectivity, electrical, or manufacturing PASS is inferred from parser success."]
    }
    (out/"deep-parse-summary.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding="utf-8")
    report=["# Deep PCB Parse","",f"- Status: **{summary['status']}**",f"- Source SHA-256: `{digest}`",
            f"- Components: {len(components)}",f"- Nets: {len(nets)}",f"- Normalized geometry objects: {len(primitives)}","","## Parser inventory"]
    report += [f"- {k}: {v.get('count')} ({v.get('status')})" for k,v in inventory.items()]
    report += ["","## Evidence limits"]+[f"- {x}" for x in summary["evidence_limits"]]
    (out/"DEEP_PARSE_REPORT.md").write_text("\n".join(report)+"\n",encoding="utf-8")
    print(json.dumps({"status":summary["status"],"components":len(components),"nets":len(nets),"geometry":len(primitives),"output":str(out)},indent=2))
    return 0
if __name__=="__main__":raise SystemExit(main())
