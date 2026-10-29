"""Conservative PDF page profiling. Classifies extraction shape, not electrical meaning."""
from dataclasses import dataclass, asdict
import re


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
        d = asdict(self)
        d["reasons"] = list(self["reasons"]) if isinstance(self, dict) else list(d["reasons"])
        return d


def _page_text(texts):
    values = []
    for row in texts:
        if isinstance(row, (list, tuple)) and row:
            values.append(str(row[0]))
        elif isinstance(row, dict):
            values.append(str(row.get("text", "")))
        else:
            values.append(str(row))
    return " ".join(values).casefold()


def _non_schematic_page(text):
    """Use explicit page labels to keep BOM/layout/render pages out of netlist OCR."""
    normalized = re.sub(r"[^a-z0-9]+", " ", text).strip()
    if re.search(r"\b(part list|bill of materials|bom)\b", normalized):
        return ("bom_or_parts_list_candidate", "high",
                "Page title explicitly identifies a parts list/BOM",
                "Preserve as BOM evidence; do not treat as schematic connectivity.")
    if re.search(r"\b(3d view|3d rendering|isometric view)\b", normalized):
        return ("render_or_mechanical_candidate", "high",
                "Page title explicitly identifies a 3D/rendered view",
                "Preserve as visual/mechanical evidence; exclude from netlist extraction.")
    if re.search(r"\b(pcb layout|board layout|layout drawing|layout note)\b", normalized):
        return ("board_layout_candidate", "high",
                "Page title explicitly identifies a board/layout drawing",
                "Preserve as board-layout evidence; exclude from schematic netlist extraction.")
    if re.search(r"\b(label|label drawing|label layout)\b", normalized) and not re.search(r"\b(net label|global label|hierarchical label)\b", normalized):
        return ("label_or_mechanical_candidate", "medium",
                "Page title appears to identify a physical label drawing",
                "Preserve as document evidence; do not infer electrical labels.")
    if re.search(r"\b(drawing structure list|revision history list|table of contents)\b", normalized):
        return ("document_index_candidate", "high",
                "Page text identifies an index/revision-history document",
                "Preserve as document metadata; exclude from schematic extraction.")
    return None


def profile_page(page):
    texts = page.get("texts") or []
    tokens = page.get("tokens") or []
    objs = page.get("objs") or []
    rects = page.get("rects") or []
    images = int(page.get("image_count", 0) or 0)
    pi = sum(1 for row in texts if str(row[0]).strip().startswith("PI"))
    segs = sum(max(0, len(o.get("pts") or []) - 1) for o in objs)
    non_schematic = _non_schematic_page(_page_text(texts))
    if non_schematic:
        kind, conf, reason, action = non_schematic
    elif pi >= 12 and len(objs) > 20:
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
