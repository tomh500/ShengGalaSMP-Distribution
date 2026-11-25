#!/usr/bin/env bash
set -euo pipefail
exec /usr/bin/python3 /srv/group-server/tooling/current/topologyctl.py \
    --config /srv/group-server/private/topology.json lifecycle "$@"
