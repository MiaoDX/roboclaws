#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
compose_file="${repo_root}/deploy/phoenix/compose.yaml"
lan_compose_file="${repo_root}/deploy/phoenix/compose.lan.yaml"
export PHOENIX_HTTP_PORT=6006
export PHOENIX_GRPC_PORT=4317

docker compose -f "${compose_file}" config --quiet
image="$(docker compose -f "${compose_file}" config --images)"
[[ "${image}" == "arizephoenix/phoenix:11.20.0" ]]
[[ "$(docker compose -f "${compose_file}" config --services)" == "phoenix" ]]
config_json="$(docker compose -f "${compose_file}" config --format json)"
PHOENIX_COMPOSE_CONFIG="${config_json}" "${repo_root}/.venv/bin/python" - <<'PY'
import json
import os

config = json.loads(os.environ["PHOENIX_COMPOSE_CONFIG"])
service = config["services"]["phoenix"]
assert service["restart"] == "no"
assert service["deploy"]["resources"]["limits"] == {
    "cpus": 2,
    "memory": "4294967296",
}
assert {
    (port["host_ip"], port["published"], port["target"])
    for port in service["ports"]
} == {
    ("127.0.0.1", "6006", 6006),
    ("127.0.0.1", "4317", 4317),
}
assert service["volumes"] == [
    {
        "type": "volume",
        "source": "phoenix-data",
        "target": "/root/.phoenix",
        "volume": {},
    }
]
assert set(config["services"]) == {"phoenix"}
assert set(config["volumes"]) == {"phoenix-data"}
PY

export PHOENIX_LAN_BIND_HOST=192.0.2.60
export PHOENIX_LAN_HTTP_PORT=6006
lan_config_json="$(
    docker compose -f "${compose_file}" -f "${lan_compose_file}" config --format json
)"
PHOENIX_COMPOSE_CONFIG="${lan_config_json}" "${repo_root}/.venv/bin/python" - <<'PY'
import json
import os

config = json.loads(os.environ["PHOENIX_COMPOSE_CONFIG"])
service = config["services"]["phoenix"]
assert {
    (port["host_ip"], port["published"], port["target"])
    for port in service["ports"]
} == {
    ("127.0.0.1", "6006", 6006),
    ("127.0.0.1", "4317", 4317),
    ("192.0.2.60", "6006", 6006),
}
assert service["restart"] == "no"
assert service["deploy"]["resources"]["limits"] == {
    "cpus": 2,
    "memory": "4294967296",
}
assert set(config["services"]) == {"phoenix"}
assert set(config["volumes"]) == {"phoenix-data"}
PY
echo "phoenix deployment config: valid localhost service with opt-in LAN web binding (${image})"
