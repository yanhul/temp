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
            try:
                raw=fn(side)
                if isinstance(raw,str) and "<svg" in raw[:2000]:
                    target=out/("surface_"+side_name.lower()+".svg")
                    target.write_text(raw)
                    meta["rendered"][target.name]={"bytes":target.stat().st_size,"via":"to_surface_svg","side":side_name}
            except Exception as e:
                meta.setdefault("errors",[]).append({"method":"to_surface_svg","side":side_name,"error":repr(e)})
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
    # Keepout-layer board boundary evidence: retain every candidate primitive, not only samples.
    def obj_dict(obj):
        row=summarize(obj)
        for key in ("start_x","start_y","end_x","end_y","x1","y1","x2","y2","layer","layer_token","is_keepout","is_board_cutout","outline_vertices","properties","width"):
            v=val(obj,key)
            if v is not None: row[key]=repr(v)[:3000]
        return row
    candidates=[]
    for key in ("tracks","arcs","regions","board_regions","shapebased_regions","dimensions"):
        try: items=list(getattr(pcb,key,[]) or [])
        except Exception: continue
        for item in items:
            attrs={}
            try: attrs=vars(item)
            except Exception: pass
            props=str(attrs.get("properties",""))
            layer=str(val(item,"layer","layer_token","dimension_layer_token") or "")
            keepout=bool(val(item,"is_keepout"))
            if keepout or "KEEPOUT" in (layer+" "+props).upper() or "BOARDREGION" in props.upper() or key=="dimensions":
                row=obj_dict(item); row["collection"]=key
                candidates.append(row)
    geometry["keepout_boundary_candidates"]={"count":len(candidates),"items":candidates}
    (out/"geometry-inventory.json").write_text(json.dumps(geometry,indent=2,default=str))
    meta["counts"]={k:len(val(pcb,k) or []) for k in ("components","pads","tracks","vias","arcs","regions","fills","texts","rules")}
    (out/"render-metadata.json").write_text(json.dumps(meta,indent=2,default=str))
    if not meta["rendered"]:
        raise SystemExit("RENDER_FAILED: no SVG emitted; inspect render-metadata.json")
    print(json.dumps({"RENDERED":meta["rendered"],"OUTLINE":meta["outline"],"COUNTS":meta["counts"]},indent=2,default=str))
if __name__=="__main__": main()
