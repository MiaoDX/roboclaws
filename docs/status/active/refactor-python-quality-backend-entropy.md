# Python Quality Backend Entropy Ratchet

Owner/session: Codex main session
Started: 2026-06-20
State: active

## Scope

Continue the accepted Python quality/backend entropy campaign one vertical
slice at a time. Source truth remains the active plan; completed slices belong
only in the completed ledger.

## Source Of Truth

- Plan: `docs/plans/refactor-python-quality-backend-entropy.md`
- Completed ledger: `docs/plans/refactor-python-quality-backend-entropy-completed.md`

## Latest Checkpoint

2026-06-21: B1 Base Navigation Map generation now requires accepted label
sources to declare a top-level `source_map_frame_id` and rejects label rows
whose declared source frame is missing or drifts from that top-level frame
before writing shared real-robot / Digital Twin map artifacts. Generated
`semantics.json` frame ids, source-frame spatial contract, rooms, and
inspection waypoints now carry the declared label frame without falling back to
`map`. Focused proof passed: B1 base-navigation map contract tests, Nav2
map-bundle contract tests, cross-environment semantic-map parity tests, B1
base-navigation sidecar tests, touched-file ruff, touched-file format check,
dependency sync, changed-code cleanup review, diff check, and ratchet summary.
Current ratchet before final slice closeout: 0 Ruff complexity violations,
80 oversized modules in the shared checkout.

2026-06-21: Runtime Map Prior Snapshot conversion now preserves declared
runtime-map and Nav2 bundle map frames instead of defaulting source-derived
waypoint, room, and source-navigation metadata to `map`. Online runtime-map
snapshots reject top-level/static-map frame drift plus anchor or generated
waypoint frame drift; direct Nav2 bundle conversion now requires the
source-frame spatial contract, rejects non-object room rows, rejects room or
waypoint frame drift, and publishes the declared map frame in
`source_navigation_map`. Focused proof passed: runtime-prior frame/source
tests, runtime-prior snapshot tests, B1 base-navigation sidecar tests,
cross-environment semantic-map parity tests, touched-file ruff, touched-file
format check, dependency sync, changed-code cleanup review, diff check, and
ratchet summary. Current ratchet before final slice closeout: 0 Ruff
complexity violations, 80 oversized modules in the shared checkout.

2026-06-21: Nav2 map-bundle projection now preserves the validated
`semantics.json frame_ids.map` source frame across projected metric-map
`frame_id`, defaulted inspection-waypoint frames, room source-frame metadata,
and initial robot pose. Bundle validation also rejects present room
`source_map_frame_id` or waypoint `frame_id` values that drift from
`frame_ids.map`, so a coherent source-map artifact cannot project plausible
mixed-frame navigation evidence. Focused proof passed: Nav2 map-bundle
contract tests, cross-environment semantic-map parity tests, touched-file
ruff, touched-file format check, dependency sync, changed-code cleanup review,
diff check, and ratchet summary. Current ratchet before final slice closeout:
0 Ruff complexity violations, 80 oversized modules in the shared checkout.

2026-06-21: Agent SDK speedup-matrix explicit calibration artifacts now fail
as row-level blocked decision-packet evidence when malformed or non-object.
The matrix uses the existing report-performance source boundary for
`calibration_path`, preserves decision-packet generation, and leaves
quality/speed/reducible-bucket evidence empty for the blocked row instead of
letting corrupt calibration evidence escape row status handling. Focused proof
passed: Agent SDK perf-matrix tests, touched-file ruff, touched-file format
check, dependency sync, changed-code cleanup review, diff check, and ratchet
summary. Current ratchet before final slice closeout: 0 Ruff complexity
violations, 80 oversized modules in the shared checkout.

2026-06-21: OpenAI Agents SDK model-input camera-grounded history compaction
now treats JSON-looking MCP tool-output text wrappers as structured sources.
Malformed text content, top-level non-object JSON, and double-encoded
non-object structured camera output fail with source-labelled diagnostics
before compaction can summarize corrupt camera evidence as a plausible
zero-candidate camera-grounded result; explicit plaintext unavailable-body
output remains tolerated. Focused proof passed: OpenAI Agents model-input
config/source tests, touched-file ruff, touched-file format check, dependency
sync, changed-code cleanup review, diff check, and ratchet summary. Current
ratchet before final slice closeout: 0 Ruff complexity violations, 80
oversized modules in the shared checkout.

2026-06-21: The stdlib-only mify MiMo v2.5 image probe now validates provider
HTTP success bodies with a script-local JSON-object source parser before
extracting chat/responses output. Malformed or parseable non-object 200 bodies
now fail as labelled probe response source errors instead of writing `status:
ok` with empty or misleading output, and malformed HTTP error bodies retain an
explicit `HTTP <code> <reason>` source in the fallback diagnostic. Focused
proof passed: mify image probe source tests, touched-file ruff, touched-file
format check, dependency sync, diff check, and ratchet summary. Current ratchet
before final slice closeout: 0 Ruff complexity violations, 80 oversized modules
in the shared checkout.

2026-06-21: Kimi key validation smoke now validates the model reply as a JSON
object through the shared JSON-object text helper and requires
`action == "MoveAhead"` before printing that the key returns parseable JSON.
Prefix/suffix prose, arrays, missing actions, or wrong actions now fail as
source-labelled validation errors instead of producing a false-green key smoke.
Focused proof passed: Kimi key smoke unit tests, touched-file ruff, touched-file
format check, dependency sync, diff check, and ratchet summary. Current ratchet
before final slice closeout: 0 Ruff complexity violations, 80 oversized modules
in the shared checkout.

2026-06-21: Direct `KimiCodingProvider` HTTP success bodies now parse through
the shared JSON-object text helper before action parsing and usage accounting.
Malformed or parseable non-object provider response bodies now fail as
source-labelled provider errors, update provider failure status, and avoid
deriving fallback actions or cost evidence from corrupt wire data. Focused
proof passed: provider VLM unit tests, touched-file ruff, touched-file format
check, dependency sync, changed-code cleanup review, diff check, and ratchet
summary. Current ratchet before final slice closeout: 0 Ruff complexity
violations, 80 oversized modules in the shared checkout.

2026-06-21: Kimi coding provider-health probe response bodies now parse
through the shared JSON-object text helper and validate the minimal
`choices[0].message` shape before extracting visible output. Malformed,
parseable non-object, or wrong-shaped Kimi direct-probe HTTP bodies now become
labelled provider-health `FAIL` diagnostics instead of raw indexing/type
errors or empty-output ambiguity. Focused proof passed: provider-health script
unit tests, touched-file ruff, touched-file format check, dependency sync,
diff check, and ratchet summary. Current ratchet before final slice closeout:
0 Ruff complexity violations, 80 oversized modules in the shared checkout.

2026-06-21: OpenAI-compatible MiMo tool-call argument parsing now recovers
malformed or parseable non-object model output through the shared provider
fallback decision instead of raising from `json.loads` before direct provider
runs can choose a safe action. Valid tool-call dictionaries still use the
existing action/reasoning validator, missing tool-call reasoning can still
fall back to `reasoning_content`, and invalid declared actions still map to
the safe fallback action. Focused proof passed: provider VLM tests plus Nvidia
provider tests, touched-file ruff, touched-file format check, dependency sync,
changed-code cleanup review, diff check, and ratchet summary. Current ratchet
before final slice closeout: 0 Ruff complexity violations, 80 oversized
modules in the shared checkout.

2026-06-21: RAW-FPV visual-labeler Responses API success and error bodies now
route through the shared JSON-object text helper after a UTF-8 source check.
Malformed, non-UTF-8, or parseable non-object provider HTTP success bodies now
fail as labelled RAW-FPV Responses API response source errors, and malformed
or wrong-shaped HTTP error bodies are included in the provider error row
message before visual-labeler predictions can derive confidence from corrupt
wire data. Focused proof passed: RAW-FPV perception probe tests and source
tests, touched-file ruff, touched-file format check, dependency sync,
changed-code cleanup review, diff check, and ratchet summary. Current ratchet
before final slice closeout: 0 Ruff complexity violations, 80 oversized
modules in the shared checkout.

