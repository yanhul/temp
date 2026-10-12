import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "colibri" / "c"))
import setup_download


class DownloadIntegrityRegression(unittest.TestCase):
    def test_existing_same_size_corrupt_file_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "model.bin"
            path.write_bytes(b"EVIL")
            spec = {"size": 4, "sha256": hashlib.sha256(b"GOOD").hexdigest()}
            self.assertFalse(setup_download.verify_file(str(path), spec))
            # A matching size must not bypass digest verification.
            with self.assertRaises(setup_download.DownloadError):
                setup_download.download_file(
                    "https://invalid.example/model.bin", str(path), spec,
                    opener=lambda *a, **k: (_ for _ in ()).throw(
                        setup_download.DownloadError("forced offline after rejecting fast path"))
                )
            self.assertEqual(path.read_bytes(), b"EVIL")

    def test_missing_hash_metadata_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "model.bin"
            path.write_bytes(b"DATA")
            self.assertFalse(setup_download.verify_file(str(path), {"size": 4}))

    def test_manifest_completion_rechecks_hash_not_only_size(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "model.bin"
            path.write_bytes(b"GOOD")
            import json
            (root / setup_download.MANIFEST).write_text(json.dumps({
                "complete": True,
                "files": [{"path": "model.bin", "size": 4,
                           "sha256": hashlib.sha256(b"GOOD").hexdigest(),
                           "git_oid": None}],
            }))
            self.assertTrue(setup_download.is_complete(str(root)))
            path.write_bytes(b"EVIL")
            self.assertFalse(setup_download.is_complete(str(root)))

    def test_windows_fast_path_does_not_accept_same_size_corruption(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "model.bin"
            path.write_bytes(b"EVIL")
            spec = {"size": 4, "sha256": hashlib.sha256(b"GOOD").hexdigest()}
            from unittest.mock import patch
            with patch.object(setup_download, "wsl_windows_path", return_value=None) as translate:
                with self.assertRaises(setup_download.DownloadError):
                    setup_download.download_file_windows(
                        "https://invalid.example/model.bin", str(path), spec, "curl.exe"
                    )
                # If the same-size file were incorrectly accepted as present, the
                # Windows path translator would never be reached.
                translate.assert_called_once()
            self.assertEqual(path.read_bytes(), b"EVIL")


if __name__ == "__main__":
    unittest.main(verbosity=2)
