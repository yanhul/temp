"""Conservative PDF page profiling. Classifies extraction shape, not electrical meaning."""
from dataclasses import dataclass, asdict

@dataclass(frozen=True)
class PageProfile:
    kind: str
    confidence: str
    text_lines: int
    tokens: int
    pi_tokens: int
    vector_objects: int
    rectangles: int
    vector_segments: int
    images: int
    reasons: tuple
    next_action: str
    def as_dict(self):
        d = asdict(self); d["reasons"] = list(self.reasons); return d

def profile_page(page):
    texts = page.get("texts") or []; tokens = page.get("tokens") or []
    objs = page.get("objs") or []; rects = page.get("rects") or []
    images = int(page.get("image_count", 0) or 0)
    pi = sum(1 for row in texts if str(row[0]).strip().startswith("PI"))
    segs = sum(max(0, len(o.get("pts") or []) - 1) for o in objs)
    if pi >= 12 and len(objs) > 20:
        kind, conf, reason, action = "smart_pdf_candidate", "medium", "PI-like tokens and vector geometry present", "Smart-PDF decoder; independently verify pins and connectivity."
    elif images and len(texts) < 4 and len(objs) < 20:
        kind, conf, reason, action = "image_scan_candidate", "high", "Image-dominant page with little extractable text/vector geometry", "OCR/layout extraction and human review; no automatic netlist."
    elif images and (len(texts) >= 4 or len(objs) >= 20):
        kind, conf, reason, action = "hybrid_pdf_candidate", "medium", "Embedded images and extractable text/vector geometry both present", "Combine image/vector evidence and deduplicate."
    elif len(objs) >= 20 and (len(texts) >= 4 or len(tokens) >= 4):
        kind, conf, reason, action = "flattened_vector_text_candidate", "medium", "Vector geometry and text without expected PI encoding", "Vector/text recognition; connectivity remains unverified."
    elif len(objs) >= 20:
        kind, conf, reason, action = "vector_only_candidate", "low", "Many vectors but no usable text; could be a drawing", "Inspect rendered page; do not assume schematic."
    elif len(texts) >= 4 or len(tokens) >= 4:
        kind, conf, reason, action = "text_document_candidate", "low", "Extractable text but weak schematic geometry signature", "Inspect page or search for structured embedded data."
    else:
        kind, conf, reason, action = "unknown_or_non_schematic", "low", "No supported schematic signature found", "Manual inspection; stop automatic conversion."
    return PageProfile(kind, conf, len(texts), len(tokens), pi, len(objs), len(rects), segs, images, (reason,), action)
