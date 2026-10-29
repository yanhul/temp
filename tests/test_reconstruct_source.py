import base64
import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "altium-audit"))
from reconstruct_source import reconstruct


def make_archive(path: Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("project/design.PrjPcb", "project")
        z.writestr("project/design.SchDoc", "schematic")
        z.writestr("project/design.PcbDoc", "board")
    return path.read_bytes()


def write_parts(parts_dir: Path, data: bytes, chunk_size: int = 12) -> None:
    parts_dir.mkdir(parents=True, exist_ok=True)
    encoded = base64.b64encode(data)
    chunks = [encoded[i:i + chunk_size] for i in range(0, len(encoded), chunk_size)]
    for index, chunk in enumerate(chunks):
        (parts_dir / f"part_{index:04d}.txt").write_bytes(chunk + b"\n")


def test_reconstructs_ordered_chunks_and_emits_sha_and_provenance(tmp_path):
    source = make_archive(tmp_path / "fixture.zip")
    parts = tmp_path / "parts"
    write_parts(parts, source)
    sha_path = tmp_path / "out/source.sha256"
    provenance_path = tmp_path / "out/source-provenance.json"
    out = tmp_path / "out/source.zip"

    provenance = reconstruct(parts, tmp_path / "missing-reference.zip", out, sha_path, provenance_path, "abc123")

    assert out.read_bytes() == source
    assert sha_path.read_text().strip() == provenance["archive_sha256"]
    assert provenance["status"] == "VERIFIED"
    assert provenance["verification_mode"] == "RECONSTRUCTED_FROM_COMMITTED_BASE64_PARTS"
    assert provenance["chunk_count"] > 1
    assert json.loads(provenance_path.read_text())["commit_sha"] == "abc123"


def test_rejects_missing_chunk_instead_of_silently_building_corrupt_archive(tmp_path):
    source = make_archive(tmp_path / "fixture.zip")
    parts = tmp_path / "parts"
    write_parts(parts, source, chunk_size=12)
    (parts / "part_0001.txt").unlink()

    with pytest.raises(ValueError, match="gaps or duplicates"):
        reconstruct(parts, tmp_path / "missing.zip", tmp_path / "out/source.zip",
                    tmp_path / "out/source.sha256", tmp_path / "out/provenance.json")


def test_reference_archive_must_match_when_present(tmp_path):
    source = make_archive(tmp_path / "fixture.zip")
    parts = tmp_path / "parts"
    write_parts(parts, source)
    reference = tmp_path / "reference.zip"
    reference.write_bytes(source + b"tampered")

    with pytest.raises(ValueError, match="does not match reference archive"):
        reconstruct(parts, reference, tmp_path / "out/source.zip",
                    tmp_path / "out/source.sha256", tmp_path / "out/provenance.json")


def test_rejects_non_zip_payload(tmp_path):
    parts = tmp_path / "parts"
    write_parts(parts, b"not a zip")

    with pytest.raises(ValueError, match="not a valid ZIP"):
        reconstruct(parts, tmp_path / "missing.zip", tmp_path / "out/source.zip",
                    tmp_path / "out/source.sha256", tmp_path / "out/provenance.json")
