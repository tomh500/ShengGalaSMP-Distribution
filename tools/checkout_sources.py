"""Fetch the exact public revisions recorded in the source lock."""
import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path


def git(*args, **kwargs):
    return subprocess.run(["git", *map(str, args)], check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    lock = Path(__file__).resolve().parents[1] / "locks/sources.json"
    records = json.loads(lock.read_text(encoding="utf-8"))["sources"]
    args.destination.mkdir(parents=True, exist_ok=True)
    for record in records:
        repo, commit = record["repo"], record["commit"]
        match = re.fullmatch(r"https://github\.com/[\w.-]+/([\w.-]+)\.git", repo)
        if not match or not re.fullmatch("[a-f0-9]{40}", commit):
            raise ValueError("Invalid locked Git URL or commit")
        destination = args.destination / match[1]
        if not destination.exists():
            with tempfile.TemporaryDirectory(dir=args.destination, prefix=".checkout-") as staging:
                candidate = Path(staging) / "repo"
                git("init", candidate)
                git("-C", candidate, "fetch", "--depth=1", repo, commit)
                git("-C", candidate, "checkout", "--detach", commit)
                candidate.rename(destination)
        head = git("-C", destination, "rev-parse", "HEAD", capture_output=True, text=True)
        changes = git("-C", destination, "status", "--porcelain", capture_output=True, text=True)
        if head.stdout.strip() != commit or changes.stdout.strip():
            raise SystemExit(f"Working tree differs from source lock: {destination}")
        print(f"{destination.name}: {commit}", flush=True)


if __name__ == "__main__":
    main()
