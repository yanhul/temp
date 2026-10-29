import subprocess
import unittest
from unittest.mock import patch

import fitz

from ocr_vector_adapter import ocr_page


TSV = (
    "level\\tpage_num\\tblock_num\\tpar_num\\tline_num\\tword_num\\t"
    "left\\ttop\\twidth\\theight\\tconf\\ttext\\n"
    "5\\t1\\t1\\t1\\t1\\t1\\t72\\t108\\t24\\t12\\t96.5\\tR12\\n"
    "5\\t1\\t1\\t1\\t1\\t2\\t120\\t108\\t20\\t12\\t88.0\\tGND\\n"
)


class OCRVectorAdapterTests(unittest.TestCase):
    def test_refdes_pattern_accepts_common_designators(self):
        from ocr_vector_adapter import REFDES

        for value in ("R1", "C12", "U35", "SW2", "J8", "FB3"):
            self.assertRegex(value, REFDES)
        for value in ("GNDREF", "USB_D+", "C4140", "1k"):
            self.assertNotRegex(value, REFDES)

    def test_invalid_page_fails_closed(self):
        doc = fitz.open()
        doc.new_page(width=100, height=100)
        with self.assertRaises(ValueError):
            ocr_page(doc, 2)

    @patch("ocr_vector_adapter.subprocess.run")
    @patch("ocr_vector_adapter.shutil.which", return_value="/usr/bin/tesseract")
    def test_ocr_output_is_only_unverified_text_evidence(self, _which, run):
        run.return_value = subprocess.CompletedProcess(
            args=["tesseract"], returncode=0, stdout=TSV, stderr=""
        )
        doc = fitz.open()
        doc.new_page(width=300, height=300)

        result = ocr_page(doc, 1, dpi=216)

        self.assertEqual(result["schema"], "pdf2kicad.ocr-evidence/1")
        self.assertEqual(result["ocr_word_count"], 2)
        self.assertEqual(result["refdes_candidate_count"], 1)
        self.assertEqual(result["refdes_candidates"][0]["candidate"], "R12")
        self.assertEqual(
            result["refdes_candidates"][0]["status"], "UNVERIFIED_OCR_CANDIDATE"
        )
        self.assertEqual(result["electrical_connectivity"], "NOT_INFERRED")
        self.assertEqual(result["refdes_candidates"][0]["bbox_pt"], [24.0, 36.0, 8.0, 4.0])
        run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
