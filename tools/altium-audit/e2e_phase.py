#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
RUNNER=HERE/"audit_runner.py"
PLANNER=HERE/"placement_routing_plan.py"
KIT=HERE/"audit_kit.py"
def run(c): return subprocess.run([sys.executable,*map(str,c)],text=True).returncode
def discover(root):
 s=sorted(root.rglob("*.SchDoc")); b=sorted(root.rglob("*.PcbDoc")); p=sorted(root.rglob("*.PrjPcb"))
 if len(s)!=1 or len(b)!=1 or len(p)>1: raise RuntimeError(f"input contract: SchDoc={len(s)} PcbDoc={len(b)} PrjPcb={len(p)}")
 return s[0],b[0],p[0] if p else None
def audit(root,out,cfg):
 out.mkdir(parents=True,exist_ok=True); c=[RUNNER,"--root",root,"--out",out]
 if cfg:c+=["--config",cfg]
 rc=run(c); f=out/"summary.json"
 return rc,json.loads(f.read_text()) if f.exists() else {}
def receipt(out,phase,status,evidence,up=None):
 r={"schema":"altium-audit-e2e-phase/v1","phase":phase,"status":status,"evidence":evidence,"upstream_receipt_sha256":up}
 (out/"phase_receipt.json").write_text(json.dumps(r,indent=2,ensure_ascii=False)); print(json.dumps(r,indent=2)); return 0 if status=="PASS" else 1
def main():
 ap=argparse.ArgumentParser(); ap.add_argument("--phase",choices=["schematic","placement","routing"],required=True); ap.add_argument("--input",type=Path,required=True); ap.add_argument("--output",type=Path,required=True); ap.add_argument("--config",type=Path); ap.add_argument("--upstream-receipt",type=Path); a=ap.parse_args()
 root=a.input.resolve(); out=a.output.resolve(); s,b,p=discover(root); out.mkdir(parents=True,exist_ok=True)
 up=hashlib.sha256(a.upstream_receipt.read_bytes()).hexdigest() if a.upstream_receipt and a.upstream_receipt.exists() else None
 if a.phase=="schematic":
  rc,x=audit(root,out/"audit",a.config); g=x.get("gates",{}); req={k:g.get(k) for k in ["G0_INTAKE","G1_PARSE","G2_COMPILE","G3_CONNECTIVITY"]}; ok=all(v=="VERIFIED" for v in req.values())
  return receipt(out,"SCHEMATIC","PASS" if ok else "BLOCKED",{"runner_rc":rc,"required_gates":req,"finding_count":len(x.get("findings",[]))})
 if a.phase=="placement":
  rc,x=audit(root,out/"audit",a.config); g=x.get("gates",{}); pre=all(g.get(k)=="VERIFIED" for k in ["G0_INTAKE","G1_PARSE","G2_COMPILE","G3_CONNECTIVITY"])
  if not pre:return receipt(out,"PLACEMENT","BLOCKED",{"reason":"schematic prerequisite failed","runner_rc":rc,"gates":g},up)
  nl=json.loads((out/"audit"/"netlist.json").read_text()); m=out/"connectivity-manifest.json"; m.write_text(json.dumps({"schema":"altium-connectivity-manifest.v2","status":"VERIFIED","basis":"phase-1 G3_CONNECTIVITY","nets":nl.get("nets",[])} ,indent=2))
  intelligence=out/"connectivity-intelligence.json"; irc=run([HERE/"connectivity_intelligence.py","--netlist",out/"audit"/"netlist.json","--out",intelligence]);
  plan=out/"placement-routing-plan.json"; prc=run([PLANNER,"--pcb",b,"--out",plan,"--findings",out/"audit"/"findings.json","--connectivity-manifest",m]+(["--config",a.config] if a.config else [])); z=json.loads(plan.read_text()) if plan.exists() else {}; pl=z.get("placement",{}); ok=pl.get("status") in ("VERIFIED","PASS") and pl.get("lock",{}).get("status")=="LOCKED"
  return receipt(out,"PLACEMENT","PASS" if ok else "BLOCKED",{"planner_rc":prc,"connectivity_intelligence_rc":irc,"placement":pl,"routing":"DEFERRED"},up)
 cmd=[KIT,"--input",root,"--output",out/"kit","--repair","--max-retries","3"]+([ "--config",a.config] if a.config else []); rc=run(cmd); f=out/"kit"/"summary.json"; x=json.loads(f.read_text()) if f.exists() else {}; g=x.get("gates",{}); ok=x.get("status")=="PASS" and all(g.get(k)=="VERIFIED" for k in ["G3_CONNECTIVITY","G6_PLACEMENT","G7_ROUTING"])
 return receipt(out,"ROUTING","PASS" if ok else "BLOCKED",{"kit_rc":rc,"status":x.get("status"),"gates":g},up)
if __name__=="__main__": raise SystemExit(main())
