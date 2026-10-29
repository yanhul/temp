#!/usr/bin/env python3
"""Reconstruct and verify the committed base64-part source archive.

The repository intentionally stores the archive as ordered text chunks rather
than a binary ZIP at the repository root. The chunk set is the source of truth;
if a named reference ZIP is present, it must match byte-for-byte.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import zipfile
from pathlib import Path, PurePosixPath


def reconstruct(parts_dir: Path, reference_archive: Path, output_archive: Path,
                output_sha256: Path, output_provenance: Path, commit_sha: str = "") -> dict:
    parts = sorted(parts_dir.glob("part_*.txt"))
    if not parts:
        raise ValueError(f"no part_*.txt files found in {parts_dir}")

    indexed = []
    for part in parts:
        match = re.fullmatch(r"part_(\d{4,})\.txt", part.name)
        if not match:
            raise ValueError(f"invalid chunk filename: {part.name}")
        indexed.append((int(match.group(1)), part))
    indexed.sort(key=lambda item: item[0])
    numbers = [number for number, _ in indexed]
    expected = list(range(len(indexed)))
    if numbers != expected:
        raise ValueError(f"chunk sequence has gaps or duplicates: expected 0..{len(indexed)-1}, got {numbers}")

    encoded = b"".join(path.read_bytes().strip() for _, path in indexed)
    try:
        archive_bytes = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise ValueError(f"base64 chunk stream is invalid: {exc}") from exc
    if not archive_bytes:
        raise ValueError("decoded source archive is empty")

    output_archive.parent.mkdir(parents=True, exist_ok=True)
    output_archive.write_bytes(archive_bytes)
    try:
        with zipfile.ZipFile(output_archive) as archive:
            bad_member = archive.testzip()
            if bad_member:
                raise ValueError(f"ZIP CRC check failed for {bad_member}")
            members = [name for name in archive.namelist() if not name.endswith("/")]
            for name in members:
                path = PurePosixPath(name)
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError(f"unsafe archive member path: {name}")
            suffixes = [PurePosixPath(name).suffix.lower() for name in members]
    except zipfile.BadZipFile as exc:
        raise ValueError(f"decoded source is not a valid ZIP: {exc}") from exc

    counts = {
        "PrjPcb": sum(suffix == ".prjpcb" for suffix in suffixes),
        "SchDoc": sum(suffix == ".schdoc" for suffix in suffixes),
        "PcbDoc": sum(suffix == ".pcbdoc" for suffix in suffixes),
    }
    if counts["SchDoc"] != 1 or counts["PcbDoc"] != 1 or counts["PrjPcb"] > 1:
        raise ValueError(f"source archive input contract failed: {counts}")

    digest = hashlib.sha256(archive_bytes).hexdigest()
    reference_present = reference_archive.is_file()
    if reference_present and reference_archive.read_bytes() != archive_bytes:
        raise ValueError(f"reconstructed archive does not match reference archive: {reference_archive}")

    output_sha256.parent.mkdir(parents=True, exist_ok=True)
    output_sha256.write_text(digest + "\n", encoding="ascii")
    provenance = {
        "schema": "altium-audit/source-provenance/v1",
        "status": "VERIFIED",
        "verification_mode": "REFERENCE_ARCHIVE_BYTE_MATCH" if reference_present else "RECONSTRUCTED_FROM_COMMITTED_BASE64_PARTS",
        "commit_sha": commit_sha or None,
        "source_label": reference_archive.name,
        "reference_archive_present": reference_present,
        "chunk_count": len(indexed),
        "chunk_names": [path.name for _, path in indexed],
        "archive_bytes": len(archive_bytes),
        "archive_sha256": digest,
        "input_counts": counts,
    }
    output_provenance.parent.mkdir(parents=True, exist_ok=True)
    output_provenance.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(provenance, indent=2, sort_keys=True))
    return provenance


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--sha256", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--commit-sha", default="")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    parts_dir = Path(config.get("base64_parts_dir", "b64parts"))
    reference = Path(config["source_archive"])
    reconstruct(parts_dir, reference, args.archive, args.sha256, args.provenance, args.commit_sha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