2026-06-21: OpenAI Agents SDK live-timing compact metric summaries now treat
JSON-looking terminal `detail` strings as structured evidence sources. Valid
JSON object details still populate compact RAW-FPV budget counters, plaintext
provider detail remains tolerated and redacted from compact metrics, and
malformed or non-object structured details now emit `detail_source_error` plus
`detail_source_error_kind` before report timing attribution can look complete
from corrupt terminal detail. Focused proof passed: full live runtime unit
file, touched-file ruff, touched-file format check, dependency sync,
changed-code cleanup review, diff check, and ratchet summary. Current ratchet
before final slice closeout: 0 Ruff complexity violations, 80 oversized
modules in the shared checkout.

2026-06-21: OpenAI Agents SDK operator-console readiness now resolves
provider/model settings through `openai_agents_runtime_settings()` before
publishing the provider gate. Unknown `ROBOCLAWS_OPENAI_AGENTS_MODEL` values,
conflicting SDK/Codex model sources, and route-incompatible SDK model overrides
now block console start with the same resolver diagnostics that launch would
hit; `ROBOCLAWS_CODE_AGENT_MODEL` is intentionally not treated as a direct SDK
model source. Focused proof passed: operator-console launcher tests, provider
catalog tests, touched-file ruff, touched-file format check, dependency sync,
changed-code cleanup review, diff check, and ratchet summary. Current ratchet
before final slice closeout: 0 Ruff complexity violations, 80 oversized
modules in the shared checkout.

2026-06-21: Mify Anthropic provider route base-url resolution now fails before
launch readiness when `XM_LLM_ANTHROPIC_BASE_URL` conflicts with the
Anthropic URL derived from `XM_LLM_BASE_URL`. The Python provider registry owns
the derivation and conflict check, `provider_readiness()` reports `ok: false`
with the same source-labelled diagnostic, and the coding-agent shell helper no
longer carries a duplicate URL derivation path. Focused proof passed:
provider catalog tests, coding-agent env helper contract tests, touched-file
ruff, touched-file format check, shell syntax check, changed-code cleanup
review, diff check, and ratchet summary. Current ratchet before final slice
closeout: 0 Ruff complexity violations, 80 oversized modules in the shared
checkout.

2026-06-21: Python quality ratchet baseline reads and Ruff JSON diagnostics
now fail through labelled source-reader diagnostics instead of raw
`json.loads` / type errors from the gate itself. Malformed or non-object
`python_quality_baseline.json` sources return clean `python-quality-ratchet:`
CLI failures, and malformed, non-array, or non-object Ruff JSON output fails
before comparison logic can derive ratchet confidence from a wrong-shaped
diagnostic source. Focused proof passed: python-quality-ratchet unit tests,
touched-file ruff, touched-file format check, direct ratchet summary command,
changed-code cleanup review, diff check, and ratchet summary. Current ratchet
before final slice closeout: 0 Ruff complexity violations, 80 oversized
modules in the shared checkout.

2026-06-21: Model-matrix OpenAI Chat stream `data:` events now fail aloud on
malformed or parseable non-object JSON instead of being silently skipped before
a later valid event can make the stream trial look healthy. Blank lines, SSE
metadata, comments, non-JSON noise, and `data: [DONE]` remain tolerated.
Focused proof passed: model-matrix benchmark unit tests, touched-file ruff,
touched-file format check, dependency sync, changed-code cleanup review, diff
check, and ratchet summary. Current ratchet before final slice closeout: 0
Ruff complexity violations, 80 oversized modules in the shared checkout.

2026-06-21: Operator-console manual-control MCP tool response text now routes
JSON-looking payloads through the shared JSON-object text helper instead of
raw `json.loads` in `control.py`. Malformed or parseable non-object tool
response text now fails as a source-labelled control-call error, writes an
error response row, and avoids a valid-looking `response` payload before
operator intervention state can derive confidence from corrupt MCP text.
Focused proof passed: operator-console control source tests plus existing
operator-console endpoint tests, touched-file ruff, touched-file format check,
dependency sync, changed-code cleanup review, diff check, and ratchet. Current
ratchet before final slice closeout: 0 Ruff complexity violations, 80
oversized modules in the shared checkout.

Previous slice: Operator-console camera-angle state now derives from the already
validated trace JSONL rows collected by `state.py` instead of re-reading
`trace.jsonl` through a private `read_text`/`json.loads` loop in
`state_summary.py`. Malformed trace rows keep the existing operator-visible
Trace source errors, while camera summary state is computed from the same
valid row set used by latest-action state. Focused proof passed:
operator-console state tests, touched-file ruff, touched-file format check,
dependency sync, changed-code cleanup review, diff check, and ratchet. Current
ratchet before final slice closeout: 0 Ruff complexity violations, 80 oversized
modules in the shared checkout.

Previous slice: Visual-grounding HTTP sidecar request bodies and client response
bodies now route through the shared JSON-object text helper instead of local
`json.loads`. Malformed, non-UTF-8, or parseable non-object sidecar request
bodies return source-labelled `bad_request` failure packets before adapter
dispatch, and wrong-shaped HTTP response bodies fail as
`VisualGroundingContractError` source evidence before benchmark or cleanup
consumers can derive candidates from corrupt sidecar wire data. Focused proof
passed: visual-grounding unit and sidecar contract tests, touched-file ruff,
touched-file format check, dependency sync, changed-code cleanup review, diff
check, and ratchet. Current ratchet before final slice closeout: 0 Ruff
complexity violations, 80 oversized modules in the shared checkout.

Previous slice: OpenClaw chat transcript tailing now treats parseable non-object
session rows as flagged invalid row evidence instead of raising `AttributeError`
while pretty-printing the Gateway session JSONL stream. Malformed JSON keeps
the existing `?? invalid json` output, while non-object JSON now prints
`?? invalid json object: <type>` and tailing continues. Focused proof passed:
OpenClaw tailer contract tests, touched-file ruff, touched-file format check,
diff check, and ratchet summary. Current ratchet before final slice closeout:
0 Ruff complexity violations, 80 oversized modules in the shared checkout.

Previous slice: Model-matrix benchmark non-stream provider responses now route
through the shared JSON-object text helper instead of raw `json.loads`.
Malformed or non-object HTTP JSON responses now become source-labelled FAIL
rows tied to the case id and benchmark layer before output extraction, token
usage, or route-support summaries can derive confidence from corrupt provider
wire data. Focused proof passed: model-matrix benchmark unit tests,
touched-file ruff, touched-file format check, diff check, and ratchet summary.
Current ratchet before final slice closeout: 0 Ruff complexity violations,
80 oversized modules in the shared checkout.

Previous slice: Isaac worker CLI inline waypoint JSON now routes through the
shared JSON-object text helper instead of a local `json.loads` / type check.
Malformed or non-object `navigate_to_waypoint --waypoint-json` payloads now
fail at argparse with source-labelled Isaac worker diagnostics before backend
navigation handling can consume wrong-shaped public waypoint payloads. Focused
proof passed: relative-navigation worker routing tests, touched-file ruff,
touched-file format check, dependency sync, and ratchet summary. Current
ratchet before final slice closeout: 0 Ruff complexity violations, 80
oversized modules in the shared checkout.

Previous slice: MolmoSpaces worker protocol request rows and inline waypoint JSON
now route through the shared JSON-object text helper instead of local
`json.loads` / type checks. Malformed or non-object persistent-worker stdin
requests now return source-labelled worker error packets before command
dispatch, and malformed inline waypoint JSON now uses the same worker source
diagnostics before navigation code can consume wrong-shaped payloads. Focused
proof passed: relative-navigation worker routing tests, touched-file ruff,
touched-file format check. Current ratchet before final slice closeout: 0 Ruff
complexity violations, 80 oversized modules in the shared checkout.

