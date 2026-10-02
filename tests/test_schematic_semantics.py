import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "altium-audit"))
import schematic_semantics as ss
from part_identity import resolve_declared_vs_compiled


def run_checker(component, netlist):
    findings=[]
    ss.run([component], {"nets": netlist}, lambda *args: findings.append(args))
    return findings


def test_display_value_drift_is_not_identity_blocker():
    c={"designator":"R1","value":"Res1","library_reference":"Res1",
       "parameters":{"Value":"2K2"},"pin_count":2}
    findings=run_checker(c, [])
    ids=[x[0] for x in findings]
    assert "G2-SCH-METADATA-VALUE-R1" in ids
    assert not any(x[0].startswith("G2-SCH-IDENTITY-R1") and x[2]=="FAIL" for x in findings)


def test_value_vs_mpn_drift_is_not_identity_blocker():
    c={"designator":"U18","value":"HCPL-0600","library_reference":"HCPL-3120",
       "parameters":{"MPN":"HCPL-3120-500E"},"pin_count":8}
    findings=run_checker(c, [])
    assert not any(x[0]=="G2-SCH-IDENTITY-U18" and x[2]=="FAIL" for x in findings)


def test_hcpl_pin_evidence_still_blocks_real_function_mismatch():
    c={"designator":"U18","value":"HCPL-0600","library_reference":"HCPL-3120","pin_count":8}
    nl=[{"name":"HCPL", "terminals":[
        {"designator":"U18","pin":"1","pin_name":"NC","pin_type":"PASSIVE"},
        {"designator":"U18","pin":"2","pin_name":"ANODE","pin_type":"INPUT"},
        {"designator":"U18","pin":"3","pin_name":"CATHODE","pin_type":"INPUT"},
        {"designator":"U18","pin":"4","pin_name":"NC","pin_type":"PASSIVE"},
        {"designator":"U18","pin":"5","pin_name":"VEE","pin_type":"POWER"},
        {"designator":"U18","pin":"6","pin_name":"VO","pin_type":"OUTPUT"},
        {"designator":"U18","pin":"7","pin_name":"NC","pin_type":"PASSIVE"},
        {"designator":"U18","pin":"8","pin_name":"VCC","pin_type":"POWER"}
    ]}]
    observed={
        t["pin"]: {"name": t["pin_name"]}
        for n in nl for t in n["terminals"]
    }
    identity=resolve_declared_vs_compiled("HCPL-0600", "HCPL-3120", observed)
    assert identity["state"]=="CONTRADICTION"
    findings=run_checker(c, nl)
    assert any(x[2]=="FAIL" and str(x[-1]).startswith("U18") for x in findings)
