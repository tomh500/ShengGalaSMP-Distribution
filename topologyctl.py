#!/usr/bin/env python3
"""Manage a single Linux host's group-server topology."""
from __future__ import annotations

import argparse
import fcntl
import graphlib
import io
import json
import os
import re
import select
import socket
import struct
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlsplit
from pathlib import Path

import artifacts

DEFAULT = Path.home() / ".config/luo-topology/topology.json"
NODE_ID = re.compile(r"[a-z][a-z0-9-]{0,47}")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def load(path):
    nodes = json.loads(path.read_text(encoding="utf-8"))["nodes"]
    for name, node in nodes.items():
        if not NODE_ID.fullmatch(name):
            raise ValueError(f"Invalid node identifier: {name}")
        if "unit" in node and not re.fullmatch(r"[A-Za-z0-9_.@-]+\.service", node["unit"]):
            raise ValueError(f"Invalid unit for {name}")
        if node.get("scope", "user") not in {"user", "system"}:
            raise ValueError(f"Invalid service scope for {name}")
        if "java" in node and node["java"]["stop"] not in {"stop", "end"}:
            raise ValueError(f"Invalid Java console stop command for {name}")
        unknown = (set(node.get("depends", [])) | set(node.get("stop_before", []))) - nodes.keys()
        if unknown:
            raise ValueError(f"{name} has unknown dependencies: {', '.join(sorted(unknown))}")
    graphlib.TopologicalSorter({name: node.get("depends", []) for name, node in nodes.items()}).prepare()
    enabled = {name: node for name, node in nodes.items() if node.get("enabled", True)}
    for name, node in enabled.items():
        if set(node.get("depends", [])) - enabled.keys():
            raise ValueError(f"{name} depends on a disabled node")
    shutdown_order(enabled)
    return enabled


def run(argv, timeout=15):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)


def unit_call(node, command, *args, timeout=15):
    context = ["--user"] if node.get("scope", "user") == "user" else []
    return run(["systemctl", *context, command, *args, node["unit"]], timeout)


def unit_state(node):
    values = unit_call(node, "show", "--property=LoadState,ActiveState,SubState").stdout
    result = dict(line.split("=", 1) for line in values.splitlines() if "=" in line)
    if result.get("LoadState") != "loaded":
        return "unknown"
    state = result.get("ActiveState", "unknown")
    if state == "active" and result.get("SubState") in {"exited", "dead"}:
        return "exited"
    return state


def varint(number):
    result = bytearray()
    while number > 127:
        result.append((number & 127) | 128)
        number >>= 7
    result.append(number)
    return bytes(result)


def read_bytes(stream, size):
    value = stream.read(size)
    if len(value) != size:
        raise ValueError("Truncated protocol response")
    return value


def read_varint(stream):
    number = 0
    for i in range(5):
        octet = read_bytes(stream, 1)[0]
        number |= (octet & 127) << (7 * i)
        if not octet & 128:
            return number
    raise ValueError("Invalid VarInt")


def minecraft_status(probe):
    host, port = probe["host"], probe["port"]
    hostname = probe.get("virtual_host", host).encode("utf-8")
    handshake = b"\x00" + varint(probe.get("protocol", 340)) + varint(len(hostname))
    handshake += hostname + struct.pack(">H", port) + b"\x01"
    with socket.create_connection((host, port), timeout=3) as connection:
        connection.sendall(varint(len(handshake)) + handshake + b"\x01\x00")
        with connection.makefile("rb") as stream:
            size = read_varint(stream)
            if size > 1048576:
                raise ValueError("Minecraft status packet is larger than expected")
            packet = io.BytesIO(read_bytes(stream, size))
            if read_varint(packet) != 0:
                return False
            data = json.loads(read_bytes(packet, read_varint(packet)))
            return isinstance(data.get("version"), dict) and isinstance(data.get("players"), dict)


def mastergal_logs(probe, nodes):
    upstream = nodes[probe["node"]]
    invocation = unit_call(upstream, "show", "--property=InvocationID", "--value").stdout.strip()
    if not re.fullmatch(r"[a-f0-9]{32}", invocation) or invocation == "0" * 32:
        return False
    logs = run(["journalctl", "--no-pager", "-o", "cat", f"_SYSTEMD_INVOCATION_ID={invocation}"])
    plugin = re.escape(probe["plugin"])
    if logs.returncode:
        return False
    seen = re.search(rf"(?im)(Enabled plugin {plugin}\b|\[{plugin}\] Enabling {plugin}\b)", logs.stdout)
    failed = re.search(rf"(?im)(Error occurred while enabling {plugin}\b|\[{plugin}\] (?:Disabling|Exception)\b|Exception enabling plugin {plugin}\b)", logs.stdout)
    return bool(seen and not failed)


