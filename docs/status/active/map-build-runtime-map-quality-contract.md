# Map-Build Runtime Map Quality Contract

Status: ACTIVE

Source intent: implement the accepted `$intuitive-flow` slice for Runtime
Metric Map quality. Keep MapBuild output useful for open-ended and cleanup
tasks while preventing RGB-only observations from pretending to know target
map-frame poses.

Current slice: prior-consumer correction implemented. Runtime Metric Map
generation now clusters same-view fixture anchors, marks anchor/candidate pose
provenance as viewpoint/navigation pose, and checker gates reject RGB-only
current-run `object_pose` unless trusted projection provenance exists. Runtime
Map Prior anchors now stay bound to their snapshot waypoint unless the current
run has waypoint-local fixture evidence to rematerialize the same public anchor.

Last proven evidence: reduce-entropy review found duplicate DINO anchors
(`Bed`, `DiningTable`, `TVStand`, `Desk`) sharing category, waypoint,
observation, and pose. Code inspection showed current-run fixture anchor
`pose` is derived from the inspection waypoint, while Map12 conversion can
separately materialize `object_pose`.

Last proven evidence: focused contract/checker/snapshot tests passed; broader
runtime-map prior consumer tests passed; `just agent::eval suite=map_build_consumer
budget=smoke` passed 5/5. The new map-build artifact has 24 anchors, 10 unique
fixture anchors, 6 observed objects, 43 target candidates, 0 duplicate fixture
viewpoint groups, and 0 `object_pose` claims. Open-ended prior search improved
from 13 waypoint navigations / 18 observes to 7 waypoint navigations / 12
observes; cleanup prior remained no-regression with movable hints rechecked.

Last proven evidence: focused prior-anchor contract tests passed, eval sample
models/runner tests passed, and `just agent::eval suite=map_build_consumer
budget=smoke` passed 5/5 at
`output/evals/household_world_map_build_consumer/20260625T224252/eval_results.json`.
The open-ended stable-anchor private predicate now keys on
`room_8_inspection`, not an unstable public fixture-anchor number.
Latest deterministic rerun after docs alignment passed 5/5 at
`output/evals/household_world_map_build_consumer/20260625T230310/eval_results.json`.

Last live evidence: root-env OpenAI Agents SDK post-fix thin matrix ran the
open-ended MapBuild consumer chain against `codex-router-responses`,
`mimo-inside-openai-chat`, `kimi-openai-chat`, and `minimax-responses` after
`7983d53c`. Provider health passed first via
`.venv/bin/python scripts/dev/check_model_providers.py --mode all` from the root
repo env. Results live under
`output/evals-live-thin-postfix/household_world_map_build_consumer_open_ended_thin/20260625T-postfix-*/eval_results.json`.
All four profiles completed without provider/key failures. All four
fixture-focused prior rows passed the private `room_8_inspection` stable-anchor
gate, and each resolved `anchor_fixture_010` as `Fridge` at
`room_8_inspection` before navigating/observing `room_8`. Prior rows were
`improved` for `codex-router-responses`, `kimi-openai-chat`, and
`minimax-responses`; `mimo-inside-openai-chat` was `no_regression` because its
no-prior row failed early, while its prior row still passed via the same
stable anchor.

Next proof: if broadening release evidence, run the full `map_build_consumer`
live suite including cleanup prior rows. Parked follow-up: one
`mimo-inside-openai-chat` no-prior row produced a complete failed eval artifact
but left the sidecar `live_status.json` at `running-sdk`; this is eval
bookkeeping, not evidence of prior-anchor remapping.

Stop condition: stop before adding a new public map schema, exposing private
fixture/scorer truth, copying Map12 fields wholesale, or claiming target
map-frame object localization from RGB-only observations.

No-touch scope: no new scan-profile choices, no public `scan_profile` axis, no
Map12 field replication, no direct object/fixture target pose from RGB-only
detections.
