from pathlib import Path

source = Path("colibri/c/setup_download.py")
text = source.read_text(encoding="utf-8")

replacements = [
    (
'''    size = int(spec["size"])
    if os.path.exists(dest) and os.path.getsize(dest) == size:
        return "present"
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)''',
'''    size = int(spec["size"])
    hasher, expected = _hasher(spec) if verify else (None, None)
    if verify and hasher is None:
        raise DownloadError(f"{os.path.basename(dest)}: missing supported hash metadata; refusing unverified file")
    if os.path.exists(dest) and os.path.getsize(dest) == size:
        if not verify or verify_file(dest, spec):
            return "present"
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)'''
    ),
    (
'''    hasher, expected = _hasher(spec) if verify else (None, None)
    if hasher is not None and have:''',
'''    if hasher is not None and have:'''
    ),
    (
'''    hasher, expected = _hasher(spec)
    if hasher is None:
        return True''',
'''    hasher, expected = _hasher(spec)
    if hasher is None:
        return False'''
    ),
    (
'''    size = int(spec["size"])
    if os.path.exists(dest) and os.path.getsize(dest) == size:
        return "present"
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)''',
'''    size = int(spec["size"])
    if verify and _hasher(spec)[0] is None:
        raise DownloadError(f"{os.path.basename(dest)}: missing supported hash metadata; refusing unverified file")
    if os.path.exists(dest) and os.path.getsize(dest) == size:
        if not verify or verify_file(dest, spec):
            return "present"
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)'''
    ),
    (
'''def is_complete(model_dir):
    """The folder holds every file the manifest lists, at its size."""''',
'''def is_complete(model_dir):
    """The folder holds every manifest file with its expected size and hash."""'''
    ),
    (
'''        if not os.path.exists(path) or os.path.getsize(path) != int(spec["size"]):
            return False''',
'''        if not verify_file(path, spec):
            return False'''
    ),
    (
'''    manifest = {"repo": repo, "revision": revision, "complete": False,
                "files": [{"path": s["path"], "size": s["size"]} for s in files]}''',
'''    manifest = {"repo": repo, "revision": revision, "complete": False,
                "files": [{"path": s["path"], "size": s["size"],
                           "sha256": s.get("sha256"), "git_oid": s.get("git_oid")}
                          for s in files]}'''
    ),
]
for old, new in replacements:
    if old not in text:
        raise SystemExit("Patch refused: expected source fragment not found:\\n" + old)
    text = text.replace(old, new, 1)
source.write_text(text, encoding="utf-8")
print("Applied fail-closed Colibri integrity patch.")