Previous slice: Operator-console HTTP POST bodies now route through the shared
JSON-object source helper instead of raw `json.loads` in the server request
handler. Malformed or non-object browser/operator payloads now return stable
400 JSON diagnostics labelled by HTTP method/path before steer, next-goal,
control, pause, stop, or launch handlers can run; the focused control-endpoint
tests also assert no operator-control rows are written for corrupt request
bodies. Focused proof passed: operator-console control-endpoint tests,
touched-file ruff, touched-file format check. Current ratchet before final
slice closeout: 0 Ruff complexity violations, 80 oversized modules in the
shared checkout.

Previous slice: Launch goal-contract inline JSON now routes through the shared
JSON-object source helper instead of raw `json.loads`. Malformed or non-object
`--goal-contract-json` / `ROBOCLAWS_GOAL_CONTRACT_JSON` payloads now fail with
source-labelled launch diagnostics before prompt rendering, MCP server startup,
or cleanup setup can derive task intent from corrupt inline operator context.
Focused proof passed: launch goal-contract source tests, touched-file ruff,
touched-file format check, and dependency sync. Current ratchet before final
slice closeout: 0 Ruff complexity violations, 80 oversized modules in the
shared checkout.

Previous slice: Molmo cleanup trace-preserving skill CLI now validates inline
`--static-fixture-projection-json` through a skill-local JSON-object source
parser instead of raw `json.loads`. Malformed or non-object inline fixture
projection payloads now fail with concise CLI diagnostics before routine-plan
inspection can derive placement/open-close guidance from corrupt operator
context. The touched skill contract tests also explicitly opt their synthetic
scenario MCP servers into synthetic map projection, matching the current Base
Navigation Map contract. Focused proof passed: Molmo cleanup skill contract
tests, touched-file ruff, touched-file format check, diff check, and ratchet
summary. Current ratchet: 0 Ruff complexity violations, 80 oversized modules
in the shared checkout.

Previous slice: Agibot nav artifact helper reads now fail raw-map gzip JSON and
candidate JSON sources through source-labelled vendor CLI diagnostics instead
of raw `json.load` / `json.loads` tracebacks. `prepare_navigation_target.py`,
`navigate_to_target.py`, and robot-direction overlays now share the same
standalone vendor source boundary for missing, malformed, non-object, or
non-gzip artifacts before deriving offline target validation or live heading
evidence from corrupt saved map artifacts. Focused proof passed: Agibot
map-context source tests, touched-file ruff, touched-file format check, diff
check, and ratchet summary. Current ratchet: 0 Ruff complexity violations,
80 oversized modules in the shared checkout.

Previous slice: Eval-harness required JSON artifact reads now reuse the shared
JSON-object source owner instead of carrying a local duplicate parser and a
stale optional JSON loader in `run_eval_harness.py`. Malformed, non-object, or
missing `eval_results.json` and detached `live_status.json` sources now use
canonical source diagnostics before eval aggregate classification or detached
live-row polling can derive confidence from corrupt artifacts. Focused proof
passed: eval-harness manifest tests, touched-file ruff, touched-file format
check, diff check, and ratchet summary. Current ratchet: 0 Ruff complexity
violations, 80 oversized modules in the shared checkout.

Previous slice: Visual result showcase rendering now routes required
`run_result.json` and present `trace.jsonl` evidence through the shared
JSON-object/JSONL source owners instead of raw local JSON parsing. Malformed or
non-object run artifacts now fail with concise showcase source diagnostics
before GIF/contact-sheet rendering can derive visible proof from corrupt result
or trace evidence. Focused proof passed: visual result showcase skill contract
tests, touched-file ruff, touched-file format check, diff check, and ratchet
summary. Current ratchet: 0 Ruff complexity violations, 80 oversized modules
in the shared checkout.

Previous slice: Molmo cleanup target-query recovery helper now routes explicit
`runtime_metric_map.json` artifact reads through the shared JSON-object source
owner instead of raw `json.loads(path.read_text(...))`. Malformed, missing, or
non-object Runtime Metric Map sources now fail with concise CLI source
diagnostics before offline target recovery can derive confidence from corrupt
public map evidence. Focused proof passed: Molmo cleanup target-query
skill-script contract tests, touched-file ruff, touched-file format check,
diff check, and ratchet summary. Current ratchet: 0 Ruff complexity
violations, 80 oversized modules in the shared checkout.

Previous slice: Molmo cleanup skill scratchpad CLI now routes present
`cleanup_scratch.json` files and inline `--result-json` payloads through one
script-local JSON-object source parser instead of raw `json.loads` calls.
Malformed or non-object scratchpad/result sources now fail with concise CLI
source diagnostics before local agent memory can be validated or updated.
Focused proof passed: Molmo cleanup scratchpad skill-script contract tests,
touched-file ruff, touched-file format check, diff check, and ratchet summary.
Current ratchet: 0 Ruff complexity violations, 80 oversized modules in the
shared checkout.

Previous slice: Scene-Gaussian alignment evidence summarizer now reads required
readiness artifacts, explicit navigation artifacts, and explicit evidence
summary artifacts through one source-labelled JSON-object helper instead of
raw `json.loads` calls. Malformed, missing, or non-object handoff artifacts now
fail with concise CLI source diagnostics before evidence summaries or
alignment manifests can be written from corrupt proof inputs. Focused proof
passed: scene-Gaussian skill contract tests, touched-file ruff, touched-file
format check, diff check, and ratchet summary. Current ratchet: 0 Ruff
complexity violations, 80 oversized modules in the shared checkout.

Previous slice: Agibot SDK cleanup backend explicit JSON inputs now fail through
source-labelled CLI diagnostics instead of raw `json.loads` tracebacks in the
vendor runner. `--context-json`, `--agent-view-json`, live-navigation
`--context-json`, and attached map artifact `source.json` all route through one
runner-local JSON-object source helper, preserving the standalone
`vendors/agibot_sdk` execution context while matching the campaign's
fail-aloud semantics for malformed and non-object source files. Focused proof
passed: Agibot map-context script contract tests, touched-file ruff,
touched-file format check, diff check, and ratchet summary. Current ratchet:
0 Ruff complexity violations, 80 oversized modules in the shared checkout.

Previous slice: Persistent MolmoSpaces worker ready and command-response stdout
packets now route through the shared worker JSON-object source helper instead
of local `json.loads` calls in `roboclaws/household/subprocess_backend.py`.
Malformed or non-object persistent ready/response packets now fail with
`MolmoSpaces persistent worker ...` source diagnostics before worker readiness,
response-id validation, or command result handling can derive confidence from
wrong-shaped structured stdout. Focused proof passed: worker-runner parser
tests, MolmoSpaces persistent packet/source tests, touched-file ruff,
touched-file format check, changed-code cleanup review, and ratchet summary.
Current ratchet: 0 Ruff complexity violations, 80 oversized modules in the
shared checkout.

Previous slice: Repo-local dotenv parsing now has a shared core owner in
`roboclaws/core/dotenv.py`. The operator-console repo `.env` loader and the
provider health/model-matrix dev scripts now use the same no-overwrite,
comment/blank-line skipping, simple quote stripping, and `export ` value-prefix
handling instead of carrying duplicate `read_text`/`splitlines`/local parsing
loops. Explicit provider-script `--dotenv <path>` files still load by exact
file path, and `load_dotenv()` keeps its side-effect behavior on `os.environ`.
Focused proof passed: core dotenv tests, provider-script dotenv wrapper tests,
existing operator-console repo-dotenv test, touched-file ruff, touched-file
format check, diff check, changed-code cleanup review, and ratchet summary.
Current ratchet: 0 Ruff complexity violations, 80 oversized modules in the
shared checkout.

Previous slice: Shared subprocess worker stdout parsing now routes JSON-looking
worker result rows through the core JSON-object text helper instead of a local
`json.loads` loop in `roboclaws/household/worker_runner.py`. MolmoSpaces and
Isaac one-shot backend workers still tolerate ordinary stdout noise and
bracketed log rows such as `[INFO]`, while malformed object-shaped result rows
or parseable non-object rows now fail with line-labelled
`<worker> worker stdout row` source diagnostics before backend callers can use
missing or stale structured worker evidence. Focused proof passed:
worker-runner parser/subprocess tests, MolmoSpaces parser alias test,
touched-file ruff, touched-file format check, diff check, changed-code cleanup
review, and ratchet summary. Current ratchet: 0 Ruff complexity violations,
80 oversized modules in the shared checkout.

