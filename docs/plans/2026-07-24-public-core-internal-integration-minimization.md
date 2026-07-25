**Status:** Approved; implementation active
**Created:** 2026-07-24
**Last reviewed:** 2026-07-25
**Current implementation contract:** Publish a small, provider-neutral Roboclaws core by replacing
one private Responses identity with an environment-configured profile, keeping Kimi as the only
Chat Completions route, retaining Agibot/B1 as explicit validation-only worlds, removing NVIDIA
model support and retired MiMo routes, and moving private remote operations out of Roboclaws.
**Related plans:** `docs/plans/refactor-coding-agent-provider-registry.md`,
`docs/plans/refactor-mimo-v25-migration.md`, and
`docs/plans/2026-07-24-cloudml-isaac-digital-twin-proof.md`.
**Publication note:** This transition plan contains private migration vocabulary and must remain in
the private repository. It is not part of the sanitized public root commit.

## Plan Ledger

- Plan status: ACTIVE
- Session scope: public-core-internal-integration-minimization
- Parent plans: none
- Child plans: none
- Last updated: 2026-07-25
- Current slice: deterministic implementation and sanitized public-candidate construction complete.
- Next action: obtain human confirmation before publication, then rerun provider and optional-world
  live gates when their documented network, credential, hardware, and safety blockers are cleared.
- Blocked on: provider network state is `unknown` and required Kimi, MiniMax, and custom Responses
  configuration is unset; Agibot physical validation remains on operator hold; strict Isaac
  preflight has only 20.7 GiB free against an 80 GiB minimum and requires explicit EULA acceptance.
- Latest proof: candidate `/tmp/roboclaws-public.fWAgj9` is a one-commit, no-remote public root at
  source commit `2839924f`; its public scan, dependency sync, lint, formatting, full standalone
  suite, explicit/default MolmoSpaces runs, sdist/wheel membership, fresh install, import, and CLI
  smoke pass. The earlier candidate full suite passed before the packaging-only exclusion change;
  the source full fast suite passed after that change.
- Do not touch from this plan: simulator/runtime NVIDIA dependencies, Isaac Lab EULA handling,
  unrelated product task semantics/scoring, or unrelated user changes.

## Preflight Contract

Preflight status: APPROVED

Task source: user request plus the two-round `agent-planning-loop` review and the affected-scope
optional-world follow-up.

Canonical source: `docs/plans/2026-07-24-public-core-internal-integration-minimization.md`

Route: durable `$intuitive-flow` using `$intuitive-refactor` semantics; this is deletion-first
architecture cleanup with optional validation-world and private operations boundaries.

Goal: make the public repository useful without exposing or embedding private provider and
infrastructure knowledge. Roboclaws owns product behavior and local evaluation; official `cml-*`,
existing executor targets, and private configuration own private operations outside it.

Scope:

- Replace the private Mify Responses identity with one provider-neutral `custom-responses` profile
  whose URL, API key, and model ID are required environment values. Delete Codex Router and its
  special transport instead of pretending it is generic.
- Retain `minimax-responses` as the named public Responses comparison and
  `kimi-openai-chat` as the only Chat Completions profile.
- Delete every MiMo Chat/Anthropic route, the removed `mimo-1000` model, associated environment
  keys, provider-specific policy, probes, tests, rows, examples, and current documentation.
- Delete NVIDIA **model/provider** support and comparison rows. Preserve NVIDIA GPU/runtime code
  required by Isaac Lab and other public simulation backends.
- Remove CloudML submission, placement, queue/resource, image registry, JuiceFS/FDS, provider-env
  staging, polling, and result collection from the public Roboclaws tree. Official `cml-*` skills
  own pure CloudML lifecycle; executor owns only cross-platform Repo/storage operations; a private
  ops workflow may coordinate them without duplicating either control plane.
- Remove private clone requirements, private submodule URLs, internal defaults, personal paths,
  private CI jobs/secrets, and private operational documents from the public tree.
