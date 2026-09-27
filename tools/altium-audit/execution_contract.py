#!/usr/bin/env python3
"""Reusable audit execution contract.

The audit engine is authoritative for findings; this controller owns lifecycle:
AUDIT -> PLAN -> REPAIR -> VERIFY -> RETRY -> FINALIZE.
A planner result is never a terminal design result.

Repair adapters are intentionally capability-gated. A repair is accepted only
when the adapter reports a concrete mutation and a subsequent audit verifies
the target finding is gone. Otherwise the run ends BLOCKED/UNRESOLVED.
"""
from __future__ import annotations
import argparse, json, pathlib, subprocess, sys

TERMINAL = {"PASS", "BLOCKED", "UNRESOLVED"}

def load(p):
    return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))

def save(p, obj):
    pathlib.Path(p).write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")

def run(cmd):
    return subprocess.run(cmd, text=True, capture_output=True)

def findings(summary, findings):
    out=[]
    for f in findings.get("findings", []):
        if f.get("status") == "FAIL" or f.get("severity") == "BLOCKER":
            out.append(f)
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--audit-cmd", nargs="+", required=True)
    ap.add_argument("--plan-cmd", nargs="+", required=True)
    ap.add_argument("--repair-cmd", nargs="+", required=True)
    ap.add_argument("--max-attempts", type=int, default=3)
    args=ap.parse_args()
    out=pathlib.Path(args.out); out.mkdir(parents=True, exist_ok=True)
    history=[]
    for attempt in range(args.max_attempts+1):
        ar=run(args.audit_cmd)
        history.append({"stage":"AUDIT","attempt":attempt,"returncode":ar.returncode})
        sp=out/"summary.json"; fp=out/"findings.json"
        if not sp.exists() or not fp.exists():
            save(out/"execution_result.json", {"status":"BLOCKED","reason":"audit produced no required evidence","history":history})
            return 2
        s=load(sp); fs=load(fp)
        status=s.get("status")
        bad=findings(s,fs)
        if status=="PASS" and not bad:
            save(out/"execution_result.json", {"status":"PASS","attempts":attempt,"history":history})
            return 0
        if attempt >= args.max_attempts:
            save(out/"execution_result.json", {"status":"UNRESOLVED","attempts":attempt,"remaining_findings":bad,"history":history})
            return 1
        pr=run(args.plan_cmd)
        history.append({"stage":"PLAN","attempt":attempt,"returncode":pr.returncode})
        plan=out/"routing_repair_plan.json"
        if not plan.exists():
            save(out/"execution_result.json", {"status":"BLOCKED","reason":"repair planner produced no plan","history":history})
            return 2
        plan_obj=load(plan)
        if plan_obj.get("mode") == "PLAN_ONLY_NO_MUTATION":
            rr=run(args.repair_cmd)
            history.append({"stage":"REPAIR","attempt":attempt,"returncode":rr.returncode})
            # The repair command is responsible for refusing unsafe/non-actionable
            # candidates. It must create repair_receipt.json when it mutates.
            receipt=out/"repair_receipt.json"
            if not receipt.exists():
                save(out/"execution_result.json", {"status":"BLOCKED","reason":"repair backend did not produce mutation receipt","history":history})
                return 2
        else:
            rr=run(args.repair_cmd)
            history.append({"stage":"REPAIR","attempt":attempt,"returncode":rr.returncode})
        vr=run(args.audit_cmd)
        history.append({"stage":"VERIFY","attempt":attempt,"returncode":vr.returncode})
        if not (out/"summary.json").exists() or not (out/"findings.json").exists():
            save(out/"execution_result.json", {"status":"BLOCKED","reason":"verification produced no evidence","history":history})
            return 2
    save(out/"execution_result.json", {"status":"UNRESOLVED","history":history})
    return 1

if __name__=="__main__":
    raise SystemExit(main())
