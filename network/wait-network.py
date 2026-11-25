#!/usr/bin/env python3
"""Read-only Linux readiness checks for the uplink and Radmin overlay."""

import argparse
import ipaddress
import json
import math
import os
import subprocess
import sys
import time


def ip_json(*args, timeout):
    result = subprocess.run(
        ["ip", "-j", *args], capture_output=True, check=True, timeout=timeout
    )
    return json.loads(result.stdout)


def ready_addresses(links, family):
    for link in links:
        if "UP" not in link["flags"]:
            continue
        for item in link["addr_info"]:
            if item["family"] != family or item["scope"] != "global":
                continue
            if any(item.get(flag) for flag in ("tentative", "optimistic", "dadfailed", "deprecated")):
                continue
            if item.get("preferred_life_time") in (0, "0", "0sec"):
                continue
            address = ipaddress.ip_address(item["local"])
            if not (address.is_unspecified or address.is_loopback or address.is_multicast):
                yield address


def uplink_ready(ip, probe, interface=None):
    routes = ip("-6", "route", "get", str(probe))
    if not routes:
        return False
    route = routes[0]
    device = route.get("dev")
    if not device or (interface and device != interface):
        return False
    if not route.get("prefsrc") or "linkdown" in route.get("flags", []):
        return False
    source = ipaddress.IPv6Address(route["prefsrc"])
    if not source.is_global:
        return False
    defaults = ip("-6", "route", "show", "table", "all", "default")
    if not any(r.get("dev") == device and "linkdown" not in r.get("flags", []) for r in defaults):
        return False
    return source in ready_addresses(ip("-6", "addr", "show", "dev", device), "inet6")


def radmin_ready(ip, interface, peer=None):
    if not any(ready_addresses(ip("-4", "addr", "show", "dev", interface), "inet")):
        return False
    if peer is None:
        return True
    return any(r.get("dev") == interface for r in ip("-4", "route", "get", str(peer)))


def seconds(value):
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("expected a finite positive number of seconds")
    return parsed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("ipv6", "radmin"))
    parser.add_argument("--timeout", type=seconds, default=30)
    parser.add_argument("--interval", type=seconds, default=1)
    parser.add_argument("--interface", default=os.getenv("MC_NETWORK_INTERFACE"))
    parser.add_argument(
        "--ipv6-route-probe", type=ipaddress.IPv6Address,
        default=os.getenv("MC_IPV6_ROUTE_PROBE", "2001:db8::1"),
    )
    parser.add_argument(
        "--radmin-peer", type=ipaddress.IPv4Address, default=os.getenv("MC_RADMIN_PEER")
    )
    args = parser.parse_args()
    deadline = time.monotonic() + args.timeout

    def ip(*command):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        return ip_json(*command, timeout=min(2, remaining))

    while time.monotonic() < deadline:
        try:
            if args.mode == "ipv6":
                ready = uplink_ready(ip, args.ipv6_route_probe, args.interface)
            else:
                ready = radmin_ready(ip, args.interface or "radminvpn0", args.radmin_peer)
        except FileNotFoundError:
            print("network readiness: ip command unavailable", file=sys.stderr)
            return 2
        except (TimeoutError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
            ready = False
        if ready:
            print(f"network readiness: {args.mode} ready")
            return 0
        time.sleep(max(0, min(args.interval, deadline - time.monotonic())))
    print(f"network readiness: {args.mode} timed out", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
