import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tools"/"altium-audit"))
import local_schlib_audit as audit

def test_absent_local_schlib_is_unknown_not_pass(tmp_path):
    findings=[]
    result=audit.audit_local_schlibs(tmp_path,[],lambda *a:findings.append(a))
    assert result["files_found"]==0
    assert any(f[0]=="G2-SCHLIB-SOURCE-INVENTORY" and f[3]=="UNKNOWN" for f in findings)

def test_exact_local_symbol_pins_are_compared_with_source_hash(tmp_path,monkeypatch):
    class Pin:
        def __init__(self,designator,name): self.designator,self.name=designator,name
    class Symbol:
        name="TVS_Diode"; original_name="TVS_Diode"; pins=[Pin("1","A"),Pin("2","K")]
    class Library:
        symbols=[Symbol()]
        def __init__(self,path): pass
    import altium_monkey
    monkeypatch.setattr(altium_monkey,"AltiumSchLib",Library,raising=False)
    (tmp_path/"Local.SchLib").write_bytes(b"local library fixture")
    findings=[]
    result=audit.audit_local_schlibs(tmp_path,[{"reference":"D1","library_id":"TVS_Diode","pins":[{"pin":"1","pin_name":"A"},{"pin":"2","pin_name":"K"}]}],lambda *a:findings.append(a))
    f=next(x for x in findings if x[0]=="G2-SCHLIB-PINMAP-D1")
    assert result["files_parsed"]==1 and f[3]=="VERIFIED"
    assert "sha256:" in f[4] and "not physical manufacturer-part identity" in f[4]

def test_pin_conflict_fails_and_suffix_is_not_fuzzy_matched(tmp_path,monkeypatch):
    class Pin:
        designator="1"; name="ANODE"
    class Symbol:
        name="PartA"; original_name="PartA"; pins=[Pin()]
    class Library:
        symbols=[Symbol()]
        def __init__(self,path): pass
    import altium_monkey
    monkeypatch.setattr(altium_monkey,"AltiumSchLib",Library,raising=False)
    (tmp_path/"Local.SchLib").write_bytes(b"local library fixture")
    findings=[]
    audit.audit_local_schlibs(tmp_path,[{"reference":"D1","library_id":"PartA","pins":[{"pin":"1","pin_name":"CATHODE"}]},{"reference":"D2","library_id":"PartA_C45354919","pins":[]}],lambda *a:findings.append(a))
    assert any(f[0]=="G2-SCHLIB-PINMAP-D1" and f[3]=="FAIL" for f in findings)
    assert any(f[0]=="G2-SCHLIB-SYMBOL-MISSING-D2" and f[3]=="UNKNOWN" for f in findings)
