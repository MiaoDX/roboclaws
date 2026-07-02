# Agent Context Management Research

Date: 2026-07-02

Status: Current decision context. Re-review after any provider SDK context
feature change, after adding a new live provider route, after a repeated
context-window failure, and at least quarterly while long-running live-agent
routes are active.

## Research Question

Roboclaws has long-running OpenAI Agents SDK runs where MCP tool outputs,
camera observations, visual-candidate declarations, and continuation prompts
can grow until the provider rejects the next model call. The question is:

- What is the current community and vendor best practice for context
  management in agentic tool loops?
- Should Roboclaws rely on provider-native compaction, framework memory, or its
  own deterministic policy?
- How should the `baseline` versus `context_managed_v1` profile contract stay
  compatible with provider features without recreating many overlapping
  profiles?

## Summary

Current practice has converged on layered context management, not one magic
compaction step:

```text
source-level tool output shaping
  -> deterministic model-input pruning/summarization
  -> explicit token budgets and hard-limit gates
  -> optional provider-native compaction for conversation/reasoning residue
  -> complete trace/artifact source of truth outside the model context
```

For Roboclaws, this means `context_managed_v1` should stay Roboclaws-owned and
deterministic by default. Provider-native compaction can be an opt-in
sub-capability for compatible Responses-style routes after proof, but it must
not become the source of truth for robot state, checker evidence, Runtime
Metric Map state, or failure classification.

## Current Roboclaws Finding: Camera-Grounded Double History

The current `camera-grounded-labels` path intentionally uses raw FPV frames,
but it currently exposes the observation and label declaration as two model
history entries:

```text
navigate_to_waypoint
  -> observe
     model-visible tool output includes raw_fpv_observation and an instruction
     to call declare_visual_candidates
  -> declare_visual_candidates(observation_id)
     model-visible tool output includes camera_model_candidates and
     model_declared_observations
```

The MCP trace/report path is correct: `observe` records the raw FPV public
observation and `declare_visual_candidates` records the camera-labeler
declaration. The problem is SDK model history growth. Every waypoint can add
both a raw observation output and a declaration output to the next model input.
On a MapBuild sweep this repeats many times.

The SDK-private `observe_camera_grounded_candidates` composite tool is not a
hidden cleanup macro. It still calls the same underlying `observe` and
`declare_visual_candidates` server methods, and the server trace preserves
those semantic substeps. The change is only model-facing: one SDK tool result
returns the current public observation plus declared candidates, instead of
forcing the model to carry a repeated `observe -> declare_visual_candidates`
pair in conversation history.

That matches the external best-practice direction: reduce unnecessary tool
roundtrips and stale tool results before asking a generic compactor to recover.

## Source Survey

### OpenAI

OpenAI documents conversation state as caller-managed unless a stateful
Responses/Conversation mechanism is used. It also explicitly calls out that
context windows include input, output, and reasoning tokens, and that large
prompts or growing history can exceed the model window.

OpenAI now provides three relevant layers:

- `RunConfig.call_model_input_filter` in the Agents SDK: a callback immediately
  before model calls that can edit `ModelInputData`, including trimming to stay
  within a token limit.
- `ToolOutputTrimmer`: a built-in Agents SDK filter that trims large older
  tool outputs while preserving recent turns.
- Responses compaction: server-side and standalone compaction for long-running
  `/responses` interactions. The server-side compaction item is encrypted and
  opaque, intended to carry state forward using fewer tokens rather than to be
  human-reviewed.

Roboclaws interpretation:

- `call_model_input_filter` is the closest match to our deterministic
  `openai_agents_model_input.py` strategy.
- OpenAI server-side compaction is useful for dialogue/reasoning residue on
  compatible Responses routes, but its opaque compaction item is not a
  reviewable robot-state artifact.
- `previous_response_id` and Conversations reduce client plumbing, but they do
  not remove the need for token accounting, because prior chain tokens still
  matter for context/cost.

Sources:

- OpenAI conversation state and context windows:
  https://developers.openai.com/api/docs/guides/conversation-state
- OpenAI Responses compaction:
  https://developers.openai.com/api/docs/guides/compaction
- OpenAI Agents SDK context management:
  https://openai.github.io/openai-agents-python/context/
