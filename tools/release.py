"""Build and install a source-and-template-only distribution."""
from __future__ import annotations

import argparse
import gzip
import io
import os
import re
import tarfile
import tempfile
from hashlib import sha256
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]
FILES = (
    "VERSION", "LICENSE", "README.md", "bootstrap.sh", "install.sh",
    "tools/release.py", "topologyctl.py", "artifacts.py",
    "config/topology.example.json", "config/artifacts.example.json",
    "config/server.properties.example", "config/bungee-routing.example.yml",
    "config/master-integration.example.json", "config/mcqq-services.example.txt",
    "config/master-lifecycle.example.sh", "tools/checkout_sources.py",
    "config/radmin-windows.example.json", "vpn/radmin-windows.ps1",
    "network/wait-network.py", "network/ipv6.env.example", "network/radmin.env.example",
    "network/mc-uplink-ipv6-ready.service", "network/mc-radmin-ready.service",
    "config/master.example.json", "docs/master.md",
    "docs/components.md", "docs/operations.md", "locks/cores.json", "locks/sources.json",
)


def version_at(root):
    version = (root / "VERSION").read_text().strip()
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("Invalid distribution version")
    return version


def contents():
    payload = {}
    for name in FILES:
        path = SOURCE / name
        if path.resolve() != path:
            raise ValueError(f"Release input must be a local file: {name}")
        payload[name] = path.read_bytes()
    return payload


def build(output):
    output.mkdir(parents=True, exist_ok=True)
    version = version_at(SOURCE)
    target = output / f"topology-{version}.tar.gz"
    with target.open("wb") as handle, gzip.GzipFile(filename="", fileobj=handle, mode="wb", mtime=0) as zipped:
        with tarfile.open(fileobj=zipped, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for name, data in sorted(contents().items()):
                member = tarfile.TarInfo(name)
                member.size = len(data)
                member.mode = 0o644
                archive.addfile(member, io.BytesIO(data))
    digest = sha256(target.read_bytes()).hexdigest()
    (output / f"{target.name}.sha256").write_text(f"{digest}  {target.name}\n", encoding="ascii", newline="\n")
    print(f"{digest}  {target}")


def install(prefix):
    import fcntl

    version = version_at(SOURCE)
    payload = contents()
    prefix.mkdir(mode=0o700, parents=True, exist_ok=True)
    versions = prefix / "versions"
    versions.mkdir(mode=0o700, exist_ok=True)
    if versions.is_symlink():
        raise ValueError("The versions directory must be local to the install prefix")
    current = prefix / "current"
    release = versions / version
    with (prefix / ".install.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if current.exists() and not current.is_symlink():
            raise ValueError("The current path is occupied")
        with tempfile.TemporaryDirectory(dir=versions, prefix=".install-") as directory:
            stage = Path(directory) / "release"
            stage.mkdir()
            for name, data in payload.items():
                target = stage / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            if release.exists() or release.is_symlink():
                if release.is_symlink() or any(
                    not (release / name).is_file() or (release / name).read_bytes() != data
                    for name, data in payload.items()
                ):
                    raise ValueError(f"Version {version} is already installed with different content")
            else:
                stage.rename(release)
            link = Path(directory) / "current"
            link.symlink_to(release.relative_to(prefix), target_is_directory=True)
            os.replace(link, current)
    print(f"Installed {version} at {current}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    builder = actions.add_parser("build")
    builder.add_argument("--output", type=Path, default=SOURCE / "dist")
    installer = actions.add_parser("install")
    installer.add_argument("--prefix", type=Path, default=Path.home() / ".local/share/luo-topology")
    args = parser.parse_args()
    try:
        if args.action == "build":
            build(args.output)
        else:
            install(args.prefix.expanduser().absolute())
    except (OSError, ValueError) as exc:
        parser.exit(1, f"error: {exc}\n")


if __name__ == "__main__":
    main()