- Publish from a sanitized new root commit while keeping the current full history private.
- Require every OpenAI Agents SDK launch to select a provider profile explicitly. There is no
  source default or implicit provider fallback.
- Retain `world=agibot-g2/map-12` / `backend=agibot-gdk` and `world=b1-map12` /
  `backend=isaaclab` as explicit validation-required contracts. Hide both from default external
  discovery and require injected private dependencies only when a maintainer opts in.

Non-goals: no Python plugin architecture, entry-point discovery, private package dependency,
automatic Chat/Responses fallback, backward-compatibility aliases for deleted profiles, public
CloudML SDK, executor reimplementation inside Roboclaws, model-ranking redesign, or simulator
cleanup unrelated to private infrastructure. Do not remove Agibot/B1 route IDs, copy private
SDK/map/scene data into the public snapshot, or claim those validation routes are public defaults.

Entity budget:

- Reuse: one OpenAI Agents SDK driver, the provider registry and evidence-lane policy, Kimi
  thinking policy, MiniMax Responses behavior, existing Agibot/B1 world/backend adapters and route
  overrides, normal local eval/product commands, official `cml-*` skills, existing executor
  Repo/storage targets, `.env` loading, and standard gates.
- Remove/merge: replace the Mify Responses identity with one generic profile and delete Codex
  Router; remove five MiMo route identities, MiMo-only models/helpers, two NVIDIA model entries and
  adapter surface, private live-CI rows, and Roboclaws-owned CloudML control-plane modules/scripts.
- New: at most one runtime profile (`custom-responses`), one bounded dynamic-model resolution path
  for that profile, one neutral maintainer opt-in for optional-world console discovery, and one
  small generic tracked-file/public-surface checker in the public candidate. Exact internal
  identifiers stay in a private untracked release denylist. No new repo, adapter, plugin package,
  or Python entry-point mechanism is allowed.
- Net rule: the provider registry must finish with fewer routes and less conditional code than it
  has before this work. Any additional adapter, compatibility alias, plugin hook, remote execution
  abstraction, or provider-specific branch requires re-approval.

Acceptance:

- SUCCESS: the public snapshot clones and passes deterministic tests without private network,
  credentials, private submodules, or private repository access; its default household world is
  runnable MolmoSpaces/MuJoCo and default discovery omits Agibot/B1; its only Chat profile is Kimi;
  one configured standard-compatible endpoint works through `custom-responses`; MiniMax remains on
  Responses; Codex Router, NVIDIA model, and all MiMo-specific routes are absent; local eval
  commands remain normal Roboclaws commands; explicit Agibot/B1 selection still passes the required
  internal hardware/Isaac gates with injected dependencies; tracked source, built packages, emitted
  artifacts, and public history pass the release scans below. Publication makes no private remote-
  execution claim.
- BLOCKED_NEEDS_DECISION: a private remote class cannot be migrated or explicitly abandoned by its
  owner; the public release must preserve old git ancestry; implementation needs more than the
  entity budget; or retaining a validation route requires redistributing private assets.
- BLOCKED_NEEDS_LOCAL_VALIDATION: Kimi Chat, private `custom-responses`, retained MiniMax,
  explicitly enabled Agibot hardware, or B1/Isaac cannot run because route-specific readiness shows
  a concrete credential, dependency, safety, network, hardware, or runtime blocker. Private remote
  migration completion is separately blocked when an authorized CPU, GPU/DINO, or Isaac receipt
  cannot be obtained.
- INTERMEDIATE_ONLY: provider cleanup or deterministic tests without the clean-room public clone
  and required provider proofs are useful checkpoints, not publication readiness. A public
  candidate may be publication-ready while private CloudML control-plane migration remains
  incomplete, but not while either retained validation route is broken or unproven after migration.
- No regressions: `direct-runner`, local eval selection/scoring, MolmoSpaces/MuJoCo default,
  explicit Agibot/B1 validation routes, generic Isaac Lab support, and OpenAI Agents SDK structured
  tool use retain their contracts.

