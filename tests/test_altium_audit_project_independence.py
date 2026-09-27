import unittest
from pathlib import Path

ENGINE = Path("tools/altium-audit/audit_runner.py")
PROTOCOL = Path("tools/altium-audit/AUDIT_PROTOCOL.md")

class ProjectIndependenceTests(unittest.TestCase):
    def test_engine_contains_no_current_project_identifiers(self):
        text = ENGINE.read_text(encoding="utf-8")
        forbidden = ("QI9-2604-A01", "J6", "J7", "ESP32")
        self.assertFalse(any(token in text for token in forbidden))

    def test_protocol_contains_no_current_project_identifiers(self):
        text = PROTOCOL.read_text(encoding="utf-8")
        forbidden = ("QI9-2604-A01", "J6", "J7", "ESP32")
        self.assertFalse(any(token in text for token in forbidden))


    def test_schematic_designator_child_lookup_is_present(self):
        text = ENGINE.read_text(encoding="utf-8")
        self.assertIn('field(obj, "parameters")', text)
        self.assertIn('field(obj, "children")', text)
        self.assertIn('"designator" in kind', text)
        self.assertIn('field(child, "text", "value")', text)
        # The child lookup must precede generic/name fallbacks: schematic\n        # component.name is the library symbol name, not its reference.\n        self.assertLess(text.index('for child in list(field(obj, "children") or [])'),\n                        text.index('v = field(obj, "designator", "refdes", "reference", "id")'))\n
    def test_engine_accepts_generic_inputs(self):
        text = ENGINE.read_text(encoding="utf-8")
        self.assertIn('--root', text)
        self.assertIn('--out', text)
        self.assertIn('--config', text)

if __name__ == "__main__":
    unittest.main()
