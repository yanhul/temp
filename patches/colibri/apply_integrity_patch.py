from pathlib import Path

DOWNLOAD = Path("colibri/c/setup_download.py")
FLOW = Path("colibri/c/setup_flow.py")


def replace_once(text, old, new, label, *, allow_multiple=False):
    count = text.count(old)
    if count != 1 and not (allow_multiple and count > 1):
        raise SystemExit(f"Patch refused for {label}: expected exactly one source fragment, found {count}")
    return text.replace(old, new, 1)


text = DOWNLOAD.read_text(encoding="utf-8")
text = replace_once(text, "import shutil\nimport subprocess", "import shutil\nimport stat\nimport subprocess", "regular-file mode import")
text = replace_once(
    text,
'''    if spec.get("sha256"):
        return hashlib.sha256(), spec["sha256"].lower()''',
'''    if spec.get("sha256"):
        if not isinstance(spec["sha256"], str):
            return None, None
        digest = spec["sha256"].lower()
        if digest.startswith("sha256:"):
            digest = digest[len("sha256:"):]
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            return None, None
        return hashlib.sha256(), digest''',
"normalize and validate Hugging Face LFS sha256 oid")
text = replace_once(
    text,
'''    if spec.get("git_oid"):
        sha1 = hashlib.sha1()''',
'''    if spec.get("git_oid"):
        if not isinstance(spec["git_oid"], str) or not re.fullmatch(r"[0-9a-fA-F]{40}", spec["git_oid"]):
            return None, None
        sha1 = hashlib.sha1()''',
"validate Git blob OID metadata")
text = replace_once(
    text,
'''    size = int(spec["size"])
    if os.path.exists(dest) and os.path.getsize(dest) == size:
        return "present"
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)''',
'''    raw_size = spec.get("size")
    if not isinstance(raw_size, int) or isinstance(raw_size, bool) or raw_size < 0:
        raise DownloadError(f"{os.path.basename(dest)}: invalid file size metadata")
    size = raw_size
    hasher, expected = _hasher(spec) if verify else (None, None)
    if verify and hasher is None:
        raise DownloadError(f"{os.path.basename(dest)}: missing supported hash metadata")
    if os.path.exists(dest) and os.path.getsize(dest) == size:
        if not verify or verify_file(dest, spec):
            return "present"
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)''',
"Linux downloader fast path", allow_multiple=True)
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
        raw_size = spec["size"]
        if not isinstance(raw_size, int) or isinstance(raw_size, bool):
            return False
        expected_size = raw_size
        if expected_size < 0:
            return False
        hasher, expected = _hasher(spec)
        if hasher is None or not expected:
            return False
        before = os.stat(path, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or before.st_size != expected_size:
            return False
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if (not stat.S_ISREG(opened.st_mode) or opened.st_dev != before.st_dev
                    or opened.st_ino != before.st_ino or opened.st_size != expected_size):
                return False
            read = 0
            while True:
                block = handle.read(CHUNK * 8)
                if not block:
                    break
                read += len(block)
                if read > expected_size:
                    return False
                hasher.update(block)
            closed_view = os.fstat(handle.fileno())
        after = os.stat(path, follow_symlinks=False)
        return (read == expected_size and opened.st_dev == closed_view.st_dev
                and opened.st_ino == closed_view.st_ino and opened.st_size == closed_view.st_size
                and opened.st_mtime_ns == closed_view.st_mtime_ns
                and stat.S_ISREG(after.st_mode) and after.st_dev == closed_view.st_dev
                and after.st_ino == closed_view.st_ino and after.st_size == expected_size
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
'''    raw_size = spec.get("size")
    if not isinstance(raw_size, int) or isinstance(raw_size, bool) or raw_size < 0:
        raise DownloadError(f"{os.path.basename(dest)}: invalid file size metadata")
    size = raw_size
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
            ui.say("\\nDownload: already complete")
        else:
            ui.say(f"\\nDownload: {entry.repo} ({human_size(entry.disk_gb * GB)}); safe to "
                   "interrupt, rerun to continue")
            download_model(ui, entry, model_dir, via_windows=a.via_windows, verify=not a.no_verify)''',
'''        # Always refresh the source listing before trusting a local cache: refs such
        # as "main" are mutable, so matching the manifest's revision string is not
        # proof that its files still match today's remote revision. Avoid hashing
        # the whole local model here; download_repo verifies each cached file against
        # the freshly fetched listing as part of the actual transfer decision.
        ui.say(f"\\nDownload: already complete locally; checking current remote revision for {entry.repo}; "
               "safe to interrupt, rerun to continue")
        download_model(ui, entry, model_dir, via_windows=a.via_windows, verify=not a.no_verify)''',
"mutable-revision cache shortcut must revalidate remotely")
FLOW.write_text(flow, encoding="utf-8")
print("Applied strict Colibri integrity hardening to isolated checkout.")
