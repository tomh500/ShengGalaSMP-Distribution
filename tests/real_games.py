"""Prepare an isolated four-backend fixture using operator-supplied core JARs."""
import hashlib
import json
import secrets
import sys
from pathlib import Path

checkout, inputs, runtime = (Path(arg).resolve() for arg in sys.argv[1:])
runtime.mkdir(mode=0o700)
nodes = json.loads((checkout / "config/topology.example.json").read_text())["nodes"]
nodes = {name: node for name, node in nodes.items() if node.get("enabled", True)}
manifest = {"release": "0.1.0", "nodes": {}}
for name, node in nodes.items():
    path = runtime / name
    path.mkdir()
    node["cwd"] = str(path)
    java = node["java"]
    jar = inputs / java["jar"]
    java["bin"] = "/usr/bin/java" if "jdk25" in java["bin"] else "/usr/lib/jvm/java-8-openjdk-amd64/jre/bin/java"
    java["jvm_args"] = ["-Xms128m", "-Xmx384m", "-XX:ActiveProcessorCount=2"]
    node["ready_timeout"] = 85
    with jar.open("rb") as binary:
        digest = hashlib.file_digest(binary, "sha256").hexdigest()
    manifest["nodes"][name] = [{"file": str(jar), "target": jar.name, "sha256": digest}]
    if name == "proxy":
        node["probes"][0]["port"] = 25577
        continue
    token = secrets.token_hex(24)
    password = runtime / f"{name}.rcon"
    password.write_text(token + "\n")
    node["save_rcon"]["password_file"] = str(password)
    port = node["probes"][0]["port"]
    opts = [
        "eula=true",
        "server-ip=127.0.0.1",
        f"server-port={port}",
        "online-mode=false",
        "enable-rcon=true",
        f"rcon.port={node['save_rcon']['port']}",
        f"rcon.password={token}",
        "view-distance=3",
        "simulation-distance=3",
        "level-type=FLAT",
        "max-players=1",
        "max-tick-time=-1",
        "generate-structures=false",
    ]
    (path / "eula.txt").write_text(opts[0] + "\n")
    (path / "server.properties").write_text("\n".join(opts[1:]) + "\n")
(runtime / "topology.json").write_text(json.dumps({"nodes": nodes}, indent=2) + "\n")
(runtime / "artifacts.json").write_text(json.dumps(manifest, indent=2) + "\n")