Verification:

- Deterministic: `ruff check .`; `ruff format --check .`;
  `./scripts/dev/run_pytest_standalone.sh -q`; focused provider, driver, thinking-policy, eval
  catalog, launch, and operator-console tests.
- Integration: run
  `just agent::eval recommend plan=docs/plans/2026-07-24-public-core-internal-integration-minimization.md budget=focused`;
  exercise configuration resolution for all three final profiles; prove an arbitrary
  opaque model ID on `custom-responses` resolves as family `custom` with conservative capabilities;
  prove missing URL/key/model or provider selection fails clearly; prove no deleted profile or
  alias resolves; prove no automatic wire fallback occurs. With private dependencies unset, assert
  default route/catalog/console discovery contains only runnable public worlds and no Agibot/B1
  combinations/readiness; with explicit maintainer opt-in and injected paths, assert both retained
  world/backend IDs resolve; missing optional paths fail before subprocess creation.
- Product-run: run
  `just run::surface surface=household-world world=molmospaces/val_0 backend=mujoco preset=cleanup agent_engine=direct-runner evidence_lane=world-public-labels`;
  also omit `world`/`backend` once and assert the same MolmoSpaces/MuJoCo resolution and terminal
  success; then repeat the bounded household route with `agent_engine=openai-agents-sdk` and
  explicit `provider_profile=kimi-openai-chat`, then `provider_profile=custom-responses`.
- Live: after route-specific readiness, require terminal reports with successful MCP tool calls for
  the Kimi and custom product runs; require
  `just dev::model-provider-health agents-sdk --probe minimax-responses --require-all` for MiniMax.
- Artifact leakage: inject unique fake URL/key/model canaries into mocked readiness and launch
  paths plus fake private dependency roots into optional-world readiness, then recursively scan
  emitted JSON, JSONL, HTML, logs, and errors. Keys, custom endpoint values, and absolute private
  roots must never appear; public identities remain `custom` and logical asset IDs/digests.
- Internal validation: with explicit optional-world discovery and injected dependencies, rerun the
  Agibot non-motion readiness/agent-view gates and the guarded physical navigation/camera/DINO path
  under localization, run-enablement, E-stop, and operator safety gates; retain the ordered B1
  Isaac A runtime, B navigation, and C strict MapBuild/DINO receipts. The current physical hold or
  unavailable hardware/runtime yields `BLOCKED_NEEDS_LOCAL_VALIDATION`, never a simulated substitute.
- Private remote migration: require separate receipts for CPU/MuJoCo, GPU/DINO, and ordered Isaac
  A/B/C before deleting each corresponding CloudML implementation from the maintained private
  branch. These receipts are not public-release gates.
- Publication: build a candidate public tree in a disposable clone, scan tracked files and emitted
  test artifacts for internal domains, private provider names, cluster/resource IDs, registry/storage
  coordinates, personal absolute paths/emails, private secret names, and credential-like values;
  run a secret scanner on the candidate root history; clone it with recursive submodules disabled
  and run setup plus deterministic gates on a network without private DNS; run `uv build`, inspect
  sdist/wheel membership, install in a fresh environment, and smoke the public CLI.

Context: must-read=this plan, `STATUS.md`, `ARCHITECTURE.md`,
`docs/agents/operating-runbook.md`, `docs/human/technical-design.md`, current provider registry,
driver, thinking/evidence policy, eval catalog, `.gitmodules`, CI, active CloudML/Isaac plan, and
the official executor/CML ownership docs; useful=current route verdicts, focused provider/eval/
launch tests, Agibot/B1 dependency inventory, and current remote receipts; avoid-unless-needed=old
provider incident plans, broad output trees, shipped GSD history, and unrelated parked work.

Execution: main=root owns sequencing, the provider/core cleanup, optional-world dependency
isolation, private operations handoff, public candidate construction, and final success/blocker
judgment; worker=none; worker-goal=none. Never overwrite concurrent CloudML/Isaac changes.

