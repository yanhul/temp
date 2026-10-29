import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import fitz


ROOT = Path(__file__).resolve().parent


class NonSmartPdfFallbackTests(unittest.TestCase):
    def test_native_vector_pdf_without_pi_preserves_evidence_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            source = tmp / "native_schematic.pdf"
            out = tmp / "out"
            doc = fitz.open()
            page = doc.new_page(width=500, height=500)
            page.insert_text((40, 35), "R1 U2 GND +5V")
            for y in range(60, 240, 6):
                page.draw_line((40, y), (250, y), color=(0, 0, 1), width=0.5)
            doc.save(source)
            doc.close()

            proc = subprocess.run(
                [sys.executable, str(ROOT / "main.py"), str(source), "-o", str(out)],
                cwd=ROOT, capture_output=True, text=True, timeout=120,
            )
            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("BLOCKED_NOT_CONVERTED", proc.stdout + proc.stderr)
            profile_path = out / "pdf_profile.json"
            vector_path = out / "pdf_vector_evidence.json"
            self.assertTrue(profile_path.is_file(), proc.stdout + proc.stderr)
            self.assertTrue(vector_path.is_file(), proc.stdout + proc.stderr)
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            evidence = json.loads(vector_path.read_text(encoding="utf-8"))
            self.assertEqual(profile["page_count"], 1)
            self.assertNotEqual(profile["pages"][0]["kind"], "smart_pdf_candidate")
            self.assertEqual(evidence["page_count"], 1)
            self.assertGreater(len(evidence["pages"][0]["objects"]), 0)
            self.assertEqual(evidence["pages"][0]["electrical_connectivity"], "NOT_INFERRED")


if __name__ == "__main__":
    unittest.main()
