#!/usr/bin/env python3
"""Single-entry reusable Altium Audit Kit: intake -> audit -> plan -> authorize -> apply -> verify -> retry."""
from __future__ import annotations
import argparse,json,shutil,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent; RUNNER=HERE/"audit_runner.py"; PLAN=HERE/"routing_repair_plan.py"; AUTHORIZE=HERE/"routing_repair_authorize.py"; APPLY=HERE/"routing_repair_apply.py"
TERMINAL={"PASS","FAIL","BLOCKED","INCONCLUSIVE","UNKNOWN"}
def discover(root):
    sch=sorted(root.rglob("*.SchDoc")); pcb=sorted(root.rglob("*.PcbDoc")); prj=sorted(root.rglob("*.PrjPcb"))
    if len(sch)!=1: raise RuntimeError(f"input contract requires exactly 1 SchDoc; found {len(sch)}")
    if len(pcb)!=1: raise RuntimeError(f"input contract requires exactly 1 PcbDoc; found {len(pcb)}")
    if len(prj)>1: raise RuntimeError(f"input contract allows at most 1 PrjPcb; found {len(prj)}")
    return sch[0],pcb[0],prj[0] if prj else None
def run(cmd): return subprocess.run([sys.executable,*map(str,cmd)],text=True).returncode
def audit(root,out,config=None):
    cmd=[RUNNER,"--root",root,"--out",out]
    if config: cmd+=["--config",config.resolve()]
    rc=run(cmd); return rc,json.loads((out/"summary.json").read_text()) if (out/"summary.json").exists() else None