To execute:
`/goal execute docs/plans/2026-07-24-public-core-internal-integration-minimization.md with intuitive-flow`

Optional tracking: none.

Approval: authorized by the user on 2026-07-25, including task-scoped commits. It does
not authorize a public push, destructive history rewrite, credential rotation, private asset
redistribution, or physical movement without the existing operator safety gates.

# Public Core And Internal Integration Minimization

## Outcome

The intended boundary is deliberately small:

```text
public Roboclaws
  product/runtime logic
  default public world: MolmoSpaces + MuJoCo
  optional validation worlds: Agibot + B1 (hidden from default discovery)
  local product and eval commands
  OpenAI Agents SDK wire adapters
    Responses: custom-responses, minimax-responses
    Chat:      kimi-openai-chat
             | normal command + neutral artifacts
             v
private ops coordinator
  official cml-resource/cml-train: CloudML resource + lifecycle
  executor targets: Repo + JuiceFS/FDS cross-platform operations
  private config: images, resources, endpoints, credentials, receipts

explicit validation-world selection
  existing thin Agibot/B1 adapters
  injected SDK runner + Map 12 bundle + B1 scene paths
  fail closed when any selected dependency or safety gate is missing
```

Roboclaws knows that one custom endpoint speaks standard-compatible Responses. It does not know
the internal deployment name, which cluster runs it, which storage backs it, or which private
configuration selects operational defaults. The coordinator does not reimplement CloudML schema or
lifecycle parsing already owned by official `cml-*` tooling.

## Fixed Decisions

### Final provider matrix

| Public profile | Wire API | Configuration | Decision |
| --- | --- | --- | --- |
| `custom-responses` | Responses | `CUSTOM_RESPONSES_BASE_URL`, `CUSTOM_RESPONSES_API_KEY`, and `CUSTOM_RESPONSES_MODEL` are required | Generic public name for one standard-compatible private Responses endpoint |
| `minimax-responses` | Responses | URL and key from environment; public model metadata may stay in source | Retain as a public comparison |
| `kimi-openai-chat` | Chat Completions | URL and key from environment; canonical Kimi model stays explicit | Retain as the only Chat route |

There is no public `mify`, `mimo`, `inside`, `token-plan`, Codex Router, or other private router
profile. Private users select `custom-responses` and populate its values locally. The custom model
ID is opaque and has no alias, pricing, or checked-in model entry. Public registry/report metadata
uses stable family/model label `custom`, text-only capability, unknown image transport, and blocked
raw-FPV. Tool calling must be proven live.

The runtime continues to instantiate `OpenAIResponsesModel` for Responses and
`OpenAIChatCompletionsModel` for Kimi. That distinction is real transport behavior, not two ways to
reach every model. The runtime must not retry one wire API through the other. Codex Router's custom
header/settings behavior is deleted with that route and is explicitly outside `custom-responses`.
Kimi's known public-provider User-Agent compatibility and thinking-only behavior remain explicit.

There is no source default for `openai-agents-sdk`. CLI requests and launch packets must contain
one of the three profiles; `ROBOCLAWS_PROVIDER_PROFILE` is an explicit operator configuration, not
a fallback. The Operator Console may visually preselect Kimi, but it must serialize that selection
into every launch packet.

### Optional validation worlds

- Keep `agibot-g2/map-12` / `agibot-gdk` and `b1-map12` / `isaaclab` as stable explicit route IDs.
- Keep `DEFAULT_WORLD_BY_SURFACE["household-world"] = "molmospaces/val_0"`; its default backend is
  MuJoCo and it must remain runnable without any private dependency.
- Mark both retained internal routes `validation-required` and omit their worlds, combinations,
  previews, and readiness from default console/API discovery. A maintainer-only explicit
  `--include-optional-worlds` control may reveal them; dependency presence never auto-enables them.
- Preserve existing launch keys instead of adding an adapter: Agibot consumes `context_json`,
  `runner_script`, `runner_python`, and `agibot_map_artifact_dir`; B1 consumes `map_bundle` and
  `isaac_scene_usd_path` plus its existing alignment/navigation proof inputs.
