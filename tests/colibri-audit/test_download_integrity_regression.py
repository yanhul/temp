import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "colibri" / "c"))
import setup_download


def manifest(root, *, files=None, repo="org/model", revision="abc123", complete=True):
    (root / setup_download.MANIFEST).write_text(json.dumps({
        "repo": repo, "revision": revision, "complete": complete,
        **({"files": files} if files is not None else {}),
    }), encoding="utf-8")


def file_spec(path="model.bin", data=b"GOOD"):
    return {"path": path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "git_oid": None}


class DownloadIntegrityRegression(unittest.TestCase):
    def test_existing_same_size_corrupt_file_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "model.bin"
            path.write_bytes(b"EVIL")
            spec = file_spec(data=b"GOOD")
            self.assertFalse(setup_download.verify_file(str(path), spec))
            with self.assertRaises(setup_download.DownloadError):
                setup_download.download_file("https://invalid.example/model.bin", str(path), spec,
                    opener=lambda *a, **k: (_ for _ in ()).throw(
                        setup_download.DownloadError("offline after fast-path rejection")))
            self.assertEqual(path.read_bytes(), b"EVIL")

    def test_missing_hash_metadata_fails_closed_on_both_downloaders(self):
        spec = {"size": 4}
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "model.bin"
            path.write_bytes(b"DATA")
            self.assertFalse(setup_download.verify_file(str(path), spec))
            with self.assertRaises(setup_download.DownloadError):
                setup_download.download_file("https://invalid.example/model.bin", str(path), spec)
            with patch.object(setup_download, "wsl_windows_path") as translate:
                with self.assertRaises(setup_download.DownloadError):
                    setup_download.download_file_windows(
                        "https://invalid.example/model.bin", str(path), spec, "curl.exe")
                translate.assert_not_called()

    def test_manifest_completion_rechecks_digest(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "model.bin").write_bytes(b"GOOD")
            manifest(root, files=[file_spec()])
            self.assertTrue(setup_download.is_complete(str(root), "org/model", "abc123"))
            (root / "model.bin").write_bytes(b"EVIL")
            self.assertFalse(setup_download.is_complete(str(root), "org/model", "abc123"))

    def test_manifest_missing_files_is_incomplete(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest(root)
            self.assertFalse(setup_download.is_complete(str(root)))

    def test_manifest_empty_files_is_incomplete(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest(root, files=[])
            self.assertFalse(setup_download.is_complete(str(root)))

    def test_manifest_identity_mismatch_is_incomplete(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "model.bin").write_bytes(b"GOOD")
            manifest(root, files=[file_spec()])
            self.assertFalse(setup_download.is_complete(str(root), "other/model", "abc123"))
            self.assertFalse(setup_download.is_complete(str(root), "org/model", "different-revision"))

    def test_manifest_invalid_file_entry_and_duplicate_paths_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest(root, files=[None])
            self.assertFalse(setup_download.is_complete(str(root)))
            manifest(root, files=[file_spec(), file_spec()])
            self.assertFalse(setup_download.is_complete(str(root)))

    def test_manifest_path_traversal_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest(root, files=[file_spec(path="../outside")])
            self.assertFalse(setup_download.is_complete(str(root)))

    def test_windows_fast_path_rejects_same_size_corruption(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "model.bin"
            path.write_bytes(b"EVIL")
            spec = file_spec(data=b"GOOD")
            with patch.object(setup_download, "wsl_windows_path", return_value=None) as translate:
                with self.assertRaises(setup_download.DownloadError):
                    setup_download.download_file_windows(
                        "https://invalid.example/model.bin", str(path), spec, "curl.exe")
                translate.assert_called_once()
            self.assertEqual(path.read_bytes(), b"EVIL")

    def test_verifier_rejects_symlink_even_when_target_hash_matches(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "target.bin"
            link = root / "link.bin"
            target.write_bytes(b"GOOD")
            spec = file_spec(data=b"GOOD")
            try:
                os.symlink(target, link)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable on this runner")
            self.assertFalse(setup_download.verify_file(str(link), spec))

    def test_git_blob_oid_alone_is_not_accepted_as_supported_integrity_metadata(self):
        data = b"plain file"
        oid = hashlib.sha1(b"blob %d\\0" % len(data) + data).hexdigest()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "plain.txt"
            path.write_bytes(data)
            self.assertFalse(setup_download.verify_file(
                str(path), {"size": len(data), "git_oid": oid}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