def write_terminal(out,r):
    r["status"]=r.get("status","UNKNOWN"); r["status"]=r["status"] if r["status"] in TERMINAL else "UNKNOWN"; r["terminal_status"]=r["status"]; r["schema"]="altium-audit-kit-result.v4"
    (out/"summary.json").write_text(json.dumps(r,indent=2,ensure_ascii=False))
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--input",required=True,type=Path); ap.add_argument("--output",required=True,type=Path); ap.add_argument("--repair",action="store_true"); ap.add_argument("--max-retries",type=int,default=3); ap.add_argument("--config",type=Path); a=ap.parse_args()
    root,out=a.input.resolve(),a.output.resolve()
    if not root.is_dir(): raise SystemExit(f"input directory does not exist: {root}")
    out.mkdir(parents=True,exist_ok=True); sch,pcb,prj=discover(root)
    (out/"intake.json").write_text(json.dumps({"schema":"altium-audit-kit-run.v4","input":{"directory":str(root),"schematic":sch.name,"pcb":pcb.name,"project":prj.name if prj else None},"repair_requested":a.repair,"max_retries":a.max_retries},indent=2))
    audit_out=out/"audit-initial"; _,initial=audit(root,audit_out,a.config)
    if initial is None: write_terminal(out,{"status":"BLOCKED","reason":"audit runner produced no summary.json"}); return 2
    fallback=False; blocker=None
    if prj and initial.get("gates",{}).get("G1_PARSE")=="UNKNOWN":
        dr=out/"direct-input"; dr.mkdir(exist_ok=True); shutil.copy2(sch,dr/sch.name); shutil.copy2(pcb,dr/pcb.name); do=out/"audit-direct-fallback"; _,direct=audit(dr,do,a.config)
        if direct is not None:
            blocker={"id":"G2-PROJECT-COMPILE","severity":"BLOCKER","domain":"compile","status":"BLOCKED","object":prj.name,"evidence":"Project compile failed; structural SCH+PCB audit continued directly.","confidence":"FACT"}
            direct.setdefault("findings",[]).append(blocker); direct.setdefault("gates",{})["G2_COMPILE"]="BLOCKED"; direct["status"]="BLOCKED"; direct["project_compile_fallback"]=True; initial=direct; fallback=True
    pp=out/"placement-routing-plan.json"; run([HERE/"placement_routing_plan.py","--pcb",pcb,"--out",pp])
    planning=json.loads(pp.read_text()) if pp.exists() else {"design_status":"BLOCKED","placement":{"status":"UNKNOWN"},"routing":{"status":"UNKNOWN"}}
    initial["kit"]={"status":"PASS","schema":"altium-audit-kit/v4"}; initial["planning"]=planning; initial["design_status"]=planning.get("design_status","BLOCKED")
    if fallback: initial.setdefault("findings",[]).append(blocker); initial.setdefault("gates",{})["G2_COMPILE"]="BLOCKED"
    if initial["design_status"]!="PASS":
        initial["status"]="BLOCKED"; initial["terminal_reason"]="placement or topology unresolved; no mutation authorized"; write_terminal(out,initial); return 1
    if not a.repair: write_terminal(out,initial); return 0 if initial.get("status")=="PASS" else 1
    work=out/"working"; work.mkdir(exist_ok=True); workpcb=work/pcb.name; shutil.copy2(pcb,workpcb); source=out/("audit-direct-fallback" if fallback else "audit-initial"); history=[]
    for attempt in range(a.max_retries+1):
        ad=out/f"attempt-{attempt}"; ad.mkdir(exist_ok=True); plan=ad/"routing_repair_plan.json"
        if run([PLAN,"--pcb",workpcb,"--out",plan])!=0: initial["status"]="BLOCKED"; initial["terminal_reason"]="routing plan unavailable"; initial["repair_history"]=history; write_terminal(out,initial); return 1
        ar=run([AUTHORIZE,"--pcb",workpcb,"--plan",plan,"--findings",source/"findings.json","--probe",source/"g4_probe.json"]); p=json.loads(plan.read_text())
        history.append({"attempt":attempt,"stage":"AUTHORIZE","returncode":ar,"authorization":p.get("authorization")})
        if ar!=0 or p.get("mutation_authorized") is not True: initial["status"]="BLOCKED"; initial["terminal_reason"]="no independently authorized routing mutation"; initial["repair_history"]=history; write_terminal(out,initial); return 1
        repaired=work/f"repaired-{attempt}-{pcb.name}"; receipt=ad/"repair_receipt.json"; rr=run([APPLY,"--pcb",workpcb,"--plan",plan,"--out",repaired,"--receipt",receipt])
        if rr!=0 or not receipt.exists(): initial["status"]="BLOCKED"; initial["terminal_reason"]="repair backend produced no safe mutation"; initial["repair_history"]=history; write_terminal(out,initial); return 1
        rec=json.loads(receipt.read_text()); history.append({"attempt":attempt,"stage":"APPLY","returncode":rr,"receipt":rec})
        if rec.get("status")!="MUTATED" or not repaired.exists(): initial["status"]="BLOCKED"; initial["terminal_reason"]="mutation receipt invalid"; initial["repair_history"]=history; write_terminal(out,initial); return 1
        vrroot=ad/"verify-input"; vrroot.mkdir(exist_ok=True); shutil.copy2(sch,vrroot/sch.name); shutil.copy2(repaired,vrroot/pcb.name)
        if prj and not fallback: shutil.copy2(prj,vrroot/prj.name)
        vo=ad/"audit-verify"; vrc,final=audit(vrroot,vo,a.config)
        vp=ad/"placement-routing-verify.json"; prc=run([HERE/"placement_routing_plan.py","--pcb",repaired,"--out",vp]); vpdata=json.loads(vp.read_text()) if vp.exists() else {}
        history.append({"attempt":attempt,"stage":"VERIFY","returncode":vrc,"planner_returncode":prc,"design_status":vpdata.get("design_status"),"status":final.get("status") if final else None})
        if final is not None:
            final["repair"]=rec; final["repair_history"]=history; final["planning"]=vpdata
            if fallback: final.setdefault("findings",[]).append(blocker); final.setdefault("gates",{})["G2_COMPILE"]="BLOCKED"; final["project_compile_fallback"]=True
            if final.get("status")=="PASS" and vpdata.get("design_status")=="PASS": write_terminal(out,final); return 0
            if attempt>=a.max_retries: final["status"]="INCONCLUSIVE" if vrc==0 else "FAIL"; final["terminal_reason"]="verification did not reach PASS within retry budget"; write_terminal(out,final); return 1
        else:
            if attempt>=a.max_retries: initial["status"]="INCONCLUSIVE"; initial["terminal_reason"]="verification evidence missing"; initial["repair_history"]=history; write_terminal(out,initial); return 1
        shutil.copy2(repaired,workpcb)
    return 1
if __name__=="__main__": raise SystemExit(main())
