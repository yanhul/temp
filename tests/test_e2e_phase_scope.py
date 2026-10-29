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


def test_scoped_tvs_identity_findings_are_explicitly_deferred():
    findings = [
        {"id": "G2-SCH-IDENTITY-EVIDENCE-D12", "domain": "schematic", "status": "FAIL", "severity": "BLOCKER"},
        {"id": "G2-SCH-IDENTITY-EVIDENCE-D13", "domain": "schematic", "status": "FAIL", "severity": "BLOCKER"},
        {"id": "G2-SCH-IDENTITY-EVIDENCE-D5", "domain": "schematic", "status": "FAIL", "severity": "BLOCKER"},
    ]
    inventory = e2e_phase.finding_inventory(findings, phase="schematic")
    assert {item["id"] for item in inventory["deferred_non_gating"]} == {
        "G2-SCH-IDENTITY-EVIDENCE-D5",
        "G2-SCH-IDENTITY-EVIDENCE-D12",
        "G2-SCH-IDENTITY-EVIDENCE-D13",
    }
    assert inventory["errors"] == []
