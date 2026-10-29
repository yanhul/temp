from pathlib import Path


def test_audit_workflow_passes_authoritative_findings_to_routing_planner():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "altium-audit.yml").read_text(encoding="utf-8")
    command = next(line for line in workflow.splitlines() if "--topology-cmd" in line)
    assert "--findings work/audit/findings.json" in command
    assert "--config altium-audit.config.json" in command