def check(probe, nodes):
    mode = probe["type"]
    if mode in {"http", "worker-online"}:
        url = probe["url"]
        if not url.startswith(("http://", "https://")):
            raise ValueError("Expected an HTTP health URL")
        request = urllib.request.Request(url)
        if mode == "worker-online":
            if urlsplit(url).hostname not in {"127.0.0.1", "::1"}:
                raise ValueError("Use a loopback address for the Master management token")
            token = Path(probe["token_file"]).read_text(encoding="utf-8").strip()
            request.add_header("Authorization", f"Bearer {token}")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(request, timeout=4) as response:
            if mode == "worker-online":
                return response.status == 200 and json.loads(response.read(65536)).get("worker_online") is True
            return response.status == 200
    if mode == "minecraft":
        return minecraft_status(probe)
    if mode == "command":
        return run(probe["argv"], timeout=8).returncode == 0
    if mode == "interface":
        result = run(["ip", "-j", "address", "show", "dev", probe["name"]])
        if result.returncode:
            return False
        link, = json.loads(result.stdout)
        if "UP" not in link["flags"] or not link.get("addr_info"):
            return False
        if "peer" not in probe:
            return True
        peer = probe["peer"]
        route = run(["ip", "-j", "route", "get", peer]).stdout
        if not route or json.loads(route)[0].get("dev") != probe["name"]:
            return False
        with socket.create_connection((peer, probe["port"]), timeout=3):
            return True
    if mode == "mastergal":
        return mastergal_logs(probe, nodes)
    raise ValueError(f"Unknown health probe: {mode}")


def health(name, nodes):
    node = nodes[name]
    if "unit" in node:
        state = unit_state(node)
        if state == "exited" and node.get("allow_unit_exited"):
            pass
        elif state != "active":
            return state
    try:
        if all(check(probe, nodes) for probe in node.get("probes", [])):
            return "ready"
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return "unready"


def graph_order(nodes, target=None):
    order = list(graphlib.TopologicalSorter({name: node.get("depends", []) for name, node in nodes.items()}).static_order())
    if target is None:
        return order
    subtree = {target}
    for name in reversed(order):
        if name in subtree:
            subtree.update(nodes[name].get("depends", []))
    return [name for name in order if name in subtree]


def shutdown_order(nodes):
    graph = {name: set() for name in reversed(graph_order(nodes))}
    for name, node in nodes.items():
        for upstream in node.get("depends", []):
            if name not in nodes[upstream].get("stop_before", []):
                graph[upstream].add(name)
        for followup in node.get("stop_before", []):
            if followup in nodes:
                graph[followup].add(name)
    return list(graphlib.TopologicalSorter(graph).static_order())


def wait_ready(name, nodes):
    timeout = nodes[name].get("ready_timeout", 120)
    deadline = time.monotonic() + timeout
    while True:
        state = health(name, nodes)
        if state == "ready":
            print(f"{name}: ready", flush=True)
            return
        if state == "failed" or time.monotonic() >= deadline:
            raise RuntimeError(f"{name}: {state} after start; inspect the unit journal and probe")
        time.sleep(1)


def start(name, nodes):
    node = nodes[name]
    if "unit" in node and node.get("manage", True):
        state = unit_state(node)
        if state in {"inactive", "failed"} and node.get("java"):
            prepare_java(node)
        if state not in {"active", "exited"}:
            result = unit_call(node, "start", timeout=node.get("ready_timeout", 120))
            if result.returncode:
                raise RuntimeError(f"{name}: systemctl start failed ({result.stderr.strip()})")
    wait_ready(name, nodes)


def stop(name, node):
    if "unit" not in node or not node.get("manage", True) or not node.get("stop_managed", True):
        return
    result = unit_call(node, "stop", timeout=node.get("stop_timeout", 210))
    if result.returncode or unit_state(node) != "inactive":
        raise RuntimeError(f"{name}: unit could not be confirmed stopped")
    print(f"{name}: stopped", flush=True)


def scope_lock(config, name):
    path = config.parent / f".{name}.operation.lock"
    handle = path.open("a")
    fcntl.flock(handle, fcntl.LOCK_EX)
    return handle


def java_spec(node):
    return Path(node["cwd"]), node["java"]


