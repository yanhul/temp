import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "altium-audit"))
import schematic_semantics as ss
from part_identity import resolve_declared_vs_compiled


def run_checker(component, netlist):
    findings=[]
    pins=[]
    ref=component.get("designator")
    for n in netlist:
        for t in n.get("terminals",[]):
            if str(t.get("designator"))==str(ref):
                pins.append({"pin":str(t.get("pin")),"pin_name":t.get("pin_name"),
                             "electrical_type":t.get("pin_type"),"connected_net":n.get("name")})
    record={"reference":ref,"declared_value":component.get("value"),
            "compiled_value":(component.get("parameters") or {}).get("Value"),
            "library_id":component.get("library_reference"),
            "footprint":component.get("footprint"),
            "mpn":(component.get("parameters") or {}).get("MPN"),
            "description":component.get("description"),
            "pin_count":component.get("pin_count"),
            "properties":{str(k).lower():v for k,v in (component.get("parameters") or {}).items()},
            "pins":pins}
    evidence={"schema":"altium-schematic-evidence.v1","status":"VERIFIED","components":[record]}
    ss.run(evidence, None, lambda *args: findings.append(args))
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
        {"designator":"U18","pin":"7","pin_name":"VO","pin_type":"OUTPUT"},
        {"designator":"U18","pin":"8","pin_name":"VCC","pin_type":"POWER"}
    ]}]
    observed={
        t["pin"]: {"name": t["pin_name"]}
        for n in nl for t in n["terminals"]
    }
    identity=resolve_declared_vs_compiled("HCPL-0600", "HCPL-3120", observed)
    assert identity["state"]=="CONTRADICTION"
    findings=run_checker(c, nl)
    assert any(x[3]=="FAIL" and str(x[-1]).startswith("U18") for x in findings)


def test_metadata_and_peer_wiring_are_review_evidence_not_warnings():
    c1={"designator":"U1","value":"X","library_reference":"X","parameters":{"Value":"X"},"pin_count":2}
    c2={"designator":"U2","value":"X","library_reference":"X","parameters":{"Value":"X"},"pin_count":2}
    nl=[{"name":"N1","terminals":[{"designator":"U1","pin":"1","pin_name":"A","pin_type":"PASSIVE"},{"designator":"U2","pin":"1","pin_name":"A","pin_type":"PASSIVE"},{"designator":"U2","pin":"2","pin_name":"B","pin_type":"PASSIVE"}]}]
    findings=[]
    evidence={"schema":"altium-schematic-evidence.v1","status":"VERIFIED","components":[]}
    for c in (c1,c2):
        pins=[]
        for n in nl:
            for t in n.get("terminals",[]):
                if str(t.get("designator"))==str(c.get("designator")):
                    pins.append({"pin":str(t.get("pin")),"pin_name":t.get("pin_name"),
                                 "electrical_type":t.get("pin_type"),"connected_net":n.get("name")})
        evidence["components"].append({
            "reference":c.get("designator"),"declared_value":c.get("value"),
            "compiled_value":(c.get("parameters") or {}).get("Value"),
            "library_id":c.get("library_reference"),"pin_count":c.get("pin_count"),
            "properties":{str(k).lower():v for k,v in (c.get("parameters") or {}).items()},
            "pins":pins})
    ss.run(evidence, None, lambda *args: findings.append(args))
    assert any(x[0]=="G2-SCH-PEER-CONNECTIVITY-U2" and x[1]=="INFO" and x[2]=="schematic" and x[3]=="VERIFIED" for x in findings)


def test_metadata_value_review_evidence_is_verified_info():
    c={"designator":"R1","value":"Res1","library_reference":"Res1","parameters":{"Value":"2K2"},"pin_count":2}
    findings=run_checker(c, [])
    assert any(x[0]=="G2-SCH-METADATA-VALUE-R1" and x[1]=="INFO" and x[3]=="VERIFIED" for x in findings)


def test_unresolved_identity_is_unknown_review_evidence_not_warning():
    c={"designator":"R99","value":"Foo","library_reference":"Bar","pin_count":2}
    findings=run_checker(c, [])
    x=next(v for v in findings if v[0]=="G2-SCH-IDENTITY-UNRESOLVED-R99")
    assert x[1]=="INFO" and x[2]=="schematic" and x[3]=="UNKNOWN"


def test_canonical_evidence_is_required_and_raw_component_is_rejected():
    import pytest
    with pytest.raises(TypeError):
        ss.run({"schema":"wrong","components":[]}, None, lambda *args: None)


