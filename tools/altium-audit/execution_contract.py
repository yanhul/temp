#!/usr/bin/env python3
"""Reusable audit execution contract: AUDIT -> PLAN -> AUTHORIZE -> REPAIR -> VERIFY -> RETRY -> FINALIZE."""
from __future__ import annotations
import argparse,json,pathlib,shutil,subprocess,shlex

def load(p): return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
def save(p,o): pathlib.Path(p).write_text(json.dumps(o,indent=2,sort_keys=True),encoding="utf-8")
def run(c):
    argv=shlex.split(c[0]) if len(c)==1 else c
    return subprocess.run(argv,text=True,capture_output=True)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--out",required=True); ap.add_argument("--max-attempts",type=int,default=3)
    ns,rest=ap.parse_known_args()
    def capture(flag,next_flags):
        if flag not in rest: raise SystemExit(f"missing {flag}")
        i=rest.index(flag)+1; j=i
        while j<len(rest) and rest[j] not in next_flags:j+=1
        if i==j: raise SystemExit(f"empty {flag}")
        return rest[i:j]
    audit_cmd=capture("--audit-cmd",{"--plan-cmd","--authorize-cmd","--repair-cmd"})
    plan_cmd=capture("--plan-cmd",{"--audit-cmd","--authorize-cmd","--repair-cmd"})
    auth_cmd=capture("--authorize-cmd",{"--audit-cmd","--plan-cmd","--repair-cmd"})
    repair_cmd=capture("--repair-cmd",{"--audit-cmd","--plan-cmd","--authorize-cmd"})
    out=pathlib.Path(ns.out); out.mkdir(parents=True,exist_ok=True); history=[]
    for attempt in range(ns.max_attempts+1):
        ar=run(audit_cmd); history.append({"stage":"AUDIT","attempt":attempt,"returncode":ar.returncode})
        sp,fp=out/"summary.json",out/"findings.json"
        if not sp.exists() or not fp.exists():
            save(out/"execution_result.json",{"status":"BLOCKED","reason":"audit evidence missing","history":history});return 2
        s,fs=load(sp),load(fp); items=fs if isinstance(fs,list) else fs.get("findings",[])
        bad=[f for f in items if f.get("status")=="FAIL" or f.get("severity")=="BLOCKER"]
        if s.get("status")=="PASS" and not bad:
            save(out/"execution_result.json",{"status":"PASS","attempts":attempt,"history":history});return 0
        if attempt>=ns.max_attempts:
            save(out/"execution_result.json",{"status":"UNRESOLVED","attempts":attempt,"remaining_findings":bad,"history":history});return 1
        pr=run(plan_cmd);history.append({"stage":"PLAN","attempt":attempt,"returncode":pr.returncode})
        au=run(auth_cmd);history.append({"stage":"AUTHORIZE","attempt":attempt,"returncode":au.returncode})
        try: plan=load(out/"routing_repair_plan.json")
        except Exception:
            save(out/"execution_result.json",{"status":"BLOCKED","reason":"routing authorization evidence missing","history":history});return 2
        if au.returncode!=0 or plan.get("mutation_authorized") is not True:
            save(out/"execution_result.json",{"status":"BLOCKED","reason":"no independently authorized routing mutation","authorization":plan.get("authorization"),"history":history});return 2
        receipt=out/"repair_receipt.json"
        if receipt.exists():receipt.unlink()
        rr=run(repair_cmd);history.append({"stage":"REPAIR","attempt":attempt,"returncode":rr.returncode})
        if not receipt.exists():
            save(out/"execution_result.json",{"status":"BLOCKED","reason":"repair backend produced no receipt","history":history});return 2
        rec=load(receipt)
        if rec.get("status")!="MUTATED":
            save(out/"execution_result.json",{"status":"BLOCKED","reason":"no safe mutation available","repair_receipt":rec,"history":history});return 2
        src=pathlib.Path(rec["source"]);dst=pathlib.Path(rec["output"])
        if not dst.exists():
            save(out/"execution_result.json",{"status":"BLOCKED","reason":"repair output missing","history":history});return 2
        shutil.copy2(dst,src)
        vr=run(audit_cmd);history.append({"stage":"VERIFY","attempt":attempt,"returncode":vr.returncode})
        if not (sp.exists() and fp.exists()):
            save(out/"execution_result.json",{"status":"BLOCKED","reason":"verification evidence missing","history":history});return 2
        s2,fs2=load(sp),load(fp);items2=fs2 if isinstance(fs2,list) else fs2.get("findings",[])
        bad2=[f for f in items2 if f.get("status")=="FAIL" or f.get("severity")=="BLOCKER"]
        history.append({"stage":"VERIFY_RESULT","attempt":attempt,"status":s2.get("status"),"remaining_findings":len(bad2)})
    save(out/"execution_result.json",{"status":"UNRESOLVED","history":history});return 1
if __name__=="__main__":raise SystemExit(main())