def prepare_java(node):
    root, java = java_spec(node)
    jar = root / java["jar"]
    if not jar.is_file():
        raise ValueError(f"Missing server JAR: {jar}")
    if java["stop"] == "stop" and not (root / "eula.txt").is_file():
        raise ValueError(f"Missing Minecraft EULA acknowledgement: {root / 'eula.txt'}")
    return root, java, jar


def java_launch(node, fifo):
    root, java, jar = prepare_java(node)
    fifo.unlink(missing_ok=True)
    os.mkfifo(fifo, mode=0o600)
    fd = os.open(fifo, os.O_RDWR)
    os.dup2(fd, 0)
    os.close(fd)
    os.chdir(root)
    binary = java["bin"]
    os.execv(binary, [binary, *java.get("jvm_args", []), "-jar", str(jar), *java.get("args", [])])


def java_stop(node, fifo, pid):
    if not pid:
        return
    try:
        descriptor = os.pidfd_open(pid)
    except ProcessLookupError:
        return
    try:
        try:
            fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
            with os.fdopen(fd, "w", encoding="ascii") as pipe:
                pipe.write(node["java"]["stop"] + "\n")
        except OSError as exc:
            raise RuntimeError(f"Could not send the console shutdown command: {exc}") from exc
        reader = select.poll()
        reader.register(descriptor, select.POLLIN)
        if not reader.poll():
            raise RuntimeError("Could not confirm Java shutdown")
    finally:
        os.close(descriptor)


def rcon_packet(stream):
    size, = struct.unpack("<i", read_bytes(stream, 4))
    if not 10 <= size <= 65536:
        raise ValueError("Invalid RCON packet size")
    body = read_bytes(stream, size)
    request_id, _ = struct.unpack("<ii", body[:8])
    return request_id, body[8:-2].decode("utf-8", errors="replace")


def rcon_send(connection, request_id, mode, payload):
    body = struct.pack("<ii", request_id, mode) + payload.encode("utf-8") + b"\0\0"
    connection.sendall(struct.pack("<i", len(body)) + body)


def save(node):
    if node.get("save") == "noop":
        return
    rcon = node["save_rcon"]
    if rcon.get("host", "127.0.0.1") != "127.0.0.1":
        raise ValueError("Use a loopback RCON listener")
    secret = Path(rcon["password_file"]).read_text(encoding="utf-8").strip()
    if not secret:
        raise ValueError("RCON password file is empty")
    with socket.create_connection(("127.0.0.1", rcon["port"]), timeout=5) as connection:
        connection.settimeout(rcon.get("timeout", 120))
        with connection.makefile("rb") as stream:
            rcon_send(connection, 1, 3, secret)
            auth_id, _ = rcon_packet(stream)
            if auth_id != 1:
                raise RuntimeError("RCON authentication failed")
            rcon_send(connection, 2, 2, "save-all flush")
            reply_id, text = rcon_packet(stream)
            # Both servers concatenate RCON feedback lines. The acknowledgement
            # is the final message after the synchronous flush.
            if reply_id != 2 or not text.rstrip().endswith(("Saved the world", "Saved the game")):
                raise RuntimeError("RCON did not return the expected save confirmation")


def write_template(target, contents, mode=0o644):
    target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        with os.fdopen(fd, "wb") as file:
            file.write(contents)
    except FileExistsError:
        if target.is_symlink() or target.read_bytes() != contents:
            raise ValueError(f"Existing template differs: {target}")
    print(target)


def systemd_setup(config, directory, nodes):
    # systemd expands percent specifiers even in quotes.
    def arg(value):
        if any(char in str(value) for char in "\r\n\0"):
            raise ValueError("Invalid character in systemd command argument")
        return '"' + str(value).replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"').replace("$", "$$") + '"'

    def unit_path(value):
        if not Path(value).is_absolute() or value.strip() != value or any(char in value for char in "\r\n\0"):
            raise ValueError("Expected an absolute systemd path")
        return value.replace("%", "%%")

    launcher = f"/usr/bin/python3 {arg(Path(__file__).absolute())} --config {arg(config.absolute())}"
    unit = f"""[Unit]
Description=Luo Minecraft instance %i
StartLimitIntervalSec=120
StartLimitBurst=3

[Service]
Type=exec
UMask=0077
RuntimeDirectory=luo-java-%i
ExecStart={launcher} run-java %i %t/luo-java-%i/console
ExecStop={launcher} stop-java %i %t/luo-java-%i/console ${{MAINPID}}
TimeoutStopSec=180
Restart=on-failure
RestartSec=5
"""
    write_template(directory / "luo-java@.service", unit.encode())
    for name, node in nodes.items():
        process = node.get("process")
        if not process:
            continue
        if node.get("scope", "user") != "user":
            raise ValueError(f"setup-systemd only writes user units: {name}")
        command = " ".join(arg(parameter) for parameter in process["argv"])
        cwd = unit_path(process["cwd"])
        environment = f"EnvironmentFile={unit_path(process['environment_file'])}" if "environment_file" in process else ""
        stop_timeout = int(node.get("stop_timeout", 120)) - 5
        service = f"""[Unit]
Description=Luo topology service {name}

[Service]
Type=exec
UMask=0077
WorkingDirectory={cwd}
{environment}
ExecStart={command}
TimeoutStopSec={stop_timeout}
Restart=on-failure
RestartSec=5
"""
        write_template(directory / node["unit"], service.encode())


