import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "altium-audit"))
import e2e_phase


def test_schematic_phase_ignores_downstream_routing_findings():
    findings = [
        {"id": "G2-COMPILE", "domain": "compile", "status": "VERIFIED", "severity": "INFO"},
        {"id": "G7-TOPOLOGY-GND", "domain": "routing", "status": "FAIL", "severity": "HIGH"},
    ]
    inventory = e2e_phase.finding_inventory(findings, phase="schematic")
    assert inventory["errors"] == []
    assert inventory["blocking"] == []


def test_tvs_identity_contradictions_are_not_exempted_by_footprint_reuse():
    findings = [
        {"id": "G2-SCH-IDENTITY-EVIDENCE-D12", "domain": "schematic", "status": "FAIL", "severity": "BLOCKER"},
        {"id": "G2-SCH-IDENTITY-EVIDENCE-D13", "domain": "schematic", "status": "FAIL", "severity": "BLOCKER"},
        {"id": "G2-SCH-IDENTITY-EVIDENCE-D5", "domain": "schematic", "status": "FAIL", "severity": "BLOCKER"},
    ]
    inventory = e2e_phase.finding_inventory(findings, phase="schematic")
    assert inventory["deferred_non_gating"] == []
    assert {item["id"] for item in inventory["errors"]} == {
        "G2-SCH-IDENTITY-EVIDENCE-D5",
        "G2-SCH-IDENTITY-EVIDENCE-D12",
        "G2-SCH-IDENTITY-EVIDENCE-D13",
    }

def test_identity_evidence_is_split_into_distinct_root_causes():
    findings = [
        {"id": "G2-SCH-IDENTITY-UNRESOLVED-C2", "domain": "schematic", "status": "UNKNOWN",
         "evidence": "No observed pin-function evidence is available to distinguish the identities."},
        {"id": "G2-SCH-IDENTITY-UNRESOLVED-D1", "domain": "schematic", "status": "UNKNOWN",
         "evidence": "Different identities are present, but one or both lack an authoritative pin fingerprint."},
        {"id": "G2-SCH-IDENTITY-EVIDENCE-D5", "domain": "schematic", "status": "FAIL",
         "evidence": "Declared and compiled part identities conflict on authoritative electrical/package specifications."},
        {"id": "G2-SCH-IDENTITY-UNRESOLVED-Q1", "domain": "schematic", "status": "UNKNOWN",
         "evidence": "Observed pin functions do not uniquely identify either candidate."},
    ]
    buckets = e2e_phase.identity_evidence_inventory(findings)
    assert [f["id"] for f in buckets["parser_evidence_missing"]] == ["G2-SCH-IDENTITY-UNRESOLVED-C2"]
    assert [f["id"] for f in buckets["reference_profile_missing"]] == ["G2-SCH-IDENTITY-UNRESOLVED-D1"]
    assert [f["id"] for f in buckets["verified_identity_contradiction"]] == ["G2-SCH-IDENTITY-EVIDENCE-D5"]
    assert [f["id"] for f in buckets["insufficient_discriminating_evidence"]] == ["G2-SCH-IDENTITY-UNRESOLVED-Q1"]



def test_diagnostic_only_mode_never_promotes_blocked_upstream_phase():
    source = (Path(__file__).resolve().parents[1] / "tools" / "altium-audit" / "e2e_phase.py").read_text(encoding="utf-8")
    assert '--diagnostic-only' in source
    assert 'final_ok=ok and pre and upstream_ok and not a.diagnostic_only' in source
    assert 'final_ok=ok and upstream_ok and not a.diagnostic_only' in source


def test_placement_review_contract_is_separate_from_routing():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "tools" / "altium-audit" / "e2e_phase.py").read_text(encoding="utf-8")
    assert '"schema":"altium-placement-review.v1"' in source
    assert '"routing":"DEFERRED"' in source
    assert '"mutation":"FORBIDDEN"' in source
    assert 'placement-review.json' in source
