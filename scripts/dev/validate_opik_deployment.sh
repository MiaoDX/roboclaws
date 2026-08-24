#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
compose_file="${repo_root}/deploy/opik/compose.yaml"
export OPIK_HTTP_PORT=5174

mkdir -p \
    "${repo_root}/output/opik-poc/data/clickhouse" \
    "${repo_root}/output/opik-poc/data/clickhouse-config" \
    "${repo_root}/output/opik-poc/data/clickhouse-logs" \
    "${repo_root}/output/opik-poc/data/minio" \
    "${repo_root}/output/opik-poc/data/mysql" \
    "${repo_root}/output/opik-poc/data/redis" \
    "${repo_root}/output/opik-poc/data/zookeeper" \
    "${repo_root}/output/opik-poc/data/zookeeper-datalog" \
    "${repo_root}/output/opik-poc/data/zookeeper-logs"
[[ -w "${repo_root}/output/opik-poc" ]]

docker compose -p roboclaws-opik-poc -f "${compose_file}" config --quiet
config_json="$(docker compose -p roboclaws-opik-poc -f "${compose_file}" config --format json)"
OPIK_COMPOSE_CONFIG="${config_json}" OPIK_REPO_ROOT="${repo_root}" \
    "${repo_root}/.venv/bin/python" - <<'PY'
import json
import os
from pathlib import Path

config = json.loads(os.environ["OPIK_COMPOSE_CONFIG"])
services = config["services"]
expected = {
    "backend", "clickhouse", "clickhouse-init", "frontend", "minio",
    "minio-init", "mysql", "redis", "zookeeper",
}
assert set(services) == expected
assert set(config["networks"]) == {"default"}
assert config["networks"]["default"]["name"] == "roboclaws-opik-poc"

images = {name: service["image"] for name, service in services.items()}
assert images == {
    "backend": "ghcr.io/comet-ml/opik/opik-backend:2.2.36",
    "clickhouse": "clickhouse/clickhouse-server:26.3.16.16-alpine",
    "clickhouse-init": "alpine:3.22.1",
    "frontend": "ghcr.io/comet-ml/opik/opik-frontend:2.2.36",
    "minio": "minio/minio:RELEASE.2025-03-12T18-04-18Z",
    "minio-init": "minio/mc:RELEASE.2025-03-12T17-29-24Z",
    "mysql": "mysql:8.4.2",
    "redis": "redis:7.2.4-alpine3.19",
    "zookeeper": "zookeeper:3.9.4",
}
assert all(service.get("restart") == "no" for service in services.values())
assert all("healthcheck" in service or name.endswith("-init") for name, service in services.items())
assert all("limits" in service.get("deploy", {}).get("resources", {}) or name.endswith("-init") for name, service in services.items())

published = [(name, port) for name, service in services.items() for port in service.get("ports", [])]
assert len(published) == 1
name, port = published[0]
assert name == "frontend"
assert (port["host_ip"], port["published"], port["target"]) == ("127.0.0.1", "5174", 5173)

data_root = Path(os.environ["OPIK_REPO_ROOT"]) / "output" / "opik-poc" / "data"
for name, service in services.items():
    for volume in service.get("volumes", []):
        assert volume["type"] == "bind", (name, volume)
        source = Path(volume["source"])
        if volume["target"].startswith(("/var/lib/", "/data", "/config", "/var/log/")):
            assert source.is_relative_to(data_root), (name, volume)

assert services["backend"]["environment"]["OPIK_USAGE_REPORT_ENABLED"] == "false"
assert services["backend"]["environment"]["LLM_MODEL_REGISTRY_REMOTE_ENABLED"] == "false"
assert services["frontend"]["environment"]["OTEL_TRACE"] == "off"
assert "python-backend" not in services
assert "demo-data-generator" not in services
assert not config.get("volumes")

clickhouse_config = Path(os.environ["OPIK_REPO_ROOT"]) / "deploy/opik/clickhouse_config/additional_config.xml"
assert "<listen_host>0.0.0.0</listen_host>" in clickhouse_config.read_text()
PY

echo "opik deployment config: valid pinned 2.2.36 loopback-only isolated pilot"