def test_canonical_pin_net_evidence_drives_identity():
    evidence={"schema":"altium-schematic-evidence.v1","status":"VERIFIED","components":[
        {"reference":"U18","declared_value":"HCPL-0600","compiled_value":"HCPL-3120",
         "library_id":"HCPL-3120","pin_count":8,"pins":[
            {"pin":"1","pin_name":"NC","electrical_type":"PASSIVE","connected_net":"N1"},
            {"pin":"2","pin_name":"ANODE","electrical_type":"INPUT","connected_net":"LED"},
            {"pin":"3","pin_name":"CATHODE","electrical_type":"INPUT","connected_net":"LEDK"},
            {"pin":"4","pin_name":"NC","electrical_type":"PASSIVE","connected_net":"N2"},
            {"pin":"5","pin_name":"VEE","electrical_type":"POWER","connected_net":"GND"},
            {"pin":"6","pin_name":"VO","electrical_type":"OUTPUT","connected_net":"OUT"},
            {"pin":"7","pin_name":"VO","electrical_type":"OUTPUT","connected_net":"OUT2"},
            {"pin":"8","pin_name":"VCC","electrical_type":"POWER","connected_net":"+5V"}]}
    ]}
    findings=[]
    ss.run(evidence, None, lambda *args: findings.append(args))
    assert any(x[3]=="FAIL" for x in findings)


def test_hcpl3120_profile_uses_pin7_vo():
    observed = {
        str(pin): {"name": name}
        for pin, name in {
            "1":"NC","2":"ANODE","3":"CATHODE","4":"NC",
            "5":"VEE","6":"VO","7":"VO","8":"VCC"
        }.items()
    }
    identity = resolve_declared_vs_compiled("HCPL-0600", "HCPL-3120", observed)
    assert identity["state"] == "CONTRADICTION"


def test_authoritative_nc_connection_is_a_schematic_failure():
    evidence={"schema":"altium-schematic-evidence.v1","status":"VERIFIED","components":[{
        "reference":"U19","declared_value":"HCPL-0600","library_id":"HCPL-3120","pin_count":8,
        "pins":[
            {"pin":"1","pin_name":"NC","electrical_type":"PASSIVE","connected_net":None},
            {"pin":"2","pin_name":"ANODE","electrical_type":"INPUT","connected_net":"LED"},
            {"pin":"3","pin_name":"CATHODE","electrical_type":"INPUT","connected_net":"LEDK"},
            {"pin":"4","pin_name":"NC","electrical_type":"PASSIVE","connected_net":"GND1"},
            {"pin":"5","pin_name":"VEE","electrical_type":"POWER","connected_net":"GND"},
            {"pin":"6","pin_name":"VO","electrical_type":"OUTPUT","connected_net":"OUT"},
            {"pin":"7","pin_name":"VO","electrical_type":"OUTPUT","connected_net":"OUT"},
            {"pin":"8","pin_name":"VCC","electrical_type":"POWER","connected_net":"+5V"}]
    }]}
    findings=[]
    ss.run(evidence,None,lambda *args: findings.append(args))
    assert any(x[0]=="G2-SCH-NC-PIN-CONNECTED-U19" and x[3]=="FAIL" for x in findings)


def test_hcpl0600_project_identity_override_does_not_mask_compiled_pin_conflict():
    observed = {str(pin): {"name": name} for pin, name in {
        "1":"NC","2":"ANODE","3":"CATHODE","4":"NC","5":"VEE","6":"VO","7":"VO","8":"VCC"
    }.items()}
    identity = resolve_declared_vs_compiled("HCPL-0600", "HCPL-3120", observed, "HCPL-0600")
    assert identity["state"] == "CONTRADICTION"
    assert any(item["pin"] == "5" and item["declared_expected"] == "GND"
               and item["compiled_expected"] == "VEE" for item in identity["evidence"])


def test_hcpl0600_enable_tied_to_vcc_is_not_a_failure():
    evidence={"schema":"altium-schematic-evidence.v1","status":"VERIFIED","components":[{
        "reference":"U18","declared_value":"HCPL-0600","compiled_value":"HCPL-3120","library_id":"HCPL-3120","pin_count":8,
        "pins":[
            {"pin":"2","pin_name":"ANODE","electrical_type":"INPUT","connected_net":"LED"},
            {"pin":"3","pin_name":"CATHODE","electrical_type":"INPUT","connected_net":"LEDK"},
            {"pin":"4","pin_name":"NC","electrical_type":"PASSIVE","connected_net":None},
            {"pin":"5","pin_name":"GND","electrical_type":"POWER","connected_net":"GND"},
            {"pin":"6","pin_name":"VO","electrical_type":"OUTPUT","connected_net":"OUT"},
            {"pin":"7","pin_name":"VE","electrical_type":"INPUT","connected_net":"+5V"},
            {"pin":"8","pin_name":"VCC","electrical_type":"POWER","connected_net":"+5V"}]}]}
    findings=[]
    ss.run(evidence, None, lambda *args: findings.append(args), {"HCPL0600":"HCPL0600"})
    assert not any(x[0]=="G2-HCPL-VE-ON-SUPPLY-U18" and x[3]=="FAIL" for x in findings)


