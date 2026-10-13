from pathlib import Path

DOWNLOAD = Path("colibri/c/setup_download.py")
FLOW = Path("colibri/c/setup_flow.py")


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"Patch refused for {label}: expected exactly one source fragment, found {count}")
    return text.replace(old, new, 1)


text = DOWNLOAD.read_text(encoding="utf-8")
text = replace_once(
    text,
'''    size = int(spec["size"])
    if os.path.exists(dest) and os.path.getsize(dest) == size:
        return "present"
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)''',
'''    size = int(spec["size"])
    hasher, expected = _hasher(spec) if verify else (None, None)
    if verify and hasher is None:
        raise DownloadError(f"{os.path.basename(dest)}: missing supported hash metadata")
    if os.path.exists(dest) and os.path.getsize(dest) == size:
        if not verify or verify_file(dest, spec):
            return "present"
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)''',
"Linux downloader fast path")
text = replace_once(
    text,
'''    hasher, expected = _hasher(spec) if verify else (None, None)
    if hasher is not None and have:''',
'''    if hasher is not None and have:''',
"Linux downloader hasher initialization")
text = replace_once(
    text,
'''def verify_file(path, spec):
    """Size and hash of a file someone else wrote (curl.exe)."""
    if not os.path.exists(path) or os.path.getsize(path) != int(spec["size"]):
        return False
    hasher, expected = _hasher(spec)
    if hasher is None:
        return True
    _feed_prefix(hasher, path, int(spec["size"]))
    return hasher.hexdigest() == expected''',
'''def verify_file(path, spec):
    """Fail closed unless a stable, exact-size file matches trusted hash metadata."""
    try:
        expected_size = int(spec["size"])
        if expected_size < 0:
            return False
        hasher, expected = _hasher(spec)
        if hasher is None or not expected:
            return False
        before = os.stat(path, follow_symlinks=False)
        if not os.path.isfile(path) or before.st_size != expected_size:
            return False
        read = 0
        with open(path, "rb") as handle:
            while True:
                block = handle.read(CHUNK * 8)
                if not block:
                    break
                read += len(block)
                if read > expected_size:
                    return False
                hasher.update(block)
        after = os.stat(path, follow_symlinks=False)
        return (read == expected_size and before.st_size == after.st_size
                and before.st_mtime_ns == after.st_mtime_ns
                and before.st_ino == after.st_ino
                and hasher.hexdigest() == expected)
    except (OSError, TypeError, ValueError, KeyError):
        return False''',
"stable full-file verification")
text = replace_once(
    text,
'''    size = int(spec["size"])
    if os.path.exists(dest) and os.path.getsize(dest) == size:
        return "present"
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)''',
'''    size = int(spec["size"])
    if verify and _hasher(spec)[0] is None:
        raise DownloadError(f"{os.path.basename(dest)}: missing supported hash metadata")
    if os.path.exists(dest) and os.path.getsize(dest) == size:
        if not verify or verify_file(dest, spec):
            return "present"
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)''',
"Windows downloader fast path")
text = replace_once(
    text,
'''def is_complete(model_dir):
    """The folder holds every file the manifest lists, at its size."""
    manifest = read_manifest(model_dir)
    if not manifest or not manifest.get("complete"):
        return False
    for spec in manifest.get("files", []):
        path = safe_join(model_dir, spec["path"])
        if not os.path.exists(path) or os.path.getsize(path) != int(spec["size"]):
            return False
    return True''',
'''def is_complete(model_dir, repo=None, revision=None):
    """Validate manifest schema, requested identity, and every file digest."""
    manifest = read_manifest(model_dir)
    if not isinstance(manifest, dict) or manifest.get("complete") is not True:
        return False
    if not isinstance(manifest.get("repo"), str) or not manifest["repo"]:
        return False
    if not isinstance(manifest.get("revision"), str) or not manifest["revision"]:
        return False
    if repo is not None and manifest["repo"] != repo:
        return False
    if revision is not None and manifest["revision"] != revision:
        return False
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        return False
    seen = set()
    for spec in files:
        if not isinstance(spec, dict):
            return False
        relative = spec.get("path")
        if not isinstance(relative, str) or not relative or relative in seen:
            return False
        seen.add(relative)
        try:
            if not isinstance(spec.get("size"), int) or isinstance(spec.get("size"), bool):
                return False
            if spec["size"] < 0 or _hasher(spec)[0] is None:
                return False
            path = safe_join(model_dir, relative)
        except (DownloadError, TypeError, ValueError, KeyError):
            return False
        if not verify_file(path, spec):
            return False
    return True''',
"manifest completion validation")
text = replace_once(
    text,
'''    manifest = {"repo": repo, "revision": revision, "complete": False,
                "files": [{"path": s["path"], "size": s["size"]} for s in files]}''',
'''    manifest = {"repo": repo, "revision": revision, "complete": False,
                "files": [{"path": s["path"], "size": s["size"],
                           "sha256": s.get("sha256"), "git_oid": s.get("git_oid")}
                          for s in files]}''',
"manifest integrity metadata")
DOWNLOAD.write_text(text, encoding="utf-8")

flow = FLOW.read_text(encoding="utf-8")
flow = replace_once(
    flow,
'''    if (cfg.get("model") or {}).get("repo") and not setup_download.is_complete(cfg["model_dir"]):
        return False''',
'''    model = cfg.get("model") or {}
    if model.get("repo") and not setup_download.is_complete(
            cfg["model_dir"], model.get("repo"), model.get("revision")):
        return False''',
"configured-model identity check")
flow = replace_once(
    flow,
'''        if setup_download.is_complete(model_dir):
            ui.say("\\nDownload: already complete")''',
'''        if setup_download.is_complete(model_dir, entry.repo, entry.revision):
            ui.say("\\nDownload: already complete")''',
"setup fast-path identity check")
FLOW.write_text(flow, encoding="utf-8")
print("Applied strict Colibri integrity hardening to isolated checkout.")
