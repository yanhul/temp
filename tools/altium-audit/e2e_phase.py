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
# Only the documented HCPL NC cases are deferred for this project's explicit
# policy. Identity contradictions for D5/D12/D13 are never exempted by footprint
# reuse; a footprint match is not evidence of electrical identity.
DEFERRED_NON_GATING_IDS = {"G2-SCH-NC-PIN-CONNECTED-U19","G2-HCPL-NC-PIN4-CONNECTED-U19","G2-SCH-NC-PIN-CONNECTED-U24","G2-HCPL-NC-PIN4-CONNECTED-U24","G2-SCH-NC-PIN-CONNECTED-U29","G2-HCPL-NC-PIN4-CONNECTED-U29"}

def required_schematic_unknowns(findings, block_unknown=True, require_schlib=False):
 if not block_unknown:
  return []
 return [
  f for f in findings
  if f.get("domain")=="schematic"
  and f.get("status")=="UNKNOWN"
  and f.get("id") not in DEFERRED_NON_GATING_IDS
  # Source SchLib checks are optional enrichment by default; only become a
  # required schematic check when the project explicitly opts in.
  and not (str(f.get("id","")).startswith("G2-SCHLIB-") and not require_schlib)
 ]

def classify_identity_finding(f):
 """Separate evidence gaps from missing reference profiles and verified conflicts.

 This is diagnostic classification only; it never changes gate status.
 """
 fid=str(f.get("id",""))
 status=str(f.get("status","")).upper()
 evidence=str(f.get("evidence","") or f.get("message","") or "")
 if fid.startswith("G2-SCH-IDENTITY-EVIDENCE-") and status=="FAIL":
  return "verified_identity_contradiction"
 if fid.startswith("G2-SCH-IDENTITY-UNRESOLVED-"):
  msg=evidence.lower()
  if "lack an authoritative pin fingerprint" in msg or "authoritative pin fingerprint" in msg:
   return "reference_profile_missing"
  if "no observed pin-function evidence" in msg or "missing" in msg and ("pin" in msg or "evidence" in msg):
   return "parser_evidence_missing"
  return "insufficient_discriminating_evidence"
 if status=="UNKNOWN" and f.get("domain") in {"schematic","compile","connectivity","parse"}:
  msg=evidence.lower()
  if any(k in msg for k in ("parser omitted","not parsed","missing from parse","parse missing","no observed pin-function evidence")):
   return "parser_evidence_missing"
  if "authoritative" in msg and any(k in msg for k in ("profile","fingerprint","datasheet")):
   return "reference_profile_missing"
 return "other_or_unclassified"

def identity_evidence_inventory(findings):
 buckets={
  "parser_evidence_missing":[],
  "reference_profile_missing":[],
  "insufficient_discriminating_evidence":[],
  "verified_identity_contradiction":[],
  "other_or_unclassified":[],
 }
 for f in findings if isinstance(findings,list) else []:
  if str(f.get("id","")).startswith("G2-SCH-IDENTITY-") or (f.get("status")=="UNKNOWN" and f.get("domain") in {"schematic","compile","connectivity","parse"}):
   buckets[classify_identity_finding(f)].append(f)
 return buckets

def finding_inventory(findings, phase=None):
 if not isinstance(findings,list):
  findings=[]
 deferred=[f for f in findings if f.get("id") in DEFERRED_NON_GATING_IDS]
 effective=[f for f in findings if f.get("id") not in DEFERRED_NON_GATING_IDS]
 if phase == "schematic":
  # A schematic receipt is authorized only by schematic/compile/connectivity evidence.
  # PCB routing/placement findings belong to their own downstream phase receipts.
  effective=[f for f in effective if f.get("domain") in {"schematic","compile","connectivity","parse","intake"}]
 errors=[f for f in effective if f.get("status")=="FAIL" or f.get("severity")=="BLOCKER"]
 warnings=[f for f in findings if f.get("status") in ("WARN","UNKNOWN","BLOCKED") or f.get("severity") in ("HIGH","MEDIUM","LOW")]
 informational=[f for f in findings if f.get("severity")=="INFO" and f.get("status") not in ("FAIL","WARN","UNKNOWN","BLOCKED")]
 return {
  "total":len(findings),
  "deferred_non_gating":deferred,
  "errors":errors,
  "warnings":warnings,
  "informational":informational,
  "blocking": [f for f in effective if f.get("status") in ("FAIL","BLOCKED") and f.get("severity") in ("HIGH","BLOCKER")],
  "unknown": [f for f in findings if f.get("status")=="UNKNOWN"],
  "identity_evidence": identity_evidence_inventory(findings),
 }

def receipt(out,phase,status,evidence,up=None):
 r={"schema":"altium-audit-e2e-phase/v2","phase":phase,"status":status,
    "evidence":evidence,"upstream_receipt_sha256":up,
    "finding_inventory":evidence.get("finding_inventory",{"total":0,"errors":[],"warnings":[],"informational":[],"blocking":[],"unknown":[]})}
 (out/"phase_receipt.json").write_text(json.dumps(r,indent=2,ensure_ascii=False)); print(json.dumps(r,indent=2)); return 0 if status=="PASS" else 1
