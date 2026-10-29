import unittest
from pdf_profile import profile_page


class ProfileTests(unittest.TestCase):
    def p(self, **kw):
        d = {"texts": [], "tokens": [], "objs": [], "rects": [], "image_count": 0}
        d.update(kw)
        return profile_page(d)

    def test_smart(self):
        self.assertEqual(self.p(texts=[("PI" + str(i), 0, 0, True) for i in range(12)],
                                objs=[{"pts": [(0, 0), (1, 1)]}] * 21).kind,
                         "smart_pdf_candidate")

    def test_scan(self):
        self.assertEqual(self.p(image_count=1).kind, "image_scan_candidate")

    def test_hybrid(self):
        self.assertEqual(self.p(image_count=1, texts=[("R1", 0, 0, True)] * 4).kind,
                         "hybrid_pdf_candidate")

    def test_flattened(self):
        self.assertEqual(self.p(texts=[("R1", 0, 0, True)] * 4,
                                objs=[{"pts": [(0, 0), (1, 1)]}] * 20).kind,
                         "flattened_vector_text_candidate")

    def test_vector_only_not_asserted_schematic(self):
        self.assertEqual(self.p(objs=[{"pts": [(0, 0), (1, 1)]}] * 20).kind,
                         "vector_only_candidate")

    def test_unknown(self):
        self.assertEqual(self.p().kind, "unknown_or_non_schematic")

    def test_bom_excluded_from_schematic_candidates(self):
        profile = self.p(texts=[("Part list 1", 0, 0, True)],
                         objs=[{"pts": [(0, 0), (1, 1)]}] * 50)
        self.assertEqual(profile.kind, "bom_or_parts_list_candidate")

    def test_board_layout_excluded(self):
        profile = self.p(texts=[("Layout", 0, 0, True), ("Note Unit mm", 0, 0, True)],
                         objs=[{"pts": [(0, 0), (1, 1)]}] * 50)
        self.assertEqual(profile.kind, "board_layout_candidate")

    def test_3d_view_excluded(self):
        profile = self.p(texts=[("3D View", 0, 0, True)],
                         objs=[{"pts": [(0, 0), (1, 1)]}] * 50)
        self.assertEqual(profile.kind, "render_or_mechanical_candidate")

    def test_actual_document_page_titles(self):
        cases = [
            (["Part list 1"], "bom_or_parts_list_candidate"),
            (["Layout Note - Unit: mm"], "board_layout_candidate"),
            (["3D View Note - Unit: mm"], "render_or_mechanical_candidate"),
            (["Label Note - Unit: mm"], "label_or_mechanical_candidate"),
            (["Drawing Structure List Revision History List"], "document_index_candidate"),
        ]
        for texts, expected in cases:
            with self.subTest(texts=texts):
                profile = self.p(texts=[(value, 0, 0, True) for value in texts],
                                 objs=[{"pts": [(0, 0), (1, 1)]}] * 50)
                self.assertEqual(profile.kind, expected)

    def test_label_page_not_electrical_label(self):
        profile = self.p(texts=[("Label", 0, 0, True)],
                         objs=[{"pts": [(0, 0), (1, 1)]}] * 50)
        self.assertEqual(profile.kind, "label_or_mechanical_candidate")


if __name__ == "__main__":
    unittest.main()