Previous slice: Eval-runner tolerant `trace.jsonl` reads now use a core JSONL row
collector instead of a local parser in `roboclaws/evals/runner.py`. The new
core collector keeps partial valid rows plus row-level issues for consumers
that intentionally grade from partial trace evidence, while eval trajectory
graders keep their existing `trace_json_invalid` violation and
`line N: invalid_json...` / `invalid_json_object` wording. Focused proof
passed: core JSON source tests, eval-runner trace-source tests, touched-file
ruff, touched-file format check, diff check, changed-code cleanup review, and
ratchet summary. Current ratchet: 0 Ruff complexity violations, 80 oversized
modules in the shared checkout.

Previous slice: Operator-message inbox JSONL reads now use the console-owned JSONL
row collector instead of a local parser in `interactions.py`. Valid partial
message rows remain visible in list/state views while malformed or non-object
present rows still surface the existing operator-message source-error payload,
and MCP `check_operator_messages` continues to fail closed before returning
queued steering. Focused proof passed: operator-console interaction source
tests, touched-file ruff, touched-file format check, diff check, changed-code
cleanup review, and ratchet summary. Current ratchet: 0 Ruff complexity
violations, 80 oversized modules in the shared checkout.

Previous slice: OpenAI Agents metrics JSONL reads now use the shared JSONL source
owner instead of a local row parser. The existing metrics helper keeps missing
`openai-agents-events*.jsonl`, `openai-agents-spans*.jsonl`, and `trace.jsonl`
sources as intentional empty evidence, while malformed or non-object present
rows now use canonical `OpenAI Agents metrics` or `OpenAI Agents live`
row-source wording before event/span/context-growth metrics or live timing can
derive confidence from partial JSONL artifacts. Focused proof passed:
OpenAI Agents metrics source tests, existing live-runtime metrics source
tests, touched-file ruff, touched-file format check, diff check, changed-code
cleanup review, and ratchet summary. Current ratchet: 0 Ruff complexity
violations, 80 oversized modules in the shared checkout.

Previous slice: RAW-FPV perception probe Codex event artifact reads now use the
shared JSONL source owner instead of a local row parser. The shared helper can
also return source line numbers for callers that need row-local secondary
parsing, so malformed or non-object present `codex-events*.jsonl` rows use
canonical `RAW-FPV Codex event` row-source wording before observation frames
can be collected from partial event evidence, while embedded MCP observe-result
errors still point at the original event line. Focused proof passed: core JSON
source tests, RAW-FPV perception probe tests, touched-file ruff,
touched-file format check, diff check, changed-code cleanup review, and
ratchet summary. Current ratchet: 0 Ruff complexity violations, 80 oversized
modules in the shared checkout.

Previous slice: Operator-console trace/event/control/history JSONL row reads
now share one console-owned JSONL row collector instead of three local
`read_text`/`splitlines`/`json.loads` loops. State and history display paths
still keep valid partial rows visible while surfacing malformed or non-object
present rows as source errors, and operator control remains fail-fast before
appending a new operator command. Focused proof passed: operator-console
state/history/control endpoint tests, touched-file ruff, touched-file format
check, diff check, changed-code cleanup review, and ratchet summary. Current
ratchet: 0 Ruff complexity violations, 80 oversized modules in the shared
checkout.

Previous slice: OpenAI Agents RAW-FPV budget guard trace reads now route
present `trace.jsonl` rows through the shared JSONL source helper instead of a
local row parser. Missing trace files remain the intentional no-budget-evidence
path, while malformed or non-object present rows use canonical
`OpenAI Agents budget trace` `path:row` source wording before candidate,
repeated-failure, or observe-per-waypoint budget decisions can derive
confidence from partial trace history. Focused proof passed: OpenAI Agents
budget source/behavior tests, touched-file ruff, touched-file format check,
diff check, changed-code cleanup review, and ratchet summary. Current ratchet:
0 Ruff complexity violations, 80 oversized modules in the shared checkout.

Previous slice: Model-latency calibration JSONL reads now route present
`model_call_metrics.jsonl` rows through the shared JSONL source helper instead
of a local row parser. Missing metric files remain the intentional empty-source
path for insufficient-sample diagnostics, while malformed or non-object
present rows now use canonical `model-call metrics` `path:row` source wording
before calibration fitting, holdout validation, or coefficient-set evidence can
derive confidence from partial model-call telemetry. Focused proof passed:
calibration/report-performance unit tests, touched-file ruff, touched-file
format check, diff check, changed-code cleanup review, and ratchet summary.
Current ratchet: 0 Ruff complexity violations, 80 oversized modules in the
shared checkout.

Previous slice: Report-performance JSONL reads now route through the shared JSONL
source helper instead of a local row parser, while preserving the
`ReportPerformanceSourceError` boundary for trace, OpenAI Agents span,
Codex/Claude event, and provider-request metrics consumers. Malformed and
non-object present rows now use canonical `path:row` source wording before
report-performance metrics or comparison rows can derive confidence from
partial JSONL evidence. Focused proof passed: report-performance
trace/span/provider JSONL source tests, provider-request happy-path test,
touched-file ruff, touched-file format check, diff check, changed-code cleanup
review, and ratchet summary. Current ratchet: 0 Ruff complexity violations,
80 oversized modules in the shared checkout.

Previous slice: Codex and Claude live cleanup timing trace readers now route
present `trace.jsonl` and Codex event JSONL rows through the shared JSONL
source helper instead of duplicate local row parsers. Missing trace sidecars
remain optional, while malformed or non-object present rows keep route-labelled
source errors before live timing can derive MCP timing confidence. Focused
proof passed: Codex/Claude live timing trace-source tests, Codex event-summary
source test, touched-file ruff, touched-file format check, diff check,
changed-code cleanup review, and ratchet summary. Current ratchet: 0 Ruff
complexity violations, 80 oversized modules in the shared checkout.

Previous slice: Isaac runtime checker no longer carries the unreachable
`_trace_events_from_path` helper. Current cleanup trace and Isaac
semantic-pose trace source validation live in their dedicated checker owners,
so the stale raw JSONL reader is removed instead of hardened. Focused proof
passed: exact no-reference search, cleanup-result checker contract test, fake
Isaac backend cleanup test, touched-file ruff, touched-file format check, diff
check, changed-code cleanup review, and ratchet summary. Current ratchet: 0
Ruff complexity violations, 80 oversized modules in the shared checkout.

Previous slice: Household cleanup and Agibot map-build MCP server self-trace
readers now route `trace.jsonl` through the shared JSONL source helper.
Malformed or non-object rows now surface as server-labelled source errors at
the `done` boundary before readiness, policy trace, raw-FPV observation, or
run-result evidence can derive confidence from a partial MCP trace. Focused
cleanup and Agibot MCP server contract tests, touched-file ruff, touched-file
format checks, diff check, changed-code cleanup review, and the ratchet summary
passed. Current ratchet: 0 Ruff complexity
violations, 80 oversized modules in the shared checkout.

Previous slice: Planner manipulation probe stdout parsing now fails malformed or
non-object JSON-looking worker rows aloud instead of silently skipping them
before timeout/runtime diagnostics are attached to manipulation evidence.
Ordinary non-JSON log lines remain tolerated. Focused planner manipulation
checker tests, touched-file ruff, touched-file format checks, diff check,
changed-code cleanup review, and the ratchet summary passed. Current ratchet:
0 Ruff complexity violations, 80 oversized modules in the shared checkout.

Previous slice: Cleanup artifact-report trace JSONL reads now route through
the shared JSONL source helper instead of a local parser. Malformed or
non-object trace rows now fail with row-labelled `cleanup report trace` source
errors before stale cleanup report re-rendering can derive semantic timeline
evidence from partial trace data. Focused artifact-report contract tests,
touched-file ruff, touched-file format checks, diff check, changed-code
cleanup review, and the ratchet summary passed. Current ratchet: 0 Ruff
complexity violations, 80 oversized modules in the shared checkout.