- OpenAI Agents SDK `RunConfig.call_model_input_filter`:
  https://openai.github.io/openai-agents-python/ref/run_config/
- OpenAI Agents SDK `ToolOutputTrimmer`:
  https://openai.github.io/openai-agents-python/ref/extensions/tool_output_trimmer/

### Anthropic / Claude

Anthropic's public docs and platform features emphasize that longer context is
not automatically better: token count growth degrades focus and recall, so
curating context matters. Its current tool-context guidance separates four
pressure points:

- tool search for large tool definition sets;
- programmatic tool calling for collapsible tool-call chains;
- prompt caching for repeated stable prefixes, with the important caveat that
  caching changes cost/latency but not whether tokens occupy the context
  window;
- context editing for stale `tool_result` blocks.

Anthropic's server-side compaction is recommended for long-running
conversations in that ecosystem, and context editing can clear old tool results
when they are no longer needed.

Roboclaws interpretation:

- The strongest transferable idea is "target the pressure point": collapse
  obvious tool chains, trim stale tool results, and cache stable prefixes.
- Anthropic-style server compaction confirms the industry direction, but it is
  provider-specific and cannot replace Roboclaws-owned audit artifacts.
- Prompt caching is not context management by itself; it should remain a
  latency/cost optimization.

Sources:

- Claude context windows:
  https://platform.claude.com/docs/en/build-with-claude/context-windows
- Claude compaction:
  https://platform.claude.com/docs/en/build-with-claude/compaction
- Claude context editing:
  https://platform.claude.com/docs/en/build-with-claude/context-editing
- Claude tool context:
  https://platform.claude.com/docs/en/agents-and-tools/tool-use/manage-tool-context
- Claude prompt caching:
  https://platform.claude.com/docs/en/build-with-claude/prompt-caching

### LangGraph / LangChain

LangGraph's memory docs separate short-term thread state from long-term stores,
and list common short-term-memory strategies for context windows: trim
messages, delete messages from state, summarize earlier history, manage
checkpoints, and use custom filters.

Roboclaws interpretation:

- The framework consensus is similar to our direction: persistent state and
  model-visible context are different things.
- For robotics, the checkpoint/source-of-truth equivalent is our run directory:
  `trace.jsonl`, `runtime_metric_map.json`, `agent_view.json`, `run_result.json`,
  images, and reports.

Source:

- LangGraph memory and short-term history management:
  https://docs.langchain.com/oss/python/langgraph/add-memory

### MCP And Apps-Style Tool Results

MCP tool results can include unstructured `content` and structured
`structuredContent`; tools may declare `outputSchema`, and clients should
validate structured outputs. The spec also calls out output sanitization,
timeouts, logging, and validating results before passing them to the LLM.

OpenAI Apps SDK follows the same broad design and adds a useful host pattern:
`structuredContent` and `content` are model-visible, while `_meta` is delivered
only to the component and hidden from the model. Roboclaws is not a ChatGPT Apps
SDK app, but the pattern maps well to robotics: keep rich artifacts in the host
and expose only compact public state to the model.

Sources:

- MCP tools specification:
  https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- OpenAI Apps SDK tool results:
  https://developers.openai.com/apps-sdk/reference

## Best-Practice Principles For Roboclaws

1. Source-level reduction first.

   Prefer smaller, task-shaped tool outputs over sending large raw payloads and
   hoping a compactor fixes them later. For camera-grounded labels, this means a
   composite observe+label tool or compact structured output. For repeated maps,
   keep the first full map model-visible and later deltas/summaries only.

2. Preserve complete artifacts outside model context.

   The model does not need every byte of every old tool result. Reviewers,
   checkers, and reports do. Do not delete trace/report/image/runtime-map
   artifacts to save model tokens.

3. Keep deterministic compaction as the default.

   Deterministic summaries are reviewable, testable, and can be tied to public
   IDs, hashes, byte counts, and explicit retention rules. Model/provider
   compaction is harder to audit and should not own robot state.

4. Use provider-native compaction only as an additive compatibility layer.

   Provider compaction may help with reasoning residue and long dialogue
   continuation, but Roboclaws must still apply source-level output shaping,
   deterministic model-input filtering, budgets, and hard-limit gates.

