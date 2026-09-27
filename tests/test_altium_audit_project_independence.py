from pathlib import Path

ENGINE = Path("tools/altium-audit/audit_runner.py")
PROTOCOL = Path("tools/altium-audit/AUDIT_PROTOCOL.md")

def test_engine_contains_no_current_project_identifiers():
    text = ENGINE.read_text(encoding="utf-8")
    forbidden = ("QI9-2604-A01", "J6", "J7", "ESP32")
    assert not any(token in text for token in forbidden)

def test_protocol_contains_no_current_project_identifiers():
    text = PROTOCOL.read_text(encoding="utf-8")
    forbidden = ("QI9-2604-A01", "J6", "J7", "ESP32")
    assert not any(token in text for token in forbidden)

def test_engine_accepts_generic_root_and_optional_config():
    text = ENGINE.read_text(encoding="utf-8")
    assert '--root' in text
    assert '--out' in text
    assert '--config' in text
