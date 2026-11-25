#!/usr/bin/env bash
set -euo pipefail
umask 077
export PYTHONDONTWRITEBYTECODE=1
src=$(cd -- "$(dirname -- "$0")/.." && pwd)
root=$(mktemp -d)
trap 'if [[ -n ${server_pid:-} ]]; then kill "$server_pid" 2>/dev/null || :; fi; rm -rf -- "$root"' EXIT

printf 'Linux: '; . /etc/os-release; echo "$PRETTY_NAME"
wget --version | head -1
builder="$src/tools/release.py"
python3 "$builder" build --output "$root/served/v0.1.0"
python3 "$builder" build --output "$root/rebuild"
archive="$root/served/v0.1.0/topology-0.1.0.tar.gz"
cmp "$archive" "$root/rebuild/topology-0.1.0.tar.gz"
digest=$(sha256sum "$archive" | cut -d' ' -f1)
cp "$src/bootstrap.sh" "$root/served/v0.1.0/bootstrap.sh"
openssl req -new -newkey rsa:2048 -x509 -nodes -days 1 -subj /CN=127.0.0.1 \
    -addext subjectAltName=IP:127.0.0.1 -keyout "$root/key" -out "$root/cert" 2>/dev/null
python3 "$src/tests/tls_server.py" "$root/served" "$root/cert" "$root/key" >"$root/tls.log" 2>&1 &
server_pid=$!
printf 'ca_certificate = %s\n' "$root/cert" > "$root/wgetrc"
export WGETRC="$root/wgetrc"
url=https://127.0.0.1:9443
for n in {1..30}; do
    if wget -q -O "$root/bootstrap.sh" "$url/v0.1.0/bootstrap.sh"; then break; fi
    sleep 0.2
done
cmp "$root/bootstrap.sh" "$src/bootstrap.sh"
prefix="$root/install"
other="$root/rejected"
if bash "$root/bootstrap.sh" "$url" 0.1.0 "$(printf '%064d' 0)" --prefix "$other"; then
    echo 'invalid checksum was accepted' >&2
    exit 1
fi
test ! -e "$other"
bash "$root/bootstrap.sh" "$url" 0.1.0 "$digest" --prefix "$prefix"
mkdir "$prefix/site-state"
printf 'preserve me' > "$prefix/site-state/world-fixture"
bash "$root/bootstrap.sh" "$url" 0.1.0 "$digest" --prefix "$prefix"
test "$(cat "$prefix/site-state/world-fixture")" = 'preserve me'
echo 'PASS deterministic archive, HTTPS bootstrap, digest rejection, rerun preserves state'

ctl="$prefix/current/topologyctl.py"
python3 "$ctl" setup-network --root "$root/network-install"
python3 "$ctl" setup-network --root "$root/network-install"
test -f "$root/network-install/usr/local/libexec/mc-network/wait-network.py"
test -f "$root/network-install/etc/systemd/system/mc-radmin-ready.service"
printf '\n# fixture collision\n' >> "$root/network-install/etc/systemd/system/mc-radmin-ready.service"
if python3 "$ctl" setup-network --root "$root/network-install"; then
    echo 'overwrote an existing network unit' >&2
    exit 1
fi
echo 'PASS staged network templates, idempotent install and collision refusal'
mkdir "$root/java"
cp "$src/tests/fake_java.py" "$root/java/runner"
chmod 700 "$root/java/runner"
export PYTHONPATH="$prefix/current"
jq_config="$root/topology.json"
python3 - "$root" > "$jq_config" <<'PY'
import json, sys
root = sys.argv[1]
print(json.dumps({"nodes": {
    "lobby": {
        "unit": "luo-java@lobby.service",
        "cwd": root + "/java",
        "java": {"bin": root + "/java/runner", "jar": "core.jar", "stop": "stop", "args": ["27566"]},
        "probes": [{"type": "minecraft", "host": "127.0.0.1", "port": 27566}],
        "ready_timeout": 15
    },
    "vpn-preflight": {"manage": False, "probes": [{"type": "command", "argv": ["/usr/bin/true"]}]},
    "ipv6-listener": {
        "manage": False, "ready_timeout": 10,
        "probes": [{"type": "command", "argv": ["/usr/bin/test", "-f", root + "/listener-ready"]}]
    },
    "ddns": {"manage": False, "depends": ["ipv6-listener"]},
}}))
PY
python3 "$ctl" --config "$jq_config" setup-systemd
# Allow the fixture binary to import the same Minecraft packet helpers.
mkdir -p "$HOME/.config/systemd/user/luo-java@.service.d"
printf '[Service]\nEnvironment=PYTHONPATH=%s\n' "$PYTHONPATH" > "$HOME/.config/systemd/user/luo-java@.service.d/smoke.conf"
systemd-analyze --user verify "$HOME/.config/systemd/user/luo-java@.service"
systemctl --user daemon-reload
printf 'eula=true\n' > "$root/java/eula.txt"
printf 'component one\n' > "$root/one.jar"
first=$(sha256sum "$root/one.jar" | cut -d' ' -f1)
printf '{"release":"1.0.0","nodes":{"lobby":[{"file":"one.jar","target":"core.jar","sha256":"%s"}]}}\n' "$first" > "$root/lock.json"
cli() { python3 "$ctl" --config "$jq_config" "$@"; }
(sleep 2; touch "$root/listener-ready") &
cli wake ddns
echo 'PASS optional DDNS waits for delayed listener readiness'
cli apply-jars "$root/lock.json" lobby
test ! -e "$root/java/core.jar"
cli apply-jars "$root/lock.json" lobby --apply
cli apply-jars "$root/lock.json" lobby --apply
if cli lifecycle status lobby; then
    echo 'inactive node incorrectly reported ready' >&2
    exit 1
else
    test "$?" = 3
fi
cli wake lobby
pid=$(cat "$root/java/pid")
cli wake lobby
test "$(cat "$root/java/pid")" = "$pid"
cli health
cli lifecycle status lobby

printf 'component two\n' > "$root/two.jar"
second=$(sha256sum "$root/two.jar" | cut -d' ' -f1)
printf '{"release":"1.1.0","nodes":{"lobby":[{"file":"two.jar","target":"core.jar","sha256":"%s","replaces":"%s"}]}}\n' "$second" "$first" > "$root/update.json"
if cli apply-jars "$root/update.json" lobby --apply; then
    echo 'updated a running node' >&2
    exit 1
fi
cli stop lobby
test "$(cat "$root/java/saved")" = stop
cli apply-jars "$root/update.json" lobby --apply
test "$(sha256sum "$root/java/core.jar" | cut -d' ' -f1)" = "$second"
old=$(find "$root/java/.topology-backups" -type f -name core.jar)
test "$(sha256sum "$old" | cut -d' ' -f1)" = "$first"
cli inventory lobby
echo 'PASS real user systemd, Java runner fixture, protocol probe, lifecycle status and stop, hash-checked JAR update and backup'