- Gitignored `.env` may provide neutral path variables that the launch layer maps to those existing
  keys: `ROBOCLAWS_AGIBOT_RUNNER_SCRIPT`, `ROBOCLAWS_AGIBOT_RUNNER_PYTHON`,
  `ROBOCLAWS_AGIBOT_MAP_ARTIFACT_DIR`, `ROBOCLAWS_B1_MAP_BUNDLE`, and
  `ROBOCLAWS_B1_SCENE_USD_PATH`. Per-run `context_json` and safety enablement remain explicit.
- Remove the public candidate's private Agibot submodule URL/gitlink and every hardcoded private
  SDK/map/scene default. Internal users may place dependencies anywhere and reference them through
  the explicit inputs above. Missing files fail before subprocess launch with exact required input
  names; explicit selection never falls back to MolmoSpaces, MuJoCo, or generic Isaac.
- Retention covers route IDs, thin adapters, safety/readiness checks, and neutral schemas. It does
  not authorize redistribution of the current SDK, robot map, B1 scene, or real-derived previews,
  fixtures, and evidence. Public contract tests use tiny synthetic neutral fixtures; internal live
  gates consume the injected real dependency roots.

### NVIDIA scope

"Remove NVIDIA" in this plan means remove hosted NVIDIA model catalog entries, aliases, provider
adapter logic, credentials, probes, tests, benchmark rows, and documentation. It does not mean
removing `nvidia-smi`, CUDA, RTX rendering, Isaac Sim/Lab packages, or license gates used by the
simulation stack.

### Configuration policy

- `.env` remains gitignored and is never read into reports or committed artifacts.
- `.env.example` contains placeholder names and explanations only, never real values or internal
  host/path examples. Optional-world placeholders may name the neutral variables above but not
  private layouts, URLs, robot addresses, or asset identities.
- `custom-responses` requires `CUSTOM_RESPONSES_BASE_URL`, `CUSTOM_RESPONSES_API_KEY`, and
  `CUSTOM_RESPONSES_MODEL` consistently across runtime, readiness, docs, and tests.
- MiniMax retains `MM_BASE_URL` and `MM_API_KEY`; Kimi retains `KIMI_OPENAI_BASE_URL` and
  `KIMI_API_KEY`. Their executable endpoint defaults are removed from source; public documentation
  URLs may remain linked in docs.
- Missing configuration fails before launch with the exact missing variable names. There is no
  fallback to a different endpoint, model, provider, or wire API.
- Private cluster, storage, registry, and repository coordinates do not belong in `.env.example`;
  they belong to private operations configuration.

### Repository policy

- Keep one public application repository. Do not add plugin discovery or Python entry points.
- Reuse the existing executor repository and official `cml-*` skills. Do not create a third private
  ops/plugin repository for this work.
- Keep private SDK/assets outside the public git object graph. The maintained internal environment
  may use a separate checkout or mounted data root, but Roboclaws depends only on explicit paths and
  neutral schemas, not a private Git URL or package import.
- Preserve the existing repository and full history privately. Produce the public repository from
  a reviewed sanitized tree with a new root commit so deleted secrets and internal coordinates are
  not recoverable from old commits.
- A sanitized root prevents carrying old content into the new history; it does not retract content
  already fetched, forked, cached, or indexed. Verify current remote visibility first. Rotate or
  revoke any real credential that was ever exposed; never treat history rewriting as secret
  remediation.
- Construct the publication candidate in a disposable clone or separate release workspace. Do not
  rewrite or orphan the active shared checkout.

## Work Slices

### Slice 0: Freeze The Boundary And Coordinate Active Work

1. Record a machine-readable inventory of tracked references in these categories: internal
   endpoints/domains, provider identities, remote compute, storage/registry, repository URLs,
   personal paths/identities, secret variable names, and private CI integration.