5. Do not treat prompt caching as context control.

   Prompt caching can reduce cost/latency for stable prefixes and tool
   definitions. It does not make those tokens disappear from the context window.

6. Make hard limits fail fast.

   Soft limits trigger compaction/continuation changes. Hard limits protect the
   run from provider-window failures and must produce a classified terminal
   reason. There should be no silent fallback to a larger or unmanaged profile.

7. Keep context policy lane-aware but profile-neutral.

   The public profile surface should remain `baseline` versus
   `context_managed_v1`. Lane/provider differences belong inside the resolved
   `context_managed_v1` payload, not in public profile ids.

## Compatibility Policy

### Profile Compatibility

- Supported profile ids are only `context_managed_v1` and `baseline`.
- `context_managed_v1` is the default for product/operator-console live-agent
  routes.
- `baseline` is explicit-only for A/B comparison and failure reproduction.
- Removed ids (`gpt_compact_v1`, `mimo_compact_v1`,
  `raw_fpv_budgeted_v1`, and `custom`) should fail loudly. Do not keep aliases.

### Provider Feature Compatibility

Provider-native context features should be expressed as fields inside
`context_managed_v1`, not new public profile ids:

```text
agent_sdk_perf_profile:
  profile_id: context_managed_v1
  context_policy:
    source_level_tool_output_reduction: true
    deterministic_model_input_compaction: true
    provider_native_compaction:
      mode: off | responses_server_compaction_v1
      threshold_tokens
      provider_capability
      proof_artifact
```

Recommended default today:

- `provider_native_compaction.mode = off`
- enable only after a provider-specific proof shows:
  - the run still writes complete MCP traces/reports/runtime-map artifacts;
  - deterministic hard-limit checks still fire before provider rejection;
  - context/cost metrics remain attributable;
  - failure classification remains Roboclaws-owned;
  - no private truth or credentials become model-visible.

### Camera-Grounded Composite Compatibility

The composite tool is acceptable only under these constraints:

- scope is `camera-grounded-labels` and SDK-managed routes;
- it calls existing public MCP methods internally;
- trace/report artifacts preserve the underlying `observe` and
  `declare_visual_candidates` events;
- model-visible output is compact, public, and sufficient to choose the next
  action;
- it does not perform hidden cleanup, private scoring, or destination selection.

### Raw-FPV Compatibility

Raw-FPV remains the highest-risk lane for context growth. The managed profile
may keep lane-specific budgets internally:

- retain only the latest full frame model-visible when image memory is enabled;
- summarize older image blocks by public observation id, size, hash, and policy;
- bound candidate attempts and repeated failure fingerprints;
- fail with classified budget/context reasons before provider rejection.

This is still compatible with the two-profile contract because these are
resolved `context_managed_v1` lane policies, not public profile ids.

## Review Checklist

Use this checklist during implementation review and quarterly re-review:

- Does the default product/operator-console route resolve
  `context_managed_v1`, not `baseline`?
- Are old profile ids rejected instead of aliased?
- Is every compaction/summarization rule deterministic or explicitly marked as
  provider-native?
- Are complete MCP traces, reports, images, and runtime-map artifacts still
  present after model-input compaction?
- Does the model-visible packet include public IDs/hashes/counts sufficient for
  debugging without raw payload bloat?
- Does a hard-limit path classify failure before a provider context-window
  rejection?
- Is prompt caching treated as cost/latency only?
- If provider-native compaction is enabled, is it an additive field inside
  `context_managed_v1` with provider-specific proof?
- For `camera-grounded-labels`, does the composite path preserve underlying
  `observe` and `declare_visual_candidates` trace events?
- For raw-FPV, are image retention and candidate budgets lane-specific and
  classified?

## Decision

Adopt `context_managed_v1` as the single managed profile and keep Roboclaws in
control of context management by default. The profile should combine:

- source-level tool output reduction;
- deterministic `call_model_input_filter` compaction;
- compact continuation state;
- lane-neutral observe/context guards;
- lane-specific raw-FPV budgets;
- hard-limit fail-fast classification.

Provider-native compaction is not rejected, but it is not the default and not a
replacement. It is a compatible optional layer only after proof on a specific
provider/wire API.