Previous slice: RAW-FPV private-label trace JSONL reads now route through the
shared JSONL source helper instead of a local parser. Malformed or non-object
trace rows now fail with row-labelled `RAW-FPV private-label trace` source
errors before private-label generation can derive first-sweep observations
from partial trace evidence. Focused RAW-FPV perception probe tests,
touched-file ruff, touched-file format checks, diff check, changed-code
cleanup review, and the ratchet summary passed. Current ratchet: 0 Ruff
complexity violations, 80 oversized modules in the shared checkout.

Previous slice: Isaac semantic-pose checker trace JSONL reads now route through
the shared JSONL source helper instead of a local parser. Malformed or
non-object trace rows now fail with row-labelled `Isaac semantic-pose trace`
source errors before semantic-pose pick/place provenance checks can derive
confidence from partial trace evidence. Focused semantic-pose and cleanup
trace-source checker tests, touched-file ruff, touched-file format checks,
diff check, changed-code cleanup review, and the ratchet summary passed.
Current ratchet: 0 Ruff complexity violations, 80 oversized modules in the
shared checkout.

Previous slice: Agibot map-build checker trace JSONL reads now route through the
shared JSONL source helper instead of a local parser. Malformed or non-object
trace rows now fail with row-labelled `Agibot map-build trace` source errors
before public-trace privacy checks or duplicate-navigation checks can derive
confidence from partial trace evidence. Focused Agibot and cleanup trace-source
checker tests, touched-file ruff, touched-file format checks, diff check,
changed-code cleanup review, and the ratchet summary passed. Current ratchet:
0 Ruff complexity violations, 80 oversized modules in the shared checkout.

Previous slice: Isaac Lab runtime smoke checker sidecar reads now reserve
stdout-last-JSON tolerance for `--init-result` only. Explicit `--state-path`
and `--robot-views-result` artifacts route through the shared JSON-object
source helper, so prefixed log text, malformed JSON, or non-object sidecars
fail with path-labelled source errors before the checker can assemble
valid-looking state/robot-view confidence. Focused runtime-smoke checker
tests, touched-file ruff, touched-file format checks, diff check,
changed-code cleanup review, and the ratchet summary passed. Current ratchet:
0 Ruff complexity violations, 80 oversized modules in the shared checkout.

Previous slice: MolmoSpaces grasp initial-contact diagnostics now validate
explicit candidate grasp JSON in the parent before launching the child probe.
Present malformed or non-object candidate grasp files fail with path-labelled
`candidate grasp JSON` source errors, while missing candidate files keep the
existing blocked-result path and valid candidates still reach the probe.
Focused initial-contact diagnostics tests, touched-file ruff, touched-file
format checks, diff check, and the ratchet summary passed. Current ratchet:
0 Ruff complexity violations, 80 oversized modules in the shared checkout.

Previous slice: Generated-mess placement seeding now reuses the canonical
generated-mess manifest relation/index validators in both MolmoSpaces and
Isaac scenario-state helpers. Persisted or hand-built worker state with bad
manifest `relation` or `placement_index` values now fails before placement
diagnostics can default to backend-derived `inside`/loop-index values, while
non-manifest seeding keeps its backend fallback behavior. Focused
generated-mess scenario-state, existing generated-mess manifest, MolmoSpaces
worker, and Isaac worker tests, touched-file ruff, touched-file format checks,
diff check, and the ratchet summary passed. Current ratchet: 0 Ruff complexity
violations, 80 oversized modules in the shared checkout.

Previous slice: Camera-control request normalization and backend camera-view spec
builders now reject malformed explicit render-pose vectors instead of
defaulting `target`/`lookat` to origin or deriving a plausible `eye` from bad
input. Canonical eye/target requests require finite 3-number `eye`,
`target`/`lookat`, and `up` vectors; anchor-orbit requests require an explicit
finite target unless they use the narrow focus-receptacle derived-camera path;
non-object view rows now fail instead of disappearing into an empty render
request. MolmoSpaces and Isaac direct camera-spec helpers reuse the same
strict vector parser while Isaac USD-bound target derivation remains covered.
Focused camera-control, MolmoSpaces camera-view, Isaac camera-view, and
scene-camera color-profile tests, touched-file ruff, touched-file format
checks, diff check, changed-code cleanup review, and the ratchet summary
passed. Current ratchet: 0 Ruff complexity violations, 80 oversized modules in
the shared checkout.

Previous slice: Operator-console runtime inventory now surfaces successful Docker
mount-inspect output with malformed or wrong-shaped JSON as a blocking
`source_error` task instead of omitting the running container as if no
repo-relevant mount existed. Normal repo-mounted Docker containers still appear
as running inventory tasks, while Docker absence and nonzero inspect results
remain optional host-probe paths. Focused runtime-inventory tests, touched-file
ruff, touched-file format checks, diff check, changed-code cleanup review, and
the ratchet summary passed. Current ratchet: 0 Ruff complexity violations, 80
oversized modules in the shared checkout.

Previous slice: Operator-console stop handling now treats successful Docker
mount-inspect output with malformed or wrong-shaped JSON as an operator stop
source error instead of silently deciding that no task container is mounted.
Docker absence and nonzero inspect results remain optional cleanup paths, but
corrupt present mount metadata now blocks state rewrite and lock release.
Focused operator-console launcher tests, touched-file ruff, touched-file
format checks, diff check, changed-code cleanup review, and the ratchet
summary passed. Current ratchet: 0 Ruff complexity violations, 80 oversized
modules in the shared checkout.

Previous slice before that: MolmoSpaces visual backend slot capacity config now fails invalid
`ROBOCLAWS_MOLMO_MAX_VISUAL_BACKENDS` and explicit `max_slots` values aloud
instead of falling back to a plausible one-slot backend. Live household launch
reports invalid slot config separately from normal slot contention, and
operator-console runtime inventory surfaces the bad config as a blocking
`source_error` task. Focused visual-slot, live-driver, and runtime-inventory
tests, touched-file ruff, touched-file format checks, diff check,
changed-code cleanup review, and the ratchet summary passed. Current ratchet:
0 Ruff complexity violations, 80 oversized modules in the shared checkout.

Previous slice before that: RAW-FPV perception probe runtime-prior loading now fails explicit
`--runtime-map-prior` paths aloud when missing, including split and equals CLI
spellings, while preserving the default missing prior as intentional no-prior
context. Focused RAW-FPV perception probe tests, touched-file ruff,
touched-file format checks, diff check, changed-code cleanup review, and the
ratchet summary passed. Current ratchet: 0 Ruff complexity violations, 80
oversized modules in the shared checkout.

Previous slice before that: OpenAI Agents model-input compaction threshold parsing now fails
booleans and non-positive values aloud across the env-backed live runtime path,
direct `model_input_compaction.min_chars` metadata, and the perf-profile
`model_input_compaction_min_chars` producer path instead of clamping invalid
values to plausible `1`/`1200` thresholds. Focused OpenAI Agents runtime/config
tests, touched-file ruff, touched-file format checks, diff check, changed-code
cleanup review, and the ratchet summary passed. Current ratchet: 0 Ruff
complexity violations, 80 oversized modules in the shared checkout.

Previous slice before that: MolmoSpaces rigid grasp-cache generation preflight now blocks
malformed, non-object, or path-less successful runtime-probe stdout instead of
reporting `python_ready=True` with blank MolmoSpaces root/assets evidence.
Focused planner task feasibility tests, touched-file ruff, touched-file format
checks, diff check, changed-code cleanup review, and the ratchet summary
passed. Current ratchet: 0 Ruff complexity violations, 80 oversized modules in
the shared checkout.

