#!/usr/bin/env python3
"""Render Altium PcbDoc geometry with altium-monkey; never mutates source."""
from __future__ import annotations
import argparse, inspect, json
from pathlib import Path
import altium_monkey
from altium_monkey import AltiumPcbDoc

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("pcb")
    ap.add_argument("--out",default="render/pcb")
    args=ap.parse_args()
    src=Path(args.pcb); out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
    pcb=AltiumPcbDoc.from_file(str(src))
    meta={"source":str(src),"source_bytes":src.stat().st_size,"source_sha256":None,"rendered":{},"methods":{}}
    import hashlib
    meta["source_sha256"]=hashlib.sha256(src.read_bytes()).hexdigest()
    for name in ("to_board_outline_svg","to_surface_svg","to_layer_svgs","to_svg"):
        fn=getattr(pcb,name,None)
        if not callable(fn): continue
        try: sig=str(inspect.signature(fn))
        except Exception: sig="unknown"
        meta["methods"][name]=sig
        attempts=[({},name+".svg")]
        attempts += [({"layer":"TOP"},name+"_top.svg"),({"side":"TOP"},name+"_top.svg"),({"surface":"TOP"},name+"_top.svg"),({"layer_name":"Top Layer"},name+"_top.svg")]
        for kwargs,filename in attempts:
            try:
                result=fn(**kwargs)
                if isinstance(result,dict):
                    for k,v in result.items():
                        if isinstance(v,(str,bytes)) and ("<svg" in (v.decode(errors="ignore") if isinstance(v,bytes) else v)[:500]):
                            target=out/(name+"_"+str(k).lower().replace(" ","_")+".svg")
                            target.write_bytes(v if isinstance(v,bytes) else v.encode())
                            meta["rendered"][target.name]={"bytes":target.stat().st_size,"via":name,"kwargs":kwargs}
                    if meta["rendered"]: break
                elif isinstance(result,(str,bytes)):
                    raw=result if isinstance(result,bytes) else result.encode()
                    if b"<svg" in raw[:2000]:
                        target=out/filename
                        target.write_bytes(raw)
                        meta["rendered"][target.name]={"bytes":target.stat().st_size,"via":name,"kwargs":kwargs}
                        break
            except TypeError:
                continue
            except Exception as e:
                meta.setdefault("errors",[]).append({"method":name,"kwargs":kwargs,"error":repr(e)})
        if name=="to_layer_svgs" and meta["rendered"]:
            break
    # Surface rendering requires the library's enum, not the literal string "TOP".
    enum_cls=getattr(altium_monkey,"PCB_SurfaceSide",None)
    if enum_cls is None:
        try:
            import pkgutil, importlib
            for info in pkgutil.walk_packages(altium_monkey.__path__, altium_monkey.__name__ + "."):
                try:
                    mod=importlib.import_module(info.name)
                    enum_cls=getattr(mod,"PCB_SurfaceSide",None)
                    if enum_cls is not None:
                        break
                except Exception:
                    continue
        except Exception:
            pass
    fn=getattr(pcb,"to_surface_svg",None)
    if enum_cls is not None and callable(fn):
        for side_name in ("TOP","BOTTOM"):
            side=getattr(enum_cls,side_name,None)
            if side is None:
                continue
            # The library may index role colors for absent surface roles and raise
            # KeyError((side, role)); omit absent roles first, then try explicit role order.
            attempts_surface = [
                ((), {"include_missing_roles": False}),
                ((), {"include_missing_roles": False, "role_order": list(getattr(altium_monkey, "PCB_SurfaceRole", []))}),
                ((), {}),
            ]
            last_error = None
            for positional, kw in attempts_surface:
                try:
                    raw=fn(side, *positional, **kw)
                    if isinstance(raw,str) and "<svg" in raw[:2000]:
                        target=out/("surface_"+side_name.lower()+".svg")
                        target.write_text(raw)
                        meta["rendered"][target.name]={"bytes":target.stat().st_size,"via":"to_surface_svg","side":side_name,"kwargs":kw}
                        last_error = None
                        break
                except Exception as e:
                    last_error = e
            if last_error is not None:
                meta.setdefault("errors",[]).append({"method":"to_surface_svg","side":side_name,"error":repr(last_error)})
    # Extract the authoritative rectangular board boundary from the rendered Keep-Out layer.
    # Altium's parsed BoardOutline can be a stale/default rectangle; do not silently substitute it.
    import re
    keepout_path = out / "to_layer_svgs_keepout.svg"
    boundary = {"status": "BLOCKED", "method": "Keep-Out layer magenta track primitives", "lines": []}
    if keepout_path.exists():
        svg = keepout_path.read_text(errors="replace")
        for m in re.finditer(r'<line\b[^>]*>', svg, re.I):
            tag = m.group(0)
            if not re.search(r'stroke=["\\']#FF00FF["\\']', tag, re.I):
                continue
            if not re.search(r'data-layer-name=["\\'](?:KEEPOUT|KEEP-OUT LAYER)["\\']', tag, re.I):
                continue
            vals = {}
            for key in ("x1", "y1", "x2", "y2"):
                mm = re.search(r'\b' + key + r'=["\\']([-+0-9.eE]+)["\\']', tag)
                if mm: vals[key] = float(mm.group(1))
            if len(vals) == 4:
                boundary["lines"].append(vals)
        xs = [v[k] for v in boundary["lines"] for k in ("x1", "x2")]
        ys = [v[k] for v in boundary["lines"] for k in ("y1", "y2")]
        # Require exactly four axis-aligned edges spanning the same bbox before declaring a rectangle.
        if len(boundary["lines"]) == 4 and len(xs) == 8 and len(ys) == 8:
            min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
            edges = set()
            for v in boundary["lines"]:
                if abs(v["x1"] - v["x2"]) < 1e-6:
                    edges.add(("v", round(v["x1"], 4), round(min(v["y1"], v["y2"]), 4), round(max(v["y1"], v["y2"]), 4)))
                elif abs(v["y1"] - v["y2"]) < 1e-6:
                    edges.add(("h", round(v["y1"], 4), round(min(v["x1"], v["x2"]), 4), round(max(v["x1"], v["x2"]), 4)))
            expected = {("v", round(min_x,4), round(min_y,4), round(max_y,4)), ("v", round(max_x,4), round(min_y,4), round(max_y,4)), ("h", round(min_y,4), round(min_x,4), round(max_x,4)), ("h", round(max_y,4), round(min_x,4), round(max_x,4))}
            if edges == expected:
                boundary.update({"status":"VERIFIED", "bbox_mm":{"min_x":min_x,"max_x":max_x,"min_y":min_y,"max_y":max_y}, "size_mm":{"width":round(max_x-min_x,4),"height":round(max_y-min_y,4)}})
    meta["keepout_board_boundary"] = boundary
    # Suppress exploratory string-enum KeyErrors when enum-based fallback succeeded.
    successful_sides = {v.get("side") for k,v in meta["rendered"].items() if k.startswith("surface_")}
    if successful_sides:
        meta["errors"] = [e for e in meta.get("errors", []) if not (e.get("method") == "to_surface_svg" and e.get("kwargs", {}).get("side") in successful_sides)]
        if not meta["errors"]: meta.pop("errors", None)

    # Save introspection and board outline evidence even if rendering API differs.
    board=getattr(pcb,"board",None)
    outline=getattr(board,"outline",None) if board is not None else None
    def val(obj,*keys):
        for k in keys:
            try:
                x=getattr(obj,k)
                if x is not None:return x
            except Exception:pass
        return None
    meta["outline"]={k:val(outline,*aliases) for k,aliases in {
      "bounding_box":["bounding_box","bbox","bounds"],
      "vertices":["vertices","points","outline_vertices","coordinates"],
      "width":["width","width_mils"],"height":["height","height_mils"]
    }.items()} if outline is not None else None
    def summarize(obj):
        row={"type":type(obj).__name__,"repr":repr(obj)[:1200]}
        try:
            row["attrs"]={k:repr(v)[:500] for k,v in vars(obj).items() if not k.startswith("_")}
        except Exception:
            pass
        for key in ("name","layer","layer_name","kind","is_board_outline","is_keepout","bounding_box","bbox","bounds","vertices","points","x_mils","y_mils","width_mils","height_mils","net_name","designator","component"):
            v=val(obj,key)
            if v is not None: row[key]=repr(v)[:1000]
        return row
    geometry={}
    for key in ("board_regions","regions","shapebased_regions","component_bodies","shapebased_component_bodies","keepout_regions","polygons","dimensions","tracks","arcs"):
        try:
            items=list(getattr(pcb,key,[]) or [])
            geometry[key]={"count":len(items),"samples":[summarize(x) for x in items[:12]]}
        except Exception as e:
            geometry[key]={"error":repr(e)}
    # Full geometry inventory for a reproducible second-pass audit. Preserve numeric
    # layer identifiers and raw coordinates; layer labels alone are not authoritative.
    def obj_dict(obj):
        row=summarize(obj)
        try:
            attrs=vars(obj)
            row["raw_layer_fields"]={k:repr(v)[:1000] for k,v in attrs.items() if "layer" in k.lower() or "keepout" in k.lower() or "outline" in k.lower()}
        except Exception: pass
        for key in ("start_x","start_y","end_x","end_y","x1","y1","x2","y2","layer","layer_token","is_keepout","is_board_cutout","outline_vertices","properties","width","v7_layer_id","keepout_restrictions"):
            v=val(obj,key)
            if v is not None: row[key]=repr(v)[:3000]
        return row
    candidates=[]
    for key in ("tracks","arcs","regions","board_regions","shapebased_regions","dimensions"):
        try: items=list(getattr(pcb,key,[]) or [])
        except Exception: continue
        for index,item in enumerate(items):
            row=obj_dict(item); row["collection"]=key; row["index"]=index
            candidates.append(row)
    geometry["full_geometry_candidates"]={"count":len(candidates),"items":candidates}
    (out/"geometry-inventory.json").write_text(json.dumps(geometry,indent=2,default=str))
    meta["counts"]={k:len(val(pcb,k) or []) for k in ("components","pads","tracks","vias","arcs","regions","fills","texts","rules")}
    (out/"render-metadata.json").write_text(json.dumps(meta,indent=2,default=str))
    if not meta["rendered"]:
        raise SystemExit("RENDER_FAILED: no SVG emitted; inspect render-metadata.json")
    print(json.dumps({"RENDERED":meta["rendered"],"OUTLINE":meta["outline"],"COUNTS":meta["counts"]},indent=2,default=str))
if __name__=="__main__": main()
