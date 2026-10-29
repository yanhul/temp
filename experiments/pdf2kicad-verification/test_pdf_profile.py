import unittest
from pdf_profile import profile_page
class ProfileTests(unittest.TestCase):
 def p(self, **kw):
  d={"texts":[],"tokens":[],"objs":[],"rects":[],"image_count":0}; d.update(kw); return profile_page(d)
 def test_smart(self): self.assertEqual(self.p(texts=[("PI"+str(i),0,0,True) for i in range(12)],objs=[{"pts":[(0,0),(1,1)]}]*21).kind,"smart_pdf_candidate")
 def test_scan(self): self.assertEqual(self.p(image_count=1).kind,"image_scan_candidate")
 def test_hybrid(self): self.assertEqual(self.p(image_count=1,texts=[("R1",0,0,True)]*4).kind,"hybrid_pdf_candidate")
 def test_flattened(self): self.assertEqual(self.p(texts=[("R1",0,0,True)]*4,objs=[{"pts":[(0,0),(1,1)]}]*20).kind,"flattened_vector_text_candidate")
 def test_vector_only_not_asserted_schematic(self): self.assertEqual(self.p(objs=[{"pts":[(0,0),(1,1)]}]*20).kind,"vector_only_candidate")
 def test_unknown(self): self.assertEqual(self.p().kind,"unknown_or_non_schematic")
if __name__=="__main__": unittest.main()