Previous committed slice before that: Scene-camera comparison MolmoSpaces source provenance now reports
installed-package `direct_url.json` metadata problems as `metadata_unavailable`
or `metadata_unreadable` instead of false `not_installed` provenance. Focused
scene-camera source tests, a nearby manifest serialization contract test,
touched-file ruff, touched-file format checks, diff check, changed-code cleanup
review, and the ratchet summary passed. Current ratchet: 0 Ruff complexity
violations, 80 oversized modules in the shared checkout.

Previous committed slice before that: Environment setup private/report metadata env parsing now fails
present malformed or non-object `ROBOCLAWS_ENVIRONMENT_SETUP_JSON` values aloud
through the shared JSON-object text helper while preserving missing/blank env as
the no-metadata default. Focused core JSON-source and environment setup boundary
tests, touched-file ruff, touched-file format checks, diff check, changed-code
cleanup review, and the ratchet summary passed. Current ratchet: 0 Ruff
complexity violations, 80 oversized modules in the shared checkout.

## Next Action

Pick a fresh fail-aloud/source-truth seam from current ratchet evidence after
committing the Agent SDK perf-matrix calibration source slice. Avoid reopening
Agent SDK speedup-matrix calibration source handling unless fresh matrix
evidence shows malformed or non-object explicit `calibration_path` artifacts
can again abort matrix generation outside row-level blocked decision-packet
evidence, or feed normalized speed deltas without a source error.
Avoid reopening OpenAI Agents SDK model-input camera-grounded MCP
output parsing unless fresh model-input compaction evidence shows malformed or
non-object JSON-looking camera-grounded tool output can again feed a plausible
camera-history summary, or plaintext unavailable-body output is no longer
preserved as the explicit fallback.
Avoid reopening OpenAI Agents SDK console readiness provider/model source parity
unless fresh console or live-launch evidence shows unknown, conflicting, or
route-incompatible SDK model/provider settings can again produce
ready-looking operator-console state before runtime failure.
Avoid reopening
mify Anthropic provider-route base-url resolution unless fresh provider
readiness or coding-agent launch evidence shows conflicting
`XM_LLM_ANTHROPIC_BASE_URL` / `XM_LLM_BASE_URL` values can again produce
ready-looking provider state or a plausible `ANTHROPIC_BASE_URL`.
Avoid reopening
python-quality-ratchet baseline or Ruff diagnostics source parsing unless
fresh gate evidence shows malformed baseline JSON or wrong-shaped Ruff JSON can
again produce raw tracebacks or valid-looking ratchet confidence.
Avoid reopening
model-matrix OpenAI Chat stream event parsing unless fresh provider-benchmark
evidence shows malformed or non-object structured `data:` events can again
produce a valid-looking stream PASS row.
Avoid reopening
operator-console MCP tool response parsing unless fresh manual-control
evidence shows corrupt tool response text can again produce valid-looking
control response or intervention evidence.
Avoid reopening closed visual-slot config, slot-file source readers, Docker mount stop/source
handling, Docker inventory mount source handling, camera-control vectors,
generated-mess relation/index placement fields, initial-contact candidate
grasp source validation, or Isaac runtime smoke sidecar-source validation
without fresh false-green evidence. Avoid reopening Agibot map-build,
Isaac semantic-pose, RAW-FPV private-label, cleanup artifact-report trace, or
planner manipulation probe stdout-source validation unless fresh
checker/generator/report/probe evidence shows false confidence again.
Avoid reopening household cleanup or Agibot map-build MCP self-trace parsing
unless fresh live-server evidence shows corrupt present `trace.jsonl` rows can
again feed readiness/done/run-result evidence.
Avoid reopening the deleted Isaac runtime checker trace helper unless a real
caller appears; current cleanup trace and semantic-pose trace readers are
owned elsewhere.
Avoid reopening Codex/Claude live trace timing JSONL readers unless fresh
live-timing or event-summary evidence shows corrupt present JSONL rows can
again feed route timing/status confidence.
Avoid reopening report-performance JSONL source handling unless fresh
report/comparison evidence shows corrupt present trace, span, event, or
provider-request rows can again feed metrics confidence.
Avoid reopening model-latency calibration JSONL source consolidation unless
fresh calibration evidence shows corrupt present `model_call_metrics.jsonl`
rows can again feed fitting, holdout validation, or coefficient-set confidence.
Avoid reopening OpenAI Agents RAW-FPV budget trace source consolidation unless
fresh budget-guard evidence shows corrupt present `trace.jsonl` rows can again
feed candidate, repeated-failure, or observe-per-waypoint budget confidence.
Avoid reopening operator-console JSONL row collection unless fresh console
state/history/control evidence shows corrupt present JSONL rows can again feed
operator-visible status or append new operator-control rows without source
diagnostics.
Avoid reopening RAW-FPV Codex event artifact source consolidation unless fresh
perception-probe evidence shows corrupt present `codex-events*.jsonl` rows can
again feed observation-frame collection without canonical row-source
diagnostics.

## Touched Areas