2. Inspect configured remotes and hosting visibility without mutating them. If a real credential
   has already reached a visible remote, stop publication work, revoke/rotate it through the owning
   service, and separately decide whether hosted-history purge is warranted.
3. Classify each match as public product code, generic reusable code, private operation, historical
   evidence, generated fixture, or false positive. The default action for private operation and
   historical internal evidence is deletion from the public snapshot, not line-by-line abstraction.
4. Split scanning policy: public CI contains only generic rules for private IPs, absolute home
   paths, non-public Git protocols, credential assignments, and standard secret detection. Exact
   internal domains, provider names, cluster/storage coordinates, and personal identifiers live in
   an untracked private release denylist applied to the candidate tree.
5. Inventory the retained Agibot/B1 boundary by role: route/adapter/safety code to keep; hardcoded
   private paths/submodule coupling to replace; and real-derived maps, scenes, previews, fixtures,
   docs, or evidence to exclude unless separate redistribution rights are proven. Do not infer
   permission from possession of the private dependency or root MIT license.
6. Stop before touching the currently modified CloudML/Isaac files. Obtain a clean handoff commit
   or owner confirmation, then re-read the final implementation and tests before migration.
7. Map every private remote operation to public Roboclaws, private coordinator, official `cml-*`,
   or existing executor Repo/storage ownership before deleting any working path.

Exit: reviewed inventory, split scan policy, explicit optional-world keep/exclude manifest,
owner-safe CloudML handoff, and an ownership migration map.

### Slice 1: Collapse The Provider Surface

1. Replace only the Mify Responses identity with `custom-responses`. Make its exact base URL, API
   key, and model environment inputs mandatory and keep the request model opaque.
2. Delete Codex Router, its custom header/settings transport, `CODEX_*` configuration, Router-only
   model entries, tests, and docs. `custom-responses` does not support endpoint-specific headers.
3. Add one bounded custom-model resolution path: public family/model label `custom`, text-only
   model capability, unknown image transport, blocked raw-FPV, no catalog aliases/cost, and no
   compatibility lookup. Named profiles remain closed-catalog.
4. Keep the shared Responses reasoning mapping only if both retained Responses profiles need it.
   Keep the Kimi thinking-only and User-Agent compatibility rules as the sole Chat-specific policy.
5. Delete all MiMo OpenAI Chat, MiMo Anthropic, and removed inside-model paths. Migrate current
   callers directly; do not retain aliases or "deprecated" branches.
6. Delete NVIDIA hosted-model support from the provider catalog, direct adapter selection, probes,
   benchmark cases, eval rows, tests, docs, and sample defaults. Verify simulator NVIDIA references
   are untouched.
7. Remove the SDK provider default. Require an explicit CLI/packet profile, migrate every hardcoded
   caller, and fail with the three allowed values when selection is missing. A console preselection
   must still be serialized explicitly.
8. Replace provider-specific live CI with deterministic/mock CI. Live provider checks move to
   explicit maintainer workflows and never run with secrets on untrusted pull requests.

Exit: exactly three OpenAI Agents SDK provider profiles, exactly one Chat profile, no deleted alias
resolves, and focused deterministic tests pass.

### Slice 2: Move Private Remote Operations Out Of Roboclaws

1. Keep only an execution-neutral Roboclaws command/row plus case ID, immutable code/assets digests,
   output directory, terminal marker, exit status, timestamps, and artifact manifest/digests. Do not
   expose provider, cluster, queue, image, mount, storage, or job nouns in public schemas.
2. Assign ownership exactly once:
   - Roboclaws owns local product/eval behavior, graders/checkers, and neutral artifacts.
   - A private ops workflow chooses approved resources/images/assets/cost and sequences operations.
   - Official `cml-resource` and `cml-train` own CloudML context, resource evidence, YAML/template,
     submit, describe, logs/events, stop, and delete.
   - Existing executor targets own Repo operations and JuiceFS/FDS probe/upload/download only.
3. Maintain three independent private migration rows and delete a row's old Roboclaws control-plane
   path only after its own receipt passes or its owner explicitly abandons it:

| Private row | Normal Roboclaws proof | Required private receipt |
| --- | --- | --- |
| CPU/MuJoCo | direct-runner household world-public product row | Terminal success plus code/asset/image digests, normal checker result, and locally consumable downloaded artifacts |
| GPU/DINO | direct-runner map-build with `camera_labeler=grounding-dino` | Authorized GPU success, CUDA/model readiness, checker result, and complete artifact receipt; retry is a new approved attempt |
| Isaac B1 | ordered runtime A, navigation B, and MapBuild/DINO C | Pinned image/assets, durable EULA record, separately accepted A/B/C receipts, and the strict active Isaac-plan metrics |

4. Preserve the active CloudML/Isaac stop gates. Image publication, paid tasks, and retries require
   their own authorization; missing credentials/capacity/runtime after authorization is
   `BLOCKED_NEEDS_LOCAL_VALIDATION`. Do not ask again for an already recorded durable EULA decision
   unless the image/license version materially changes.
5. Exclude all Roboclaws-owned CloudML control-plane code and private nouns from the public
   candidate immediately after local public commands/artifacts pass. Publication does not wait for
   private live receipts and makes no remote support claim.
6. Keep the old implementation only in the maintained private repo/history until all applicable
   row receipts pass. Then delete plan builders, task YAML/status parsing, provider-env packaging,
   storage adapters, submit/collect scripts, private pools/catalog fields, docs, and their tests.

Exit: `PUBLICATION_READY` means the public candidate has only local/neutral contracts;
`PRIVATE_REMOTE_MIGRATION_COMPLETE` independently means every retained row has its own receipt and
the duplicate private implementation is deleted.

### Slice 3: Remove Private Repository And CI Coupling

1. Remove the private Agibot submodule URL/gitlink from the public candidate while retaining the
   two validation-required world/backend IDs, thin adapters, safety/readiness code, neutral schemas,
   and explicit CLI resolution. Remove every hardcoded `vendors/...` or `data/...` dependency
   default; map gitignored path variables and existing launch overrides only after explicit route
   selection.
2. Make default catalog/console/API discovery omit both optional worlds and all associated
   combinations, previews, and readiness. Add at most one explicit maintainer console opt-in; keep
   the existing MolmoSpaces/MuJoCo world and backend defaults unchanged.
3. Provenance-review all Map12/B1-derived tracked assets, fixtures, previews, and evidence. Exclude
   real-derived content lacking redistribution rights from the public candidate and replace only
   necessary contract-test inputs with tiny synthetic neutral fixtures. Internal live runs consume
   real content through injected roots and record logical IDs/digests rather than absolute paths.
4. Remove private repository URLs, internal network probes/defaults, registry/storage defaults,
   personal absolute paths/emails, and private operational instructions from tracked code and
   current docs.
5. Delete internal-only plans, status evidence, generated fixtures, and benchmark artifacts from the
   public snapshot. Preserve them in the private repository; do not redact hundreds of historical
   files merely to keep their filenames public.
6. Reduce GitHub Actions permissions to the minimum needed by deterministic public CI. Remove
   private live-provider matrices and their secret contracts; keep privileged permissions only for
   a separately justified publish job.
7. Add one fast generic public-surface check over candidate tracked text and wire it into public CI.
   Seed-test its generic rules and pair it with an established secret scanner. Apply the exact
   private denylist externally during candidate construction; never publish that identifier list.

Exit: the candidate tracked tree passes the public-surface check and contains no private clone or
network prerequisite; default external discovery runs only public simulation; both validation
routes still resolve explicitly and fail closed when their injected dependencies are absent.

### Slice 4: Build And Validate The Public Root

1. Generate an explicit source-commit-to-candidate membership manifest, then materialize only that
   reviewed file set into a fresh disposable directory. Do not copy `.env`, outputs, caches,
   private plans, active status evidence, or untracked files by broad wildcard.