def setup_network(root):
    source = Path(__file__).parent / "network"
    payload = {
        "wait-network.py": "usr/local/libexec/mc-network/wait-network.py",
        "mc-uplink-ipv6-ready.service": "etc/systemd/system/mc-uplink-ipv6-ready.service",
        "mc-radmin-ready.service": "etc/systemd/system/mc-radmin-ready.service",
        "ipv6.env.example": "etc/mc-network/ipv6.env.example",
        "radmin.env.example": "etc/mc-network/radmin.env.example",
    }
    for name, target in payload.items():
        write_template(root / target, (source / name).read_bytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(os.environ.get("LUO_TOPOLOGY_CONFIG", DEFAULT)))
    actions = parser.add_subparsers(dest="action", required=True)
    for name in ("wake", "stop", "health"):
        actions.add_parser(name).add_argument("node", nargs="?")
    lifecycle = actions.add_parser("lifecycle")
    lifecycle.add_argument("operation", choices=("status", "save", "stop", "start"))
    lifecycle.add_argument("node")
    for verb in ("run-java", "stop-java"):
        sub = actions.add_parser(verb)
        sub.add_argument("node")
        sub.add_argument("fifo", type=Path)
        if verb == "stop-java":
            sub.add_argument("pid", type=lambda value: int(value or "0"), nargs="?", default=0)
    setup = actions.add_parser("setup-systemd")
    setup.add_argument("--directory", type=Path, default=Path.home() / ".config/systemd/user")
    network = actions.add_parser("setup-network")
    network.add_argument("--root", type=Path, default=Path("/"))
    inventory = actions.add_parser("inventory")
    inventory.add_argument("node", nargs="?")
    provision = actions.add_parser("apply-jars")
    provision.add_argument("manifest", type=Path)
    provision.add_argument("node")
    provision.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    try:
        if args.action == "setup-network":
            setup_network(args.root)
            return 0
        config = args.config.expanduser().resolve()
        if args.action == "setup-systemd":
            systemd_setup(config, args.directory, load(config))
            return 0
        nodes = load(config)
        target = args.node
        if target is not None and target not in nodes:
            raise ValueError(f"Unknown or disabled node: {target}")
        if args.action == "inventory":
            artifacts.inventory({target: nodes[target]} if target else nodes)
        elif args.action == "apply-jars":
            with scope_lock(config, target):
                artifacts.apply(nodes[target], args.manifest, target, args.apply, unit_state)
        elif args.action == "run-java":
            java_launch(nodes[target], args.fifo)
        elif args.action == "stop-java":
            java_stop(nodes[target], args.fifo, args.pid)
        elif args.action == "lifecycle":
            node = nodes[target]
            if not node.get("manage", True) or not node.get("backup_target", bool(node.get("java"))):
                raise ValueError("Master lifecycle adapter requires a managed service other than Master")
            with scope_lock(config, target):
                if args.operation == "status":
                    state = health(target, nodes)
                    return 0 if state == "ready" else 3 if state == "inactive" else 4
                if args.operation == "save":
                    if health(target, nodes) != "ready":
                        raise RuntimeError("Cannot save a node that is not ready")
                    save(node)
                if args.operation == "stop":
                    stop(target, node)
                if args.operation == "start":
                    start(target, nodes)
        elif args.action == "health":
            states = {name: health(name, nodes) for name in ([target] if target else graph_order(nodes))}
            for name, state in states.items():
                print(f"{name}: {state}")
            return 0 if all(state == "ready" for state in states.values()) else 1
        elif args.action in {"wake", "stop"}:
            order = graph_order(nodes, target) if args.action == "wake" else [target] if target else shutdown_order(nodes)
            for name in order:
                with scope_lock(config, name):
                    if args.action == "wake":
                        start(name, nodes)
                    else:
                        stop(name, nodes[name])
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.TimeoutExpired) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
