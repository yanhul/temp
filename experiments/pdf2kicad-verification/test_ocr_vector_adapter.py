import unittest
import fitz
from ocr_vector_adapter import ocr_page


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


if __name__ == "__main__":
    unittest.main()
