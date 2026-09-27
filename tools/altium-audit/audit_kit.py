#!/usr/bin/env python3
"""Single-entry reusable Altium Audit Kit.

Contract:
  audit_kit.py --input <folder> --output <folder> [--repair] [--config <json>]

The input folder contains exactly one *.SchDoc and one *.PcbDoc, plus optional
*.PrjPcb. Project-specific identifiers are discovered at runtime; no project
name/net/refdes/path is embedded in the engine.
"""
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
    if len(sch) != 1:
        raise RuntimeError(f"input contract requires exactly 1 SchDoc; found {len(sch)}")
    if len(pcb) != 1:
        raise RuntimeError(f"input contract requires exactly 1 PcbDoc; found {len(pcb)}")
    if len(prj) > 1:
        raise RuntimeError(f"input contract allows at most 1 PrjPcb; found {len(prj)}")
    return sch[0], pcb[0], prj[0] if prj else None

def run(cmd):
    p = subprocess.run([sys.executable, *map(str, cmd)], text=True)
    return p.returncode

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--repair", action="store_true")
    ap.add_argument("--config", type=Path)
    args = ap.parse_args()

    root = args.input.resolve()
    out = args.output.resolve()
    if not root.is_dir():
        raise SystemExit(f"input directory does not exist: {root}")
    out.mkdir(parents=True, exist_ok=True)

    sch, pcb, prj = discover(root)
    manifest = {
        "schema": "altium-audit-kit-run.v1",
        "input": {
            "directory": str(root),
            "schematic": sch.name,
            "pcb": pcb.name,
            "project": prj.name if prj else None,
        },
        "repair_requested": bool(args.repair),
    }
    (out / "intake.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    audit_out = out / "audit-initial"
    rc = run([RUNNER, "--root", root, "--out", audit_out] +
             ([ "--config", args.config.resolve() ] if args.config else []))
    if rc == 0 and not args.repair:
        shutil.copy2(audit_out / "summary.json", out / "summary.json")
        return 0

    if not args.repair:
        shutil.copy2(audit_out / "summary.json", out / "summary.json")
        return rc

    # Work only on a private copy. Never mutate the caller's source PcbDoc.
    work = out / "working"
    work.mkdir(exist_ok=True)
    work_pcb = work / pcb.name
    shutil.copy2(pcb, work_pcb)
    plan = out / "routing_repair_plan.json"
    rc_plan = run([PLAN, "--pcb", work_pcb, "--out", plan])
    if rc_plan != 0:
        return rc_plan

    authorized = run([
        AUTHORIZE, "--pcb", work_pcb, "--plan", plan,
        "--findings", audit_out / "findings.json",
        "--probe", audit_out / "g4_probe.json",
    ])
    if authorized != 0:
        shutil.copy2(audit_out / "summary.json", out / "summary.json")
        return 1

    repaired_pcb = work / ("repaired_" + pcb.name)
    receipt = out / "repair_receipt.json"
    applied = run([APPLY, "--pcb", work_pcb, "--plan", plan,
                   "--out", repaired_pcb, "--receipt", receipt])
    if applied != 0:
        shutil.copy2(audit_out / "summary.json", out / "summary.json")
        return 1

    # Verify the mutated working copy with the same kit runner.
    verify_root = out / "verify-input"
    verify_root.mkdir(exist_ok=True)
    shutil.copy2(sch, verify_root / sch.name)
    shutil.copy2(repaired_pcb, verify_root / pcb.name)
    if prj:
        shutil.copy2(prj, verify_root / prj.name)
    verify_out = out / "audit-verify"
    rc_verify = run([RUNNER, "--root", verify_root, "--out", verify_out] +
                    ([ "--config", args.config.resolve() ] if args.config else []))

    summary = json.loads((verify_out / "summary.json").read_text(encoding="utf-8"))
    summary["repair"] = json.loads(receipt.read_text(encoding="utf-8"))
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False),
                                      encoding="utf-8")
    return rc_verify

if __name__ == "__main__":
    raise SystemExit(main())
