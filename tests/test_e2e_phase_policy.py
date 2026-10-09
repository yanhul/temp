import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "tools" / "altium-audit" / "e2e_phase.py"
SPEC = importlib.util.spec_from_file_location("e2e_phase", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_required_schematic_unknown_blocks_pass():
    findings = [{
        "id": "G2-SCH-IDENTITY-UNRESOLVED-U15",
        "domain": "schematic",
        "status": "UNKNOWN",
    }]
    assert MODULE.required_schematic_unknowns(findings, True) == findings


def test_non_schematic_unknown_does_not_block_schematic_phase():
    findings = [{"id": "G6-PHYSICAL", "domain": "physical", "status": "UNKNOWN"}]
    assert MODULE.required_schematic_unknowns(findings, True) == []


def test_only_explicitly_deferred_u19_u24_u29_nc_findings_are_non_gating():
    findings = [
        {"id": f"G2-HCPL-NC-PIN4-CONNECTED-{ref}", "domain": "schematic", "status": "UNKNOWN"}
        for ref in ("U19", "U24", "U29")
    ]
    assert MODULE.required_schematic_unknowns(findings, True) == []


def test_hcpl_topology_unknown_is_not_silently_deferred():
    findings = [{"id": "G2-HCPL-TOPOLOGY-ADC1_DATA", "domain": "schematic", "status": "UNKNOWN"}]
    assert MODULE.required_schematic_unknowns(findings, True) == findings


def test_policy_can_disable_unknown_gate_only_when_explicitly_authorized():
    findings = [{"id": "G2-SCH-IDENTITY-UNRESOLVED-U15", "domain": "schematic", "status": "UNKNOWN"}]
    assert MODULE.required_schematic_unknowns(findings, False) == []
