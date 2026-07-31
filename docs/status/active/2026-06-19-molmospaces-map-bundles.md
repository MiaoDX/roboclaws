# MolmoSpaces Map Bundles

- Source: user request on 2026-06-19 to commit strict bundle policy first, then
  generate a bundle set for all active scenes.
- Current slice: generated and verified canonical Nav2-style bundles under
  `assets/maps/molmospaces/<source>/<index>` for all active sampler scenes.
- Scope: simulator map bundle preparation only. Real robot and B1 digital-twin
  Agibot map flows remain as-is.
- No-touch scope: unrelated dirty work and parked SDK storage status docs.
- Last proven evidence:
  - `.venv/bin/python scripts/maps/generate_molmospaces_scene_bundles.py --active-sampler-scenes --force --json`
  - `for dir in $(find assets/maps/molmospaces -mindepth 2 -maxdepth 2 -type d | sort); do .venv/bin/python -m roboclaws.maps.bundle "$dir"; done`
  - `./scripts/dev/run_pytest_standalone.sh -q tests/contract/maps/test_generate_molmospaces_scene_bundles.py tests/contract/maps/test_nav2_map_bundle_contract.py tests/unit/launch/test_scene_sampler.py`
  - `ruff check scripts/maps/generate_molmospaces_scene_bundles.py tests/contract/maps/test_generate_molmospaces_scene_bundles.py roboclaws/launch/map_bundles.py tests/contract/maps/test_nav2_map_bundle_contract.py tests/unit/launch/test_scene_sampler.py`
  - `ruff format --check scripts/maps/generate_molmospaces_scene_bundles.py tests/contract/maps/test_generate_molmospaces_scene_bundles.py`
- Stop condition: owned changes committed.
- Parked work: broader scanner candidates without `ui` or `eval_stress` lanes
  are not part of this generated product asset set.
