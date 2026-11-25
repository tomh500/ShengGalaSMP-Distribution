#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ $# -lt 3 ]]; then
    echo 'Usage: bash bootstrap.sh HTTPS_BASE VERSION APPROVED_SHA256 [install arguments]' >&2
    exit 2
fi
base=${1%/}
version=$2
digest=$3
shift 3
[[ $base == https://* && $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ && $digest =~ ^[a-f0-9]{64}$ ]] || {
    echo 'Expected an HTTPS base URL, exact version, and lower-case SHA-256' >&2
    exit 2
}

work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
archive="$work/topology.tar.gz"
wget --https-only --tries=2 --timeout=25 -O "$archive" -- "$base/v$version/topology-$version.tar.gz"
printf '%s  %s\n' "$digest" "$archive" | sha256sum --strict -c -

python3 - "$archive" "$work" "$version" <<'PY'
import pathlib
import sys
import tarfile

archive, work, version = sys.argv[1:]
with tarfile.open(archive, "r:gz") as source:
    members = source.getmembers()
    paths = [pathlib.PurePosixPath(item.name) for item in members]
    if len(set(paths)) != len(paths) or not all(
        item.isfile() and not path.is_absolute() and ".." not in path.parts
        for item, path in zip(members, paths)
    ):
        raise SystemExit("Invalid topology archive")
    source.extractall(work, members, filter="data")
if (pathlib.Path(work) / "VERSION").read_text().strip() != version:
    raise SystemExit("Topology archive version mismatch")
PY

bash "$work/install.sh" "$@"
