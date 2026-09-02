# Long-Running Agent Context Management

Research date: 2026-09-01  
Scope: community and first-party approaches for long-running agents with tool calls, visual observations, and resumable execution; compared with Roboclaws' current OpenAI Agents SDK path.

## Executive Summary

The strongest community pattern is not “keep appending history and summarize items when the provider rejects the request.” It is a split between (1) durable, queryable execution state and raw evidence, and (2) a deliberately reconstructed model context for the next step.

Three recurring design choices are supported by primary sources:

1. **Thread state is persisted separately from long-term memory.** LangGraph distinguishes thread-scoped checkpoints from cross-thread stores, and explicitly recommends using both for most applications ([memory overview](https://docs.langchain.com/oss/python/concepts/memory), [persistence](https://docs.langchain.com/oss/python/langgraph/persistence)). Letta persists all messages, tool calls, and reasoning even after eviction, while pinning only important memory blocks into the prompt ([stateful agents](https://docs.letta.com/v1-sdk/concepts/stateful-agents/)).
2. **Compaction is proactive and threshold-based.** Google ADK supports token-based compaction with a token threshold and raw-event retention, plus sliding-window compaction with interval and overlap; token-based compaction takes priority when both are configured ([context compaction](https://adk.dev/context/compaction/)). LlamaIndex's `Memory` uses a token limit, a short-term history ratio, and a flush size, moving older material into long-term memory ([memory](https://developers.llamaindex.ai/python/framework/module_guides/deploying/agents/memory/)).
3. **The model should retrieve durable facts/evidence when needed.** AutoGen exposes a `Memory` protocol with `add`, `query`, `update_context`, `clear`, and `close`, rather than requiring all history to remain in the prompt ([memory and RAG](https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/memory.html)). MemGPT frames the same idea as virtual memory: bounded main context plus external tiers and explicit paging/retrieval ([paper](https://arxiv.org/html/2310.08560)).

For Roboclaws, the current design is structurally weaker in one important way: compaction happens on the outgoing item list, but the budget guard runs first. Once measured `max_input_tokens` reaches the 96,000 hard limit, the run fails before compaction can rescue it. The 64,000 soft limit is currently recorded/configured but is not the trigger for a canonical context rebuild. The practical fix is a state-first context assembler with proactive reserve-based compaction, not more continuation retries.

## Findings

### 1. Separate durable state from prompt context

LangGraph defines short-term memory as thread-scoped state persisted by a checkpointer; the state can include conversation history, uploaded files, retrieved documents, and generated artifacts. Long-term memory is application-defined data in a store, shared across threads. Its persistence guide calls out checkpoints for conversation continuity, human-in-the-loop, time travel, and fault tolerance, while stores hold durable facts and shared knowledge.

Letta makes the durability boundary explicit: all state, messages, reasoning, and tool calls are stored in a database and remain retrievable after context eviction. Only selected “core” memory blocks are pinned into the model context. This is directly relevant to robot runs: raw camera/DINO artifacts and MCP traces should remain authoritative even when no longer in the next prompt.

**Implication:** a summary is a cache/view, not the source of truth. Action-critical facts (object identity, pose/waypoint, grasp/place result, completion evidence, safety status) need typed durable records with provenance and revision, not only prose summaries.

### 2. Trigger compaction before the provider limit

Google ADK's token strategy triggers at a configured threshold and retains a specified number of recent raw events. Its sliding-window strategy compacts after a fixed invocation interval and retains overlap. The documentation states that token-based compaction wins when both conditions fire. LlamaIndex similarly reserves a fraction of its token budget for short-term history and flushes a fixed number of tokens to long-term memory when the ratio is exceeded.

**Implication:** use a pre-call budget equation such as `estimated_input + expected_output + safety_reserve <= provider_limit`. Trigger reconstruction at a soft watermark (for example 60-70% of hard capacity), and keep a reserve for the next tool result and completion call. A hard-limit check should be the final fail-closed guard, not the normal cleanup trigger.

### 3. Preserve a recent raw overlap, but do not preserve every raw tool payload

ADK's `event_retention_size` and `overlap_size` preserve immediate conversational context and pronoun resolution while older events are summarized. LlamaIndex's default short-term memory is the newest messages fitting a token limit. These are bounded-tail policies, not unbounded FIFO retention.

**Implication:** retain the current action episode and a small overlap of recent tool calls verbatim; replace older bulky outputs with references and structured summaries. For camera work, preserve the latest observation per active waypoint/object and the evidence URI/hash, while moving full images and detector payloads to artifact storage.

### 4. Retrieval and memory APIs are explicit control-flow operations

AutoGen's memory protocol separates adding memories from querying and updating model context. CoALA describes retrieval, reasoning, and learning as different internal actions, with working memory distinct from semantic and episodic memory ([paper](https://arxiv.org/html/2309.02427)). MemGPT similarly lets the agent page data into and out of a bounded main context.

**Implication:** the next Roboclaws architecture should make `load_task_state`, `retrieve_evidence`, and `record_decision` explicit runtime operations or deterministic pre-model assembly steps. The agent should not need to infer critical state from a lossy transcript.

### 5. Checkpoints and resumability are first-class

LangGraph's checkpointer is explicitly for resuming threads and fault tolerance. Anthropic's agent guidance recommends grounding each step in environment truth (tool/code results), pausing at checkpoints or blockers, and imposing maximum iterations ([Building effective agents](https://www.anthropic.com/engineering/building-effective-agents), published 2024-12-19).

**Implication:** a context-budget event should checkpoint a canonical task snapshot and expose a resumable continuation from that snapshot. A continuation should be a new invocation over reconstructed state, not a second attempt with an increasingly compressed copy of the same transcript.

## Roboclaws Baseline

- Default profile is `context_managed_v1`.
- `camera-grounded-labels`: soft 64k, hard 96k, one continuation, therefore at most two SDK invocation segments.
- `camera-raw-fpv`: two continuations, at most three segments.
- `max_turns=128` is turns inside one SDK invocation; provider retry attempts are separate HTTP retries.
- The model-input filter runs on every model call, but `_raise_budget_failure_before_model_call` runs before `_compact_model_input_items`.
- `provider_context_budget_exceeded` therefore fails before a late compaction can help once measured `max_input_tokens >= 96,000`.
- Current compaction is item replacement: repeated metric-map deltas, oversized public tool outputs, bounded camera-grounded history, and optional raw-FPV image memory. Full MCP trace, reports, and DINO artifacts remain outside the model input.
- `completed_tool_history_limit` is currently zero in the relevant camera-grounded path; compaction does not rebuild a fixed canonical state.

These facts explain the observed MiMo runs ending around 97-98k input tokens despite the configured 96k hard limit: the system is discovering the overage at the guard, not preventing it through a soft-watermark rebuild.

## Recommended Target Architecture

```text
authoritative run ledger
  - task contract / goal
  - current world + robot state
  - object and waypoint records
  - action outcomes and safety gates
  - evidence/artifact references
  - append-only raw events
          |
          +--> checkpoint after every meaningful tool/action boundary
          |
          +--> context assembler before every model call
                 fixed system contract
                 canonical task snapshot
                 recent raw overlap
                 retrieved evidence only for current subgoal
                 bounded output reserve
```

Suggested phases:

1. Keep raw events and artifacts immutable and content-addressed.
2. Update a typed canonical snapshot after each successful tool call.
3. Estimate the next request before provider invocation; trigger assembly at the soft watermark, with output reserve.
4. Assemble from snapshot + recent overlap + targeted retrieval. Never derive the snapshot by repeatedly summarizing the prior prompt.
5. If assembly still exceeds hard capacity, drop low-value retrieval first, then fail with a checkpointed resumable state. Do not spend continuation attempts on the same over-limit payload.

## Contradictions And Uncertainty

- Vendor frameworks differ on whether summarization is LLM-generated or deterministic and on the exact retention unit (events, turns, or tokens). They converge on the boundary and lifecycle, not on one universal algorithm.
- The cited docs are mostly general agent/chat frameworks, not production robot manipulation systems. The recommendation to type object/pose/action state is an application design inference, supported by their separation of working memory, durable state, and external evidence rather than directly prescribed by each vendor.
- Provider-native compaction behavior is not assumed here; Roboclaws currently uses application-side filtering and must budget for provider-specific token accounting.

## Gaps

- No primary source found that publishes a general-purpose, benchmarked policy for preserving robot manipulation state under context compaction.
- We did not compare proprietary provider context-compaction APIs because their semantics and availability vary by route and can change independently of the SDK.
- Retrieval quality and summary fidelity for DINO bounding boxes, poses, and occlusion changes need an in-repo evaluation rather than adoption by analogy.

## Method

Subquestions covered: trigger timing, retained raw tail, durable state location, retrieval/resume, tool-call and visual evidence handling, and hard-budget failure behavior. Sources were official framework documentation, first-party implementation documentation, and original papers. An adversarial pass checked whether each source actually addresses bounded tool-call context rather than only generic chat history; the remaining robot-specific claims are marked as design inference above.

