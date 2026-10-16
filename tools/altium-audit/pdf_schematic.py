#!/usr/bin/env python3
"""Evidence-first PDF -> schematic bridge.

No home-grown PDF schematic parser is implemented here. Existing PDF/OCR tools are
discovered and used; reconstruction is delegated to an external backend. Unsupported
reconstruction is BLOCKED rather than guessed.
"""
from __future__ import annotations
import argparse, hashlib, json, shutil, subprocess
from pathlib import Path

TOOLS = {
    "pdftotext": ["pdftotext"],
    "pdfinfo": ["pdfinfo"],
    "pdftoppm": ["pdftoppm"],
    "tesseract": ["tesseract"],
    "kicad-cli": ["kicad-cli", "kicad-cli.exe"],
    "eeschema": ["eeschema", "eeschema.exe"],
}

def find_tool(names):
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    return None

def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def run(cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--backend", help="External reconstruction command. Receives {pdf} {out} {manifest}.")
    a = ap.parse_args()
    pdf, out = a.pdf.resolve(), a.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if not pdf.is_file() or pdf.suffix.lower() != ".pdf":
        raise SystemExit("input must be an existing .pdf")

    tools = {k: find_tool(v) for k, v in TOOLS.items()}
    manifest = {
        "schema": "pdf-schematic-bridge.v1",
        "input": {"path": str(pdf), "sha256": sha256(pdf)},
        "tools": tools,
        "stages": {},
        "status": "UNKNOWN",
    }

    if tools["pdfinfo"]:
        r = run([tools["pdfinfo"], str(pdf)])
        (out / "pdfinfo.txt").write_text(r.stdout + r.stderr, encoding="utf-8")
        manifest["stages"]["inspect"] = {"status": "VERIFIED" if r.returncode == 0 else "FAIL"}
    else:
        manifest["stages"]["inspect"] = {"status": "BLOCKED", "reason": "pdfinfo not installed"}

    if tools["pdftotext"]:
        r = run([tools["pdftotext"], "-layout", str(pdf), str(out / "source.txt")])
        manifest["stages"]["text_extract"] = {
            "status": "VERIFIED" if r.returncode == 0 else "FAIL",
            "tool": tools["pdftotext"],
        }
    else:
        manifest["stages"]["text_extract"] = {"status": "BLOCKED", "reason": "pdftotext not installed"}

    if tools["pdftoppm"]:
        r = run([tools["pdftoppm"], "-png", "-r", "300", str(pdf), str(out / "page")])
        manifest["stages"]["render"] = {
            "status": "VERIFIED" if r.returncode == 0 else "FAIL",
            "tool": tools["pdftoppm"],
        }
    else:
        manifest["stages"]["render"] = {"status": "BLOCKED", "reason": "pdftoppm not installed"}

    if tools["tesseract"]:
        pages = sorted(out.glob("page-*.png"))
        completed = 0
        for page in pages:
            r = run([tools["tesseract"], str(page), str(page.with_suffix("")), "--dpi", "300"])
            completed += r.returncode == 0
        manifest["stages"]["ocr"] = {
            "status": "VERIFIED" if pages and completed == len(pages) else ("INCOMPLETE" if pages else "BLOCKED"),
            "pages": len(pages),
            "completed": completed,
            "tool": tools["tesseract"],
        }
    else:
        manifest["stages"]["ocr"] = {"status": "BLOCKED", "reason": "tesseract not installed"}

    if a.backend:
        cmd = a.backend.format(pdf=str(pdf), out=str(out), manifest=str(out / "manifest.json"))
        r = subprocess.run(cmd, shell=True, cwd=out, text=True, capture_output=True)
        manifest["stages"]["reconstruction"] = {
            "status": "VERIFIED" if r.returncode == 0 else "FAIL",
            "command": cmd,
            "stdout": r.stdout[-4000:],
            "stderr": r.stderr[-4000:],
        }
    else:
        manifest["stages"]["reconstruction"] = {
            "status": "BLOCKED",
            "reason": "no authoritative PDF-to-schematic reconstruction backend configured",
        }

    sch = next(out.glob("*.kicad_sch"), None)
    kicad = tools["kicad-cli"] or tools["eeschema"]
    if sch and kicad:
        if tools["kicad-cli"]:
            r = run([tools["kicad-cli"], "sch", "export", "pdf", str(sch), "-o", str(out / "kicad-verify.pdf")])
        else:
            r = run([kicad, str(sch)])
        manifest["stages"]["kicad"] = {
            "status": "VERIFIED" if r.returncode == 0 else "FAIL",
            "tool": kicad,
            "schematic": str(sch),
        }
    else:
        manifest["stages"]["kicad"] = {
            "status": "BLOCKED",
            "reason": "no reconstructed .kicad_sch and KiCad executable available",
        }

    manifest["status"] = "VERIFIED" if (
        manifest["stages"]["reconstruction"]["status"] == "VERIFIED"
        and manifest["stages"]["kicad"]["status"] == "VERIFIED"
    ) else "BLOCKED"
    manifest["terminal_reason"] = (
        "PDF reconstructed and KiCad verification completed"
        if manifest["status"] == "VERIFIED"
        else "required authoritative reconstruction/verification evidence is missing"
    )
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0 if manifest["status"] == "VERIFIED" else 1

if __name__ == "__main__":
    raise SystemExit(main())
