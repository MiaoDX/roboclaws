#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
compose_file="${repo_root}/deploy/phoenix/compose.yaml"

docker compose -f "${compose_file}" config --quiet
image="$(docker compose -f "${compose_file}" config --images)"
[[ "${image}" == "arizephoenix/phoenix:11.20.0" ]]
[[ "$(docker compose -f "${compose_file}" config --services)" == "phoenix" ]]
echo "phoenix deployment config: valid (${image})"
