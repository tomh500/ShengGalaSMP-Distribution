"""Verify and install explicitly mapped server JARs while the service is down."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def inventory(nodes):
    result = {}
    for name, node in nodes.items():
        if "java" not in node:
            continue
        root = Path(node["cwd"])
        core = root / node["java"]["jar"]
        files = ([core] if core.is_file() else []) + sorted((root / "plugins").glob("*.jar"))
        result[name] = {path.relative_to(root).as_posix(): digest(path) for path in files if path.is_file()}
    print(json.dumps(result, indent=2, ensure_ascii=False))


def plan(node, manifest, name):
    spec = json.loads(manifest.read_text(encoding="utf-8"))
    if not re.fullmatch(r"[0-9][0-9A-Za-z._-]{0,63}", spec["release"]):
        raise ValueError("A fixed component release identifier is required")
    root = Path(node["cwd"]).resolve()
    if not root.is_dir():
        raise ValueError(f"Create the node directory before installation: {root}")
    core = node["java"]["jar"]
    if Path(core).name != core or not core.endswith(".jar"):
        raise ValueError("The server core must be a top-level JAR")
    entries = []
    seen = set()
    for item in spec["nodes"][name]:
        relative = item["target"]
        if relative != core and not re.fullmatch(r"plugins/[^/\\\x00-\x1f]+\.jar", relative):
            raise ValueError(f"Target must be the configured core or a plugins/*.jar file: {relative}")
        target = root / relative
        if (target.is_symlink() or target.parent.is_symlink() or
                target.exists() and not target.is_file() or relative.casefold() in seen):
            raise ValueError(f"Target is occupied, duplicated, or a symlink: {relative}")
        seen.add(relative.casefold())
        source = manifest.parent / item["file"]
        expected = item["sha256"]
        if not re.fullmatch(r"[0-9a-f]{64}", expected) or digest(source) != expected:
            raise ValueError(f"Input SHA-256 mismatch: {relative}")
        old = digest(target) if target.is_file() else None
        if expected == old:
            continue
        if old != item.get("replaces"):
            raise ValueError(f"Existing JAR hash must match the reviewed 'replaces' value: {relative}")
        entries.append((source, target, old, expected))
    return root, spec["release"], entries


def apply(node, manifest, name, commit, unit_state):
    root, release, entries = plan(node, manifest, name)
    for _, target, old, expected in entries:
        print(f"{target.relative_to(root)}: {old or 'absent'} -> {expected}")
    if not entries:
        print("All mapped JARs already match")
        return
    if not commit:
        return
    if unit_state(node) != "inactive":
        raise ValueError("The configured service must be confirmed inactive")
    backup_root = root / ".topology-backups"
    backup_root.mkdir(mode=0o700, exist_ok=True)
    if backup_root.is_symlink():
        raise ValueError("Backup directory must be inside the node directory")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = Path(tempfile.mkdtemp(dir=backup_root, prefix=f"{stamp}-{release}-"))
    journal = []
    with tempfile.TemporaryDirectory(dir=root, prefix=".topology-stage-") as directory:
        staged = []
        for index, (source, target, old, expected) in enumerate(entries):
            copy = Path(directory) / str(index)
            shutil.copyfile(source, copy)
            if digest(copy) != expected:
                raise ValueError(f"Staged SHA-256 mismatch: {target.name}")
            previous = backup / target.relative_to(root)
            if old is not None:
                previous.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(target, previous)
                if digest(previous) != old:
                    raise ValueError(f"Backup SHA-256 mismatch: {target.name}")
            staged.append((copy, target, previous if old else None))
            journal.append({"target": target.relative_to(root).as_posix(), "previous": old, "next": expected})
        (backup / "manifest.json").write_text(json.dumps(journal, indent=2) + "\n", encoding="utf-8")
        if unit_state(node) != "inactive":
            raise ValueError("The configured service must remain inactive")
        applied = []
        try:
            for copy, target, previous in staged:
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(copy, target)
                applied.append((target, previous))
        except (OSError, KeyboardInterrupt):
            for target, previous in reversed(applied):
                if previous is None:
                    target.unlink()
                else:
                    copy = Path(directory) / "rollback"
                    shutil.copyfile(previous, copy)
                    os.replace(copy, target)
            raise
    print(f"Backup manifest: {backup / 'manifest.json'}")