- `scripts/molmo_cleanup/run_raw_fpv_perception_probe.py`
- `tests/unit/molmo_cleanup/test_raw_fpv_perception_probe.py`
- `tests/unit/core/test_json_sources.py`
- `roboclaws/operator_console/jsonl_sources.py`
- `roboclaws/operator_console/control.py`
- `tests/unit/operator_console/test_control_sources.py`
- `tests/unit/operator_console/test_history.py`
- `scripts/molmo_cleanup/openai_agents_budget.py`
- `tests/unit/agents/test_openai_agents_budget_sources.py`
- `tests/unit/agents/test_live_runtime.py`
- `scripts/reports/calibrate_model_latency.py`
- `tests/unit/reports/test_calibrate_model_latency.py`
- `tests/unit/reports/test_live_performance.py`
- `scripts/molmo_cleanup/isaac_semantic_pose_checker.py`
- `tests/contract/checkers/test_isaac_semantic_pose_checker_trace_sources.py`
- `scripts/molmo_cleanup/generate_raw_fpv_private_labels.py`
- `tests/unit/molmo_cleanup/test_raw_fpv_perception_probe.py`
- `roboclaws/household/artifact_report.py`
- `tests/contract/reports/test_molmo_cleanup_artifact_report.py`
- `scripts/molmo_cleanup/planner_manipulation_probe_result.py`
- `tests/contract/checkers/test_check_molmo_planner_manipulation_probe.py`
- `roboclaws/household/realworld_mcp_server.py`
- `roboclaws/household/agibot_map_build_mcp_server.py`
- `tests/contract/molmo_cleanup/test_molmo_realworld_mcp_server.py`
- `tests/contract/molmo_cleanup/test_physical_agibot_pilot.py`
- `scripts/molmo_cleanup/isaac_runtime_checker.py`
- `scripts/molmo_cleanup/realworld_agibot_map_build_checker.py`
- `tests/contract/checkers/test_agibot_map_build_checker_trace_sources.py`
- `scripts/isaac_lab_cleanup/check_isaac_lab_runtime_smoke_result.py`
- `tests/unit/molmo_cleanup/test_isaac_lab_runtime_smoke_checker.py`
- `scripts/molmo_cleanup/molmospaces_worker_protocol.py`
- `scripts/molmo_cleanup/molmospaces_subprocess_worker.py`
- `scripts/agibot/capture_map_context_views.py`
- `scripts/agibot/verify_waypoints_with_pnc.py`
- `scripts/agibot/generate_metric_map_from_context.py`
- `scripts/isaac_lab_cleanup/isaac_worker_protocol.py`
- `scripts/isaac_lab_cleanup/isaac_robot_import.py`
- `scripts/isaac_lab_cleanup/build_b1_map12_waypoint_pose_requests.py`
- `scripts/isaac_lab_cleanup/run_b1_map12_navigation_smoke.py`
- `scripts/isaac_lab_cleanup/render_b1_map12_navigation_report.py`
- `scripts/isaac_lab_cleanup/check_b1_map12_readiness.py`
- `scripts/isaac_lab_cleanup/check_b1_map12_asset_visual_comparison.py`
- `scripts/isaac_lab_cleanup/check_prepared_semantic_usd_summary.py`
- `scripts/isaac_lab_cleanup/compare_isaac_segmentation_aov.py`
- `scripts/isaac_lab_cleanup/summarize_isaac_aov_matrix.py`
- `scripts/isaac_lab_cleanup/isaac_scene_camera_geometry.py`
- `scripts/isaac_lab_cleanup/isaac_scenario_builders.py`
- `scripts/isaac_lab_cleanup/install_molmospaces_usd_references.py`
- `scripts/isaac_lab_cleanup/isaac_scene_index_metadata.py`
- `scripts/isaac_lab_cleanup/prepare_molmospaces_flattened_semantic_usd.py`
- `scripts/maps/render_b1_scene_gaussian_topdown.py`
- `scripts/maps/render_b1_map12_manual_alignment_overlay.py`
- `scripts/maps/render_b1_scene_topdown_diagnostic.py`
- `scripts/maps/suggest_b1_map12_manual_anchor_semantics.py`
- `scripts/maps/build_b1_map12_semantic_anchor_review_packet.py`
- `scripts/maps/build_b1_map12_semantic_projection.py`
- `scripts/molmo_cleanup/summarize_robot_camera_visual_parity.py`
- `scripts/maps/render_b1_map12_correspondence_review.py`
- `scripts/maps/fit_b1_map12_scene_alignment.py`
- `scripts/maps/render_b1_map12_manual_alignment_overlay.py`
- `scripts/maps/normalize_semantic_map_spatial_contract.py`
- `scripts/maps/compile_b1_map12_runtime_bundle.py`
- `scripts/maps/check_robot_map12_consistency.py`
- retired legacy Agent View bundle exporter
- `scripts/maps/promote_b1_map12_manual_draft_for_verification.py`
- `scripts/maps/promote_b1_map12_semantic_review_packet.py`
- `scripts/molmo_cleanup/run_molmo_apple2apple_test_grid.py`
- `scripts/molmo_cleanup/run_live_codex_agibot_map_build.py`
- `tests/unit/molmo_cleanup/test_live_codex_agibot_map_build.py`
- `scripts/molmo_cleanup/run_molmo_realworld_agent_mcp_smoke.py`
- `tests/contract/molmo_cleanup/test_molmo_realworld_mcp_smoke_artifacts.py`
- `scripts/visual_grounding/check_visual_grounding_benchmark_result.py`
- `scripts/visual_grounding/run_visual_grounding_benchmark.py`
- `scripts/molmo_cleanup/run_live_codex_cleanup.py`
- `scripts/molmo_cleanup/run_live_claude_cleanup.py`
- `tests/unit/molmo_cleanup/test_ci_live_reports.py`
- `roboclaws/reports/live_performance.py`
- `tests/unit/reports/test_live_performance.py`
- `scripts/visual_grounding/build_visual_grounding_corpus_from_cleanup_run.py`
- `scripts/operator_console/scene_sampler_worklist_alignment.py`
- `scripts/operator_console/run_scene_sampler_source_prep.py`
- `scripts/operator_console/run_scene_sampler_scanner_plan.py`
- `roboclaws/launch/scene_sampler_prefilter.py`
- `roboclaws/launch/scene_sampler_scanner.py`
- `scripts/reports/write_pages_index.py`
- `scripts/reports/compare_live_report_metrics.py`
- `scripts/reports/serve_reports.py`
- `roboclaws/evals/live_artifacts.py`
- `scripts/molmo_cleanup/run_codex_cleanup_apple2apple_summary.py`
- `scripts/molmo_cleanup/run_agent_sdk_perf_matrix.py`
- `scripts/molmo_cleanup/run_molmo_planner_proof_bundle_from_requests.py`
- `scripts/molmo_cleanup/run_raw_fpv_perception_probe.py`
- `scripts/molmo_cleanup/run_robot_camera_apple2apple_comparison.py`
- `scripts/molmo_cleanup/robot_camera_apple2apple_materials.py`
- `roboclaws/household/grasp_initial_contact_diagnostics.py`
- `roboclaws/household/scene_camera_source_artifacts.py`
- `roboclaws/household/agibot_contract_rehearsal.py`
- `roboclaws/household/planner_proof_requests.py`
- `roboclaws/household/planner_task_feasibility.py`
- `scripts/molmo_cleanup/check_molmo_planner_manipulation_probe.py`
- `scripts/molmo_cleanup/check_molmo_planner_proof_bundle_runner_result.py`
- `scripts/molmo_cleanup/check_molmo_realworld_cleanup_result.py`
- `scripts/molmo_cleanup/run_live_claude_cleanup.py`
- `scripts/molmo_cleanup/run_live_openai_agents_cleanup.py`
- `scripts/molmo_cleanup/make_robot_camera_rgb_gain_profile.py`
- `scripts/molmo_cleanup/summarize_live_run.py`
- `roboclaws/maps/runtime_prior_snapshot.py`
- `roboclaws/maps/bundle.py`
- `roboclaws/maps/bundle_validation.py`
- `roboclaws/maps/project.py`
- `roboclaws/household/agibot_map_bundle.py`
- `roboclaws/household/planner_proof_attachment.py`
- `roboclaws/cli/household_agent_server.py`
- `roboclaws/household/realworld_cleanup.py`
- `roboclaws/household/subprocess_backend.py`
- `roboclaws/household/isaac_lab_backend.py`
- `roboclaws/core/json_sources.py`
- `roboclaws/household/camera_control.py`
- `roboclaws/household/ci_live_reports.py`
- `roboclaws/household/artifact_report.py`
- `roboclaws/household/report_sections_isaac.py`
- `tests/unit/molmo_cleanup/test_report_sections_isaac_sources.py`
- `roboclaws/household/scene_camera_usda_contract.py`
- `tests/unit/molmo_cleanup/test_scene_camera_usda_contract_sources.py`
- `roboclaws/household/report_sections_timing.py`
- `roboclaws/household/grasp_cache_generation.py`
- `roboclaws/household/grasp_generation_setup.py`
- `roboclaws/household/grasp_pose_policy_cache.py`
- `roboclaws/household/skill_scratchpad.py`
- `roboclaws/launch/goals.py`
- `roboclaws/evals/models.py`
- `roboclaws/maps/room_semantics.py`
- `roboclaws/household/generated_mess.py`
- `scripts/molmo_cleanup/molmospaces_scenario_state.py`
- `scripts/isaac_lab_cleanup/isaac_scenario_state.py`
- `tests/contract/maps/test_b1_map12_navigation_smoke_cli.py`
- `tests/contract/maps/test_b1_map12_navigation_report.py`
- `tests/contract/maps/test_b1_map12_readiness_cli.py`
- `tests/contract/maps/test_b1_map12_asset_visual_comparison.py`
- `tests/unit/molmo_cleanup/test_check_prepared_semantic_usd_summary.py`
- `tests/unit/molmo_cleanup/test_isaac_segmentation_aov_compare.py`
- `tests/unit/molmo_cleanup/test_isaac_scenario_builder_sources.py`
- `tests/contract/maps/test_b1_scene_gaussian_topdown.py`
- `tests/contract/maps/test_b1_map12_manual_anchor_semantics_cli.py`
- `tests/contract/maps/test_b1_map12_verified_alignment.py`
- `tests/unit/molmo_cleanup/test_robot_camera_visual_parity_summary_sources.py`
- `tests/contract/maps/test_b1_map12_correspondence_review_cli.py`
- `tests/contract/maps/test_b1_map12_alignment_fit_cli.py`
- `tests/contract/maps/test_b1_map12_manual_alignment_overlay_cli.py`
- `tests/contract/maps/test_cross_environment_semantic_map_parity.py`
- `tests/contract/maps/test_b1_map12_runtime_bundle.py`
- `tests/contract/maps/test_robot_map12_consistency.py`
- `tests/contract/maps/test_agibot_map_bundle_export.py`
- `tests/contract/maps/test_nav2_map_bundle_contract.py`
- `tests/unit/molmo_cleanup/test_apple2apple_test_grid.py`
- `tests/contract/visual_grounding/test_visual_grounding_benchmark_checker_sources.py`
- `tests/contract/visual_grounding/test_visual_grounding_benchmark_runner_sources.py`
- `tests/contract/visual_grounding/test_visual_grounding_corpus_builder.py`
- `tests/unit/molmo_cleanup/test_codex_cleanup_apple2apple_summary.py`
- `tests/unit/molmo_cleanup/test_agent_sdk_perf_matrix.py`
- `tests/unit/molmo_cleanup/test_robot_camera_rgb_gain_profile.py`
- `tests/unit/molmo_cleanup/test_summarize_live_run.py`
- `tests/unit/molmo_cleanup/test_molmo_planner_proof_attachment.py`
- `tests/unit/scripts/test_run_molmo_planner_proof_bundle_from_requests.py`
- `tests/unit/scripts/test_run_molmo_planner_proof_bundle_prior_sources.py`
- `tests/contract/checkers/test_cleanup_checker_planner_proof_request_sources.py`
- `tests/contract/checkers/test_cleanup_checker_b1_manifest_sources.py`
- `tests/contract/checkers/test_cleanup_checker_run_result_sources.py`
- `tests/contract/checkers/test_cleanup_checker_scene_index_sources.py`
- `tests/contract/checkers/test_cleanup_checker_trace_sources.py`
- `tests/contract/checkers/test_planner_checker_source_readers.py`
- `tests/contract/maps/test_runtime_map_prior_snapshot.py`
- `tests/contract/maps/test_runtime_map_prior_source_loading.py`
- `tests/contract/maps/test_scene_room_semantic_overlay.py`
- `tests/contract/agibot/test_agibot_map_context_scripts.py`
- `tests/unit/molmo_cleanup/test_isaac_lab_backend.py`
- `tests/unit/molmo_cleanup/test_backend_state_source_readers.py`
- `tests/unit/molmo_cleanup/test_prepare_molmospaces_flattened_semantic_usd_sources.py`
- `tests/unit/molmo_cleanup/test_isaac_robot_import_sources.py`
- `tests/unit/molmo_cleanup/test_molmospaces_worker_state.py`
- `tests/unit/molmo_cleanup/test_molmospaces_usd_reference_installer.py`
- `scripts/isaac_lab_cleanup/isaac_worker_cli.py`
- `tests/unit/molmo_cleanup/test_relative_navigation_worker_routing.py`
- `scripts/dev/benchmark_model_matrix.py`
- `tests/unit/providers/test_model_matrix_benchmark.py`
- `scripts/dev/model_matrix_benchmark_wire.py`
- `scripts/dev/check_python_quality_ratchet.py`
- `tests/unit/scripts/test_python_quality_ratchet.py`
- `scripts/openclaw/tail-openclaw-chat.py`
- `tests/contract/openclaw/test_tail_openclaw_chat.py`
- `tests/unit/core/test_json_sources.py`
- `tests/unit/molmo_cleanup/test_camera_control.py`
- `tests/unit/molmo_cleanup/test_generated_mess_scenario_state.py`
- `tests/unit/molmo_cleanup/test_ci_live_reports.py`
- `tests/contract/reports/test_molmo_cleanup_artifact_report.py`
- `tests/contract/reports/test_molmo_cleanup_report_timing_sources.py`
- `tests/unit/molmo_cleanup/test_grasp_cache_generation.py`
- `tests/unit/molmo_cleanup/test_grasp_generation_setup.py`
- `tests/unit/molmo_cleanup/test_grasp_pose_policy_cache.py`
- `tests/unit/molmo_cleanup/test_skill_scratchpad_sources.py`
- `tests/unit/molmo_cleanup/test_raw_fpv_perception_probe.py`
- `tests/unit/molmo_cleanup/test_raw_fpv_perception_probe_sources.py`
- `tests/unit/molmo_cleanup/test_robot_camera_prior_probe_sources.py`
- `tests/unit/molmo_cleanup/test_molmo_grasp_initial_contact_diagnostics.py`
- `tests/unit/molmo_cleanup/test_scene_camera_source_artifacts.py`
- `tests/unit/molmo_cleanup/test_agibot_sdk_runner_sources.py`
- `tests/unit/molmo_cleanup/test_agibot_contract_rehearsal_sources.py`
- `tests/unit/evals/test_eval_models.py`
- `tests/unit/operator_console/test_scene_sampler_source_prep_runner.py`
- `tests/unit/operator_console/test_scene_sampler_scanner_runner.py`
- `tests/unit/launch/test_scene_sampler_scanner_sources.py`
- `tests/unit/launch/test_goal_contract_sources.py`
- `tests/unit/reports/test_write_pages_index_sources.py`
- `tests/unit/reports/test_compare_live_report_metrics_sources.py`
- `tests/unit/reports/test_serve_reports_sources.py`
- `tests/unit/evals/test_live_artifacts_sources.py`
- `roboclaws/evals/regression.py`
- `tests/unit/evals/test_regression_promotion_sources.py`
- `roboclaws/evals/runner.py`
- `tests/unit/evals/test_eval_runner_sources.py`
- `roboclaws/reports/live_performance.py`
- `roboclaws/agents/live_runtime.py`
- `roboclaws/agents/drivers/openai_agents_model_input.py`
- `scripts/molmo_cleanup/openai_agents_perf_profile.py`
- `tests/unit/agents/test_live_runtime.py`
- `tests/unit/agents/test_live_runtime_sources.py`
- `tests/unit/agents/test_openai_agents_model_input_config.py`
- `roboclaws/agents/provider_timing_proxy.py`
- `tests/unit/agents/test_provider_timing_proxy.py`
- `roboclaws/agents/drivers/household_live.py`
- `roboclaws/household/visual_backend_slots.py`
- `tests/unit/molmo_cleanup/test_visual_backend_slots.py`
- `roboclaws/operator_console/launch_support.py`
- `roboclaws/operator_console/runtime_inventory.py`
- `tests/unit/agents/test_household_live_driver.py`
- `tests/unit/operator_console/test_runtime_inventory.py`
- `roboclaws/operator_console/launcher.py`
- `roboclaws/operator_console/readiness.py`
- `roboclaws/operator_console/state.py`
- `roboclaws/operator_console/interactions.py`
- `tests/unit/operator_console/test_interactions.py`
- `roboclaws/operator_console/history.py`
- `docs/plans/refactor-python-quality-backend-entropy.md`
- `docs/plans/refactor-python-quality-backend-entropy-completed.md`