def test_hcpl_bypass_accepts_common_100nf_value_spellings():
    assert ss._is_100nf_class("100nF")
    assert ss._is_100nf_class("100n")
    assert ss._is_100nf_class("0.1uF")
    assert ss._is_100nf_class("104")
    assert not ss._is_100nf_class("1uF")



def test_known_smaj_voltage_rating_mismatch_is_blocker_in_semantic_gate():
    component = {
        "designator": "D12",
        "value": "SMAJ15CA",
        "library_reference": "SMAJ30CA",
        "parameters": {"Value": "SMAJ30A", "MPN": "SMAJ30A"},
        "pin_count": 2,
    }
    findings = run_checker(component, [])
    finding = next(x for x in findings if x[0] == "G2-SCH-IDENTITY-EVIDENCE-D12")
    assert finding[1] == "BLOCKER"
    assert finding[2] == "schematic"
    assert finding[3] == "FAIL"
    assert "reverse_standoff_v" in finding[4]


def test_authoritative_mpn_overrides_stale_library_identity_for_physical_part_check():
    evidence = {
        "schema": "altium-schematic-evidence.v1",
        "status": "VERIFIED",
        "components": [{
            "reference": "D12",
            "declared_value": "SMAJ15CA",
            "library_id": "SMAJ15CA",
            "mpn": "SMAJ30A",
            "pins": [
                {"pin": "1", "pin_name": "A", "electrical_type": "PASSIVE", "connected_net": "N1"},
                {"pin": "2", "pin_name": "K", "electrical_type": "PASSIVE", "connected_net": "GND"},
            ],
        }],
    }
    findings = []
    ss.run(evidence, None, lambda *args: findings.append(args))
    identity = [item for item in findings if item[0] == "G2-SCH-IDENTITY-EVIDENCE-D12"]
    assert identity
    assert identity[0][3] == "FAIL"
    assert "directionality" in identity[0][4]



def _temporary_hcpl0600_evidence(pin7_net="5V_RS232"):
    return {
        "schema": "altium-schematic-evidence.v1",
        "status": "VERIFIED",
        "components": [{
            "reference": "U6",
            "declared_value": "HCPL-0600",
            "library_id": "IC_HCPL-3120-500E",
            "mpn": "HCPL-3120-500E",
            "pin_count": 8,
            "properties": {"value": "HCPL-0600", "mpn": "HCPL-3120-500E"},
            "pins": [
                {"pin": "1", "pin_name": "NC", "electrical_type": "PASSIVE", "connected_net": None},
                {"pin": "2", "pin_name": "ANODE", "electrical_type": "INPUT", "connected_net": "LED_IN"},
                {"pin": "3", "pin_name": "CATHODE", "electrical_type": "INPUT", "connected_net": "LED_RET"},
                {"pin": "4", "pin_name": "NC", "electrical_type": "PASSIVE", "connected_net": None},
                {"pin": "5", "pin_name": "VEE", "electrical_type": "POWER", "connected_net": "GND_RS232"},
                {"pin": "6", "pin_name": "V0", "electrical_type": "OUTPUT", "connected_net": "UART_TX0"},
                {"pin": "7", "pin_name": "V0", "electrical_type": "OUTPUT", "connected_net": pin7_net},
                {"pin": "8", "pin_name": "VCC", "electrical_type": "POWER", "connected_net": "5V_RS232"},
            ],
        }],
    }


def test_explicit_temporary_hcpl0600_override_checks_pin_number_net_topology():
    findings = []
    ss.run(
        _temporary_hcpl0600_evidence(),
        None,
        lambda *args: findings.append(args),
        identity_overrides={"HCPL0600": "HCPL0600"},
    )
    ids = {x[0] for x in findings}
    assert "G2-SCH-IDENTITY-EVIDENCE-U6" not in ids
    topology = next(x for x in findings if x[0] == "G2-HCPL-0600-TOPOLOGY-U6")
    assert topology[1:4] == ("INFO", "schematic", "VERIFIED")
    assert topology[5] == "ASSUMPTION"
    override = next(x for x in findings if x[0] == "G2-SCH-IDENTITY-OVERRIDE-U6")
    assert override[5] == "ASSUMPTION"
    assert any(x[0] == "G2-SCH-METADATA-MPN-U6" for x in findings)


def test_explicit_temporary_hcpl0600_override_still_blocks_bad_enable_topology():
    findings = []
    ss.run(
        _temporary_hcpl0600_evidence(pin7_net="OTHER_SUPPLY"),
        None,
        lambda *args: findings.append(args),
        identity_overrides={"HCPL0600": "HCPL0600"},
    )
    topology = next(x for x in findings if x[0] == "G2-HCPL-0600-TOPOLOGY-U6")
    assert topology[1:4] == ("BLOCKER", "schematic", "FAIL")
