#!/usr/bin/env python3
"""Single-entry reusable Altium Audit Kit."""
from __future__ import annotations
import argparse, json, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNNER = HERE / "audit_runner.py"
PLAN = HERE / "routing_repair_plan.py"
AUTHORIZE = HERE / "routing_repair_authorize.py"
APPLY = HERE / "routing_repair_apply.py"

def discover(root: Path):
    sch = sorted(root.rglob("*.SchDoc"))
    pcb = sorted(root.rglob("*.PcbDoc"))
    prj = sorted(root.rglob("*.PrjPcb"))
    if len(sch) != 1: raise RuntimeError(f"input contract requires exactly 1 SchDoc; found {len(sch)}")
    if len(pcb) != 1: raise RuntimeError(f"input contract requires exactly 1 PcbDoc; found {len(pcb)}")
    if len(prj) > 1: raise RuntimeError(f"input contract allows at most 1 PrjPcb; found {len(prj)}")
    return sch[0], pcb[0], prj[0] if prj else None

def run(cmd):
    return subprocess.run([sys.executable, *map(str, cmd)], text=True).returncode

def summary(path):
    return json.loads((path / "summary.json").read_text(encoding="utf-8"))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--repair", action="store_true")
    ap.add_argument("--config", type=Path)
    args = ap.parse_args()
    root, out = args.input.resolve(), args.output.resolve()
    if not root.is_dir(): raise SystemExit(f"input directory does not exist: {root}")
    out.mkdir(parents=True, exist_ok=True)
    sch, pcb, prj = discover(root)
    (out / "intake.json").write_text(json.dumps({
        "schema":"altium-audit-kit-run.v2",
        "input":{"directory":str(root),"schematic":sch.name,"pcb":pcb.name,"project":prj.name if prj else None},
        "repair_requested":bool(args.repair)}, indent=2), encoding="utf-8")

    audit_out = out / "audit-initial"
    rc = run([RUNNER,"--root",root,"--out",audit_out] +
             (["--config",str(args.config.resolve())] if args.config else []))
    initial = summary(audit_out) if (audit_out/"summary.json").exists() else None

    project_compile_fallback = False
    project_blocker = None

    # Preserve a project compile blocker, but continue the supplied SCH+PCB audit.
    if prj and initial and initial.get("gates",{}).get("G1_PARSE") == "UNKNOWN":
        direct_root = out / "direct-input"
        direct_root.mkdir(exist_ok=True)
        shutil.copy2(sch, direct_root/sch.name)
        shutil.copy2(pcb, direct_root/pcb.name)
        direct_out = out / "audit-direct-fallback"
        run([RUNNER,"--root",direct_root,"--out",direct_out] +
            (["--config",str(args.config.resolve())] if args.config else []))
        direct = summary(direct_out)
        project_blocker = {
            "id":"G2-PROJECT-COMPILE","severity":"BLOCKER","domain":"compile",
            "status":"BLOCKED","object":prj.name,
            "evidence":"Project compile failed for its referenced source set; structural SCH+PCB audit was executed directly instead.",
            "confidence":"FACT"}
        direct.setdefault("findings",[]).append(project_blocker)
        direct.setdefault("gates",{})["G2_COMPILE"]="BLOCKED"
        direct["status"]="BLOCKED"
        direct["project_compile_fallback"]=True
        initial = direct
        project_compile_fallback = True
        (out/"summary.json").write_text(json.dumps(direct,indent=2,ensure_ascii=False),encoding="utf-8")
    if initial is None: raise SystemExit("audit runner produced no summary.json")
    # Planning is always part of the reusable kit lifecycle. It is non-mutating
    # and deliberately independent from routing repair authorization.
    planning_out = out/"placement-routing-plan.json"
    run([HERE/"placement_routing_plan.py","--pcb",pcb,"--out",planning_out])
    planning = json.loads(planning_out.read_text(encoding="utf-8")) if planning_out.exists() else {
        "design_status":"BLOCKED","placement":{"status":"UNKNOWN"},"routing":{"status":"BLOCKED"}
    }
    initial["kit"] = {"status":"PASS","schema":"altium-audit-kit/v3"}
    initial["planning"] = planning
    initial["design_status"] = planning.get("design_status","BLOCKED")
    if initial["design_status"] != "PASS":
        initial["status"] = "BLOCKED"
    (out/"summary.json").write_text(json.dumps(initial,indent=2,ensure_ascii=False),encoding="utf-8")

    if not args.repair:
        return 0 if initial["design_status"]=="PASS" else 1
    audit_source_out = out/"audit-direct-fallback" if project_compile_fallback else audit_out
    if not (audit_source_out/"findings.json").exists() or not (audit_source_out/"g4_probe.json").exists():
        shutil.copy2(audit_source_out/"summary.json",out/"summary.json")
        return rc or 1

    work = out/"working"; work.mkdir(exist_ok=True)
    work_pcb = work/pcb.name; shutil.copy2(pcb,work_pcb)
    plan = out/"routing_repair_plan.json"
    if run([PLAN,"--pcb",work_pcb,"--out",plan]) != 0:
        shutil.copy2(audit_out/"summary.json",out/"summary.json"); return 1
    if run([AUTHORIZE,"--pcb",work_pcb,"--plan",plan,
            "--findings",audit_source_out/"findings.json","--probe",audit_source_out/"g4_probe.json"]) != 0:
        shutil.copy2(audit_out/"summary.json",out/"summary.json"); return 1

    repaired = work/("repaired_"+pcb.name); receipt=out/"repair_receipt.json"
    if run([APPLY,"--pcb",work_pcb,"--plan",plan,"--out",repaired,"--receipt",receipt]) != 0:
        shutil.copy2(audit_out/"summary.json",out/"summary.json"); return 1

    verify_root=out/"verify-input"; verify_root.mkdir(exist_ok=True)
    shutil.copy2(sch,verify_root/sch.name); shutil.copy2(repaired,verify_root/pcb.name)
    if prj and not project_compile_fallback: shutil.copy2(prj,verify_root/prj.name)
    verify_out=out/"audit-verify"
    rc_verify=run([RUNNER,"--root",verify_root,"--out",verify_out] +
                  (["--config",str(args.config.resolve())] if args.config else []))
    if not (verify_out/"summary.json").exists():
        shutil.copy2(audit_out/"summary.json",out/"summary.json"); return 1
    final=summary(verify_out)
    final["repair"]=json.loads(receipt.read_text(encoding="utf-8"))
    if project_compile_fallback and project_blocker:
        final.setdefault("findings",[]).append(project_blocker)
        final.setdefault("gates",{})["G2_COMPILE"]="BLOCKED"
        final["status"]="BLOCKED"
        final["project_compile_fallback"]=True
    (out/"summary.json").write_text(json.dumps(final,indent=2,ensure_ascii=False),encoding="utf-8")
    return rc_verify

if __name__=="__main__":
    raise SystemExit(main())