## No-Touch Scope

- Do not touch unrelated concurrent command-surface changes.
- Do not touch unrelated operator-console dirty files:
  `roboclaws/operator_console/server.py`,
  `roboclaws/operator_console/static/app.js`, and
  `roboclaws/operator_console/static/index.html`.
- Do not touch unrelated dirty tests:
  `tests/contract/checkers/test_check_molmo_realworld_cleanup_result.py`,
  `tests/contract/dev_tools/test_task_agent_just_recipes.py`,
  `tests/contract/maps/test_b1_map12_base_navigation_map.py`,
  `tests/contract/maps/test_b1_map12_runtime_bundle.py`,
  `tests/contract/maps/test_scene_room_semantic_overlay.py`,
  `tests/unit/launch/test_environment_setup_catalog.py`, and
  `tests/contract/maps/test_b1_map12_base_navigation_sidecar.py`.
- Do not touch unrelated dirty repo-status/plan/runtime files:
  `STATUS.md`, `docs/plans/2026-06-17-b1-map12-two-map-alignment-blocker.md`,
  `roboclaws/launch/catalog.py`, and
  `scripts/maps/compile_b1_map12_runtime_bundle.py`.
- Do not touch unrelated `docs/status/active/2026-06-18-sdk-storage-targets.md`.
- Do not touch unrelated
  `docs/plans/2026-06-20-cross-environment-map-waypoint-source-of-truth.md`.
- Do not touch unrelated
  `scripts/maps/augment_b1_map12_base_navigation_map.py`.
- Avoid adding to `tests/contract/maps/test_b1_map12_verified_alignment.py`
  unless also compacting local debt; it is at the 2000-line hard ceiling.