2. Run fresh `git init` and create a new root commit in that directory. Assert there are no copied
   remotes, tags, replace/graft refs, or old objects. Keep the full-history origin private and do not
   rewrite or force-push it in place.
3. Run tracked-file, artifact, dependency, submodule, large-file, license, and secret scans against
   the exact public candidate. Scan the candidate's full history, even though it should contain only
   the new root and release follow-ups.
4. Clone the candidate as an external user without credentials or private DNS, run
   `uv sync --extra dev`, deterministic gates, and at least one documented mock/direct-runner
   example. Run `uv build`, inspect sdist/wheel membership, install in a fresh environment, and
   smoke import plus the public CLI.
5. Separately inject public Kimi/MiniMax test credentials and private custom Responses config for
   their live gates. Confirm logs and artifacts redact keys and do not echo endpoint details.
6. Present the membership manifest/digest, candidate commit hash, scan reports, deterministic and
   package results, and required provider proof receipts for human approval before any public push.
   Selecting a new empty destination or replacing an existing remote is a separate decision; never
   force-push as an implementation default.

Exit: a publication-ready commit exists and the actual push remains a separate human-authorized
external action.

## Expected File Impact

Provider/runtime ownership centers on:

- `roboclaws/agents/provider_registry.py`
- `roboclaws/agents/drivers/openai_agents_live.py`
- `roboclaws/agents/thinking_policy.py`
- `roboclaws/agents/provider_transport.py` (delete with Codex Router)
- `roboclaws/agents/model_matrix_benchmark.py`
- `scripts/dev/check_model_providers.py`
- `.env.example`, public launch recipes, current model docs, eval rows, and their focused tests

Remote-operation deletion centers on `roboclaws/evals/cloudml_*.py`,
`skills/eval-harness/scripts/eval_harness_cloudml*.py`, CloudML-specific catalog fields,
`scripts/dev/*cloudml*`, storage publishing scripts, their tests, and current CloudML operating
docs. The exact list comes from Slice 0 after the active CloudML/Isaac handoff; this plan does not
pre-authorize deleting a dirty or newly added file by glob.

Agibot/B1 isolation centers on `.gitmodules`, world visibility/readiness, current hardcoded defaults
in `roboclaws/launch/worlds.py` and `roboclaws/household/agibot_sdk_runner.py`, console route
allowlists, real-derived Map 12/B1 fixtures/previews/evidence, affected tests/docs, and explicit
dependency resolution. The world/backend IDs, thin adapters, safety gates, generic Isaac Lab, and
public MolmoSpaces submodule remain; exact keep/exclude decisions are inventory-driven, never
glob-driven.

Public repository cleanup includes `.gitmodules`, private CI jobs, private network-probe defaults,
historical internal plans/status files, and any tracked sample containing private endpoints,
identities, or paths. The generic network-status guard remains available with explicit public or
operator-supplied configuration. Public simulator/runtime files mentioning NVIDIA are retained
when they are not model-provider integrations.

## Failure And Rollback Rules

- Work in small commits ordered provider collapse, optional-world dependency isolation, neutral
  remote boundary, public-tree sanitization, then public-root construction. Keep private per-row
  remote migration and old-code deletion in separate reviewable commits.
- If a retained provider requires a provider-specific transport quirk, document the observed wire
  evidence and decide whether to keep that named profile. Do not hide the quirk in
  `custom-responses` without review.
- If a private remote row fails migration, retain its old CloudML code in the private repository
  and report `PRIVATE_REMOTE_MIGRATION_COMPLETE` as blocked. The sanitized public candidate may
  still become `PUBLICATION_READY`, but it must contain no control plane or remote-support claim.
- If the public scan finds a historical secret, discard and recreate the disposable candidate root.
  Do not mutate or delete the private source history.
- Retain both Agibot/B1 route IDs and their real validation gates. Do not expose them in default
  discovery, copy private assets into the public snapshot, publish an unusable default, auto-enable
  from dependency presence, add a private dependency/stub, or silently fall back during execution.
