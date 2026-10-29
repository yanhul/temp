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
    meta["counts"]={k:len(val(pcb,k) or []) for k in ("components","pads","tracks","vias","arcs","regions","fills","texts","rules")}
    (out/"render-metadata.json").write_text(json.dumps(meta,indent=2,default=str))
    if not meta["rendered"]:
        raise SystemExit("RENDER_FAILED: no SVG emitted; inspect render-metadata.json")
    print(json.dumps({"RENDERED":meta["rendered"],"OUTLINE":meta["outline"],"COUNTS":meta["counts"]},indent=2,default=str))
if __name__=="__main__": main()
