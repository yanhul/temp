"""Run the optional SchematicNetlist vector-PDF backend without trusting it as ground truth.

This adapter preserves its artifacts/log and reports extraction status separately from
verified topology. A successful process exit is not a verified KiCad conversion.
"""
from __future__ import annotations
import json
import shutil
import subprocess
from pathlib import Path


def run_backend(pdf_path: str, out_dir: str, pages: str = "") -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    exe = shutil.which("schematic-netlist")
    if not exe:
        result = {
            "schema": "pdf2kicad.external-backend/1",
            "backend": "SchematicNetlist",
            "status": "UNAVAILABLE",
            "reason": "schematic-netlist executable not installed",
            "verified_netlist": False,
            "verified_kicad": False,
        }
        (out / "external_backend_manifest.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8")
        return result

    cmd = [exe, "analyze", str(Path(pdf_path).resolve()), "-o", str(out.resolve()),
           "--no-excel", "--no-spice", "--no-cache"]
    if pages:
        cmd += ["--pages", pages]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900, check=False)
        (out / "external_backend_stdout.txt").write_text(proc.stdout, encoding="utf-8")
        (out / "external_backend_stderr.txt").write_text(proc.stderr, encoding="utf-8")
        outputs = sorted(p.name for p in out.iterdir()
                         if p.is_file() and p.name not in {
                             "external_backend_manifest.json",
                             "external_backend_stdout.txt",
                             "external_backend_stderr.txt"})
        result = {
            "schema": "pdf2kicad.external-backend/1",
            "backend": "SchematicNetlist",
            "command": cmd,
            "returncode": proc.returncode,
            "status": "EXTRACTED_UNVERIFIED" if proc.returncode == 0 else "FAILED",
            "outputs": outputs,
            "verified_netlist": False,
            "verified_kicad": False,
            "warning": "Backend output is derived from drawing geometry; inspect warnings and compare pin-to-net topology to independently reviewed ground truth.",
        }
    except subprocess.TimeoutExpired as exc:
        result = {"schema": "pdf2kicad.external-backend/1", "backend": "SchematicNetlist",
                  "status": "TIMEOUT", "timeout_seconds": 900,
                  "verified_netlist": False, "verified_kicad": False}
        (out / "external_backend_stderr.txt").write_text(str(exc), encoding="utf-8")
    (out / "external_backend_manifest.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result