def main():
 ap=argparse.ArgumentParser(); ap.add_argument("--phase",choices=["schematic","placement","routing"],required=True); ap.add_argument("--input",type=Path,required=True); ap.add_argument("--output",type=Path,required=True); ap.add_argument("--config",type=Path); ap.add_argument("--upstream-receipt",type=Path); a=ap.parse_args()
 root=a.input.resolve(); out=a.output.resolve(); s,b,p=discover(root); out.mkdir(parents=True,exist_ok=True)
 up=hashlib.sha256(a.upstream_receipt.read_bytes()).hexdigest() if a.upstream_receipt and a.upstream_receipt.exists() else None
 if a.phase=="schematic":
  rc,x=audit(root,out/"audit",a.config); g=x.get("gates",{}); findings=x.get("findings",[]); req={k:g.get(k) for k in ["G0_INTAKE","G1_PARSE","G2_COMPILE","G3_CONNECTIVITY"]}; inv=finding_inventory(findings, phase="schematic")
  blocking=bool(inv["blocking"] or inv["errors"])
  policy=json.loads(a.config.read_text()).get("policy",{}) if a.config else {}
  block_unknown=bool(policy.get("block_on_unsupported_required_check",True))
  required_unknown=required_schematic_unknowns(findings, block_unknown, bool(policy.get("require_schlib_source", False)))
  ok=all(v=="VERIFIED" for v in req.values()) and not blocking and not required_unknown
  return receipt(out,"SCHEMATIC","PASS" if ok else "BLOCKED",{"runner_rc":rc,"required_gates":req,"finding_inventory":inv,"required_unknown_findings":required_unknown,"finding_policy":"PASS requires G0-G3 VERIFIED, no blocking findings in the schematic/compile/connectivity/intake/parse domains, and no UNKNOWN schematic-required checks under block_on_unsupported_required_check. PCB placement/routing findings are evaluated by their own downstream phase; explicitly scoped TVS identity and U19/U24/U29 NC findings are deferred non-gating by current project scope.","downstream_impact":{"placement":"BLOCKED unless schematic phase is PASS","routing":"BLOCKED unless placement is PASS"}})
 if a.phase=="placement":
  if not a.upstream_receipt or not a.upstream_receipt.exists(): return receipt(out,"PLACEMENT","BLOCKED",{"reason":"missing schematic upstream receipt"},up)
  try:
   ur=json.loads(a.upstream_receipt.read_text())
  except Exception:
   return receipt(out,"PLACEMENT","BLOCKED",{"reason":"invalid schematic upstream receipt"},up)
  if ur.get("phase")!="SCHEMATIC" or ur.get("status")!="PASS": return receipt(out,"PLACEMENT","BLOCKED",{"reason":"schematic prerequisite not VERIFIED","upstream_phase":ur.get("phase"),"upstream_status":ur.get("status")},up)
  rc,x=audit(root,out/"audit",a.config); g=x.get("gates",{}); pre=all(g.get(k)=="VERIFIED" for k in ["G0_INTAKE","G1_PARSE","G2_COMPILE","G3_CONNECTIVITY"])
  findings=x.get("findings",[]); inv=finding_inventory(findings)
  if not pre:return receipt(out,"PLACEMENT","BLOCKED",{"reason":"schematic prerequisite failed","runner_rc":rc,"gates":g,"finding_inventory":inv},up)
  nl=json.loads((out/"audit"/"netlist.json").read_text()); m=out/"connectivity-manifest.json"; m.write_text(json.dumps({"schema":"altium-connectivity-manifest.v2","status":"VERIFIED","basis":"phase-1 G3_CONNECTIVITY","nets":nl.get("nets",[])} ,indent=2))
  intelligence=out/"connectivity-intelligence.json"; irc=run([HERE/"connectivity_intelligence.py","--netlist",out/"audit"/"netlist.json","--out",intelligence]);
  plan=out/"placement-routing-plan.json"; prc=run([PLANNER,"--pcb",b,"--out",plan,"--findings",out/"audit"/"findings.json","--connectivity-manifest",m]+(["--config",a.config] if a.config else [])); z=json.loads(plan.read_text()) if plan.exists() else {}; pl=z.get("placement",{}); ok=pl.get("status") in ("VERIFIED","PASS") and pl.get("lock",{}).get("status")=="LOCKED"
  return receipt(out,"PLACEMENT","PASS" if ok else "BLOCKED",{"planner_rc":prc,"connectivity_intelligence_rc":irc,"placement":pl,"routing":"DEFERRED","finding_inventory":inv,"downstream_impact":{"routing":"ALLOWED_WITH_FINDINGS" if not inv["blocking"] else "BLOCKED","note":"Placement PASS does not erase schematic findings; downstream must retain and account for them."}},up)
 if not a.upstream_receipt or not a.upstream_receipt.exists(): return receipt(out,"ROUTING","BLOCKED",{"reason":"missing placement upstream receipt"},up)
 try:
  ur=json.loads(a.upstream_receipt.read_text())
 except Exception:
  return receipt(out,"ROUTING","BLOCKED",{"reason":"invalid placement upstream receipt"},up)
 if ur.get("phase")!="PLACEMENT" or ur.get("status")!="PASS": return receipt(out,"ROUTING","BLOCKED",{"reason":"placement prerequisite not VERIFIED","upstream_phase":ur.get("phase"),"upstream_status":ur.get("status")},up)
 rc,x=audit(root,out/"audit",a.config); g=x.get("gates",{}); findings=x.get("findings",[]); inv=finding_inventory(findings); req={k:g.get(k) for k in ["G3_CONNECTIVITY","G6_PLACEMENT","G7_ROUTING"]}; ok=all(v=="VERIFIED" for v in req.values())
 return receipt(out,"ROUTING","PASS" if ok else "BLOCKED",{"runner_rc":rc,"required_gates":req,"finding_inventory":inv,"routing_repair":"DEFERRED_TO_ROUTING_MUTATION_STAGE","downstream_impact":{"mutation":"BLOCKED" if inv["blocking"] else "REQUIRES_FINDING_REVIEW"}} ,up)
if __name__=="__main__": raise SystemExit(main())
