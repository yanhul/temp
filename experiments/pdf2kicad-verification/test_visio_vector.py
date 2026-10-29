import unittest
import fitz
from visio_vector import extract_vector_page


class VectorEvidenceTests(unittest.TestCase):
    def test_text_and_geometry_are_preserved_without_net_claim(self):
        doc = fitz.open()
        page = doc.new_page(width=100, height=100)
        page.draw_line((10, 10), (50, 10), color=(0, 0, 0), width=0.5)
        page.draw_line((50, 10), (50, 40), color=(0, 0, 0), width=0.5)
        page.insert_text((12, 8), "R1")
        result = extract_vector_page(doc, 0)
        self.assertEqual(result["electrical_connectivity"], "NOT_INFERRED")
        self.assertGreaterEqual(result["summary"]["lines_over_min_length"], 2)
        self.assertTrue(any(w["text"] == "R1" for w in result["text_words"]))

    def test_page_number_is_one_based(self):
        doc = fitz.open()
        doc.new_page(width=100, height=100)
        self.assertEqual(extract_vector_page(doc, 0)["page_1based"], 1)


if __name__ == "__main__":
    unittest.main()
