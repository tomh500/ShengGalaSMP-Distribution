"""Exercise Master, worker, and a real Spigot node in the disposable systemd fixture."""
import argparse
import hashlib
import json
import secrets
import shlex
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("checkout", type=Path)
parser.add_argument("runtime", type=Path)
parser.add_argument("bin", type=Path)
args = parser.parse_args()
checkout, runtime, binaries = (path.resolve() for path in (args.checkout, args.runtime, args.bin))
config = runtime / "topology.json"
state = Path(tempfile.mkdtemp(dir=runtime, prefix="master-test-"))
tokens = {}
for role in ("observer", "backup", "worker"):
    token = state / f"{role}.token"
    token.write_text(secrets.token_urlsafe(32) + "\n")
    token.chmod(0o600)
    tokens[role] = token

sites = json.loads(config.read_text())
examples = json.loads((checkout / "config/topology.example.json").read_text())
for key, name in (("master", "luo-master"), ("backup-worker", "luobackup-worker")):
    node = examples["nodes"][key]
    node["enabled"] = True
    node["process"] = {"cwd": str(state), "argv": [str(binaries / name), "--config", str(state / "master.json")]}
    sites["nodes"][key] = node
sites["nodes"]["backup-worker"]["probes"][0]["token_file"] = str(tokens["observer"])
config.write_text(json.dumps(sites, indent=2) + "\n", encoding="utf-8")

adapter = state / "lifecycle"
ctl = [sys.executable, str(checkout / "topologyctl.py"), "--config", str(config)]
adapter.write_text('#!/bin/sh\nexec ' + shlex.join(ctl) + ' lifecycle "$@"\n')
adapter.chmod(0o700)
for directory in ("job-state", "archives"):
    (state / directory).mkdir(mode=0o700)
master = json.loads((checkout / "config/master.example.json").read_text())
master.update({
    "state_dir": str(state / "job-state"),
    "archive_dir": str(state / "archives"),
    "lifecycle": str(adapter),
    "profiles": {"lobby-world": {"source": str(runtime / "lobby"), "include": ["world"]}},
})
for role, token in tokens.items():
    master[f"{role}_token_file"] = str(token)
(state / "master.json").write_text(json.dumps(master, indent=2) + "\n", encoding="utf-8")

def invoke(*arguments, check=True):
    return subprocess.run([*ctl, *arguments], check=check).returncode

def request(path, role, data=None):
    headers = {"Authorization": "Bearer " + tokens[role].read_text().strip()}
    if data is not None:
        headers.update({"Content-Type": "application/json", "Idempotency-Key": "lobby-smoke"})
        data = json.dumps(data).encode()
    req = urllib.request.Request("http://127.0.0.1:18776" + path, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as response:
        return response.status, json.load(response)

invoke("setup-systemd")
subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
try:
    invoke("wake", "lobby")
    assert invoke("lifecycle", "status", "survival", check=False) == 3
    invoke("wake", "backup-worker")
    assert request("/v1/topology", "observer")[1]["worker_online"] is True
    submitted, _ = request("/v1/backups", "backup", {"profile": "lobby-world"})
    assert submitted == 202
    deadline = time.monotonic() + 90
    while True:
        _, job = request("/v1/backups/lobby-smoke", "observer")
        if job["phase"] in ("succeeded", "failed", "recovery_required"):
            break
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Backup timed out in {job['phase']}")
        time.sleep(0.5)
    assert job["phase"] == "succeeded", job
    archive = state / "archives" / job["archive"]
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == job["sha256"]
    with zipfile.ZipFile(archive) as archived:
        assert "world/level.dat" in archived.namelist(), archived.namelist()[:10]
        assert all(not path.endswith("session.lock") for path in archived.namelist())
    invoke("lifecycle", "status", "lobby")
    assert invoke("lifecycle", "status", "survival", check=False) == 3
    print("PASS real Master, worker, Spigot save and restart, archive SHA-256 and prior stopped state", flush=True)
finally:
    invoke("stop")
