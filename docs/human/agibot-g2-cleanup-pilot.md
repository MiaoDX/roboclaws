# Agibot G2 导航与感知验证手册

这是 Agibot G2 当前唯一的人类操作手册。它的目标不是证明 physical cleanup
成功，而是证明 **OpenAI Agents SDK 可以通过 Agibot-backed MCP surface 驱动 G2 完成导航 +
感知 + Runtime Metric Map 证据刷新**。

当前硬件验收只接受这个组合：

- public surface/preset: `surface=household-world preset=map-build`
- agent engine: `openai-agents-sdk`
- evidence lane: `camera-grounded-labels`
- backend: `agibot_gdk`
- MCP server: `agibot_map_build`
- policy: `openai_agents_agibot_map_build`
- camera labeler: `grounding-dino`
- checker: `--require-agibot-g2-hardware`

物理抓取和放置还不在验收范围内。`pick`、`place`、`place_inside`、
`open_receptacle`、`close_receptacle` 必须保持 `blocked_capability`。

## 一页流程

```text
自动预检
  -> 人工采集 map context
  -> 人工确认 localization / run enablement / E-stop
  -> PNC waypoint verification（会移动机器人）
  -> SDK dry run（不移动）
  -> 启动 DINO sidecar
  -> SDK hardware run（会移动）
  -> hardware checker
```

`intent=cleanup` 不作为当前 Agibot 真机主验收任务。它会因为 manipulation
正确 blocked 而看起来像“cleanup 没完成”，这不是今天要证明的事。

## 自动预检

这一节可以先跑完。它不需要 G2，不移动机器人，不启动 live SDK agent，不需要
operator 站在机器人旁边。

### 1. 环境和网络

```bash
uv sync --extra dev
set -a && source .env && set +a
scripts/dev/network_status.sh
```

每次 SDK 启动都必须显式选择 profile。默认验证使用 `kimi-openai-chat`，并从
repo-local `.env` 读取 `KIMI_OPENAI_BASE_URL` 和 `KIMI_API_KEY`；也可以显式选择
`codex-responses`、`mimo-responses` 或 `minimax-responses`。不要把 URL、key 或实际请求模型写进日志、报告或文档。

### 2. 离线 Agibot map 转 snapshot

当前 vendor submodule 已包含 `robot_map_12`，直接转换它：

```bash
python -m roboclaws.maps.runtime_prior_conversion agibot-navigation-memory \
  vendors/agibot_sdk/artifacts/maps/robot_map_12 \
  --output output/maps/robot_map_12/runtime_map_prior_snapshot.json \
  --summary-json output/maps/robot_map_12/materialized_targets.json
```

然后跑合约测试：

```bash
./scripts/dev/run_pytest_standalone.sh \
  tests/contract/maps/test_runtime_map_prior_snapshot.py -q
```

检查 `output/maps/robot_map_12/materialized_targets.json`：

- actionable fixture anchor 应该存在，例如 sink、table、sofa 一类目标。
- movable-object prior 只能作为待确认观察证据，不能提升成静态 fixture。
- `costmap_disagrees`、`needs_review`、`observe_only`、`projected` 这类不确定状态要保留。

不要把 fixture fallback 当作正常步骤。vendor map 不完整时，应先修 submodule 或明确
切到测试 fixture；测试 fixture 不是现场 Agibot 准备流程。

### 3. Console route sanity

HTML control console 已经注册了 Agibot G2 Map 12 world + Agibot GDK backend +
map-build intent + OpenAI Agents SDK engine 组合。可以自动验证 gate 和 launcher 仍然可用：

```bash
./scripts/dev/run_pytest_standalone.sh \
  tests/unit/operator_console/test_routes.py \
  tests/unit/operator_console/test_launcher.py \
  tests/unit/operator_console/test_operator_console.py -q
```

也可以 trace 硬件命令是否会路由到 Agibot SDK live runner。这个命令只打印 route，不启动
SDK agent 或机器人：

```bash
ROBOCLAWS_JUST_TRACE=1 just run::surface surface=household-world world=agibot-g2/map-12 backend=agibot-gdk preset=map-build agent_engine=openai-agents-sdk provider_profile=kimi-openai-chat evidence_lane=camera-grounded-labels \
  context_json=output/agibot/map-context/example/agibot_map_context.completed.json \
  output_dir=output/agibot/map-build-hardware \
  policy=openai_agents_agibot_map_build \
  camera_labeler=grounding-dino \
  visual_grounding_timeout_s=20 \
  real_movement_enabled=true
```

期望 trace 里出现：

- `scripts/molmo_cleanup/run_live_openai_agents_agibot_map_build.py`
- `--server-arg=--evidence-lane` / `--server-arg=camera-grounded-labels`
- `--server-arg=--camera-labeler` / `--server-arg=grounding-dino`
- `--server-arg=--real-movement-enabled`

## 人工准备

这一节需要现场 operator。不要在无人看守时运行。

### 1. G2 Pad 和安全边界

operator 必须确认：

- G02 Pad 已选中目标地图。
- G2 已完成 relocalization。
- workspace safety boundary 已确认。
- robot-side E-stop / manual stop 可见可用。
- 现场有人负责 human takeover。

### 2. 采集 map context

先做不移动的 RAW_FPV preflight，确认 `head_color` 能读到真实图片：

```bash
cd vendors/agibot_sdk
uv run python tools/check_raw_fpv_status.py --cameras default-open
```

通过条件：

- `raw_fpv_status=head_color_available`
- `checks[].camera=head_color` 里 `ok=true`
- `shape=[640, 400]` 或现场 GDK 报告的有效尺寸
- `fps>0`
- `head_color_latest.jpg` 是有效现场图片
- `motion_or_write_calls_used=[]`
- `navigation_submission=false`

已知失败模式：

- repo 根目录 `.venv` 是 Python 3.12，不能 import CPython 3.10 的
  `agibot_gdk`。
- 某些 Python 3.10 GDK 环境能 import `agibot_gdk`，但缺 `numpy`；
  `get_latest_image()` 在 materialize `image.data` 时会直接抛出 import error。
  这是环境错误，不要记录成 `head_color_unavailable`。用 `vendors/agibot_sdk`
  下的 `uv run python ...` 跑 preflight，或把 numpy 安装到当前 Python 3.10
  GDK 环境。

然后在可信本地工作站或 Agibot GDK 机器上采集 map、pose 和 `head_color`
camera evidence：

```bash
.venv/bin/python scripts/agibot/capture_map_context_views.py \
  --output-dir output/agibot/map-context/<stamp> \
  --cameras head_color
```

完成后的 `agibot_map_context.completed.json` 必须包含 safety bounds 和 exploration
candidates。它不能依赖手写 room、fixture 或 semantic waypoint。

### 3. 写入 operator gates

real movement 前，`agibot_map_context.completed.json` 必须包含：

```json
{
  "operator_localization_gate": {
    "selected_map_confirmed": true,
    "g02_pad_relocalized": true,
    "localization_ready": true,
    "localization_confidence": 0.92,
    "min_localization_confidence": 0.9,
    "localization_state": "localized",
    "accepted_localization_states": ["localized", "tracking"],
    "operator": "<operator>",
    "confirmed_at": "<iso8601>"
  },
  "operator_run_enablement_gate": {
    "enabled": true,
    "scope": "session",
    "operator": "<operator>",
    "confirmed_at": "<iso8601>"
  }
}
```

### 4. 生成 agent-facing map artifacts

```bash
.venv/bin/python scripts/agibot/generate_metric_map_from_context.py \
  output/agibot/map-context/<stamp>/agibot_map_context.completed.json \
  --output-dir output/agibot/map-context/<stamp>/generated_metric_map
```

人工检查：

- `agent_view.json`
- `metric_map.json`
- `static_fixture_projection.json`
- `semantic_preview.png`

Agent-facing map 不能暴露 raw Agibot map source、GDK internals 或 PNC verification
payload。

### 5. PNC 验证 waypoints

这个步骤会移动机器人。只有 operator 确认地图、定位、安全边界和 stop access 后才能跑：

```bash
.venv/bin/python scripts/agibot/verify_waypoints_with_pnc.py \
  output/agibot/map-context/<stamp>/agibot_map_context.completed.json \
  --all \
  --yes
```

至少一个 waypoint 必须变成 `verified`，并带有：

- `navigation_backend=agibot_gdk`
- `primitive_provenance=agibot_gdk_normal_navi`

第一次 hardware run 只使用 verified waypoint。不要加入隐藏 fallback waypoint、map
switch、自动 relocalization 或任意坐标导航。

## Grounding DINO sidecar

硬件验收要求 `grounding-dino` 成功。没有 visual-grounding HTTP sidecar 时，dry run
可以留下失败证据，但 hardware checker 不会通过。

默认 client 会请求：

```text
http://127.0.0.1:18880/v1/visual-grounding/candidates
```

在单独 terminal 启动 real sidecar：

```bash
UV_PROJECT_ENVIRONMENT="$PWD/.venv-visual-grounding" \
  uv sync --project sidecars/visual-grounding --extra cuda

.venv-visual-grounding/bin/python -m roboclaws.household.visual_grounding_sidecar.service \
  --pipeline real-router --adapter-mode real
```

默认使用 DINO base recall；只有本机需要临时覆盖模型、阈值、device 或 dtype 时才设置
`VISUAL_GROUNDING_DINO_*`、`VISUAL_GROUNDING_DEVICE` 或
`VISUAL_GROUNDING_TORCH_DTYPE`。

如果只是验证 HTTP contract，使用同一个 detector sidecar；缺少真实依赖时它应留下
missing-sidecar / adapter-unavailable 证据，而不是伪造候选：

```bash
.venv/bin/python -m roboclaws.household.visual_grounding_sidecar.service --pipeline grounding-dino
```

## 命令行运行

### 1. SDK dry run

不启用 movement，确认 OpenAI Agents SDK 可以启动并连接
`agibot_map_build` MCP server：

```bash
OPEN_EVIDENCE_REFRESH_PROMPT='基于当前已有 Runtime Metric Map，自主选择 3 个最值得复核的 public semantic anchor 或 inspection waypoint，依次导航过去观察。优先选择 actionability=actionable、needs_review、costmap_disagrees 或缺少当前画面证据的目标；如果目标不可达或证据不清楚，跳过并记录原因。最后调用 done，总结你选择了哪里、为什么选择、每个点看到什么、哪些点被跳过。'

just run::surface surface=household-world world=agibot-g2/map-12 backend=agibot-gdk preset=map-build agent_engine=openai-agents-sdk provider_profile=kimi-openai-chat evidence_lane=camera-grounded-labels \
  context_json=output/agibot/map-context/<stamp>/agibot_map_context.completed.json \
  output_dir=output/agibot/map-build-sdk-dry-run \
  policy=openai_agents_agibot_map_build \
  prompt="$OPEN_EVIDENCE_REFRESH_PROMPT" \
  camera_labeler=grounding-dino \
  visual_grounding_timeout_s=20
```

dry run 应产出：

- `run_result.json`
- `trace.jsonl`
- `runtime_metric_map.json`
- `report.html`

dry run 不能称为 hardware evidence。

### 2. SDK hardware run

只有 operator 确认 run-level gate 后，才启用 movement：

```bash
just run::surface surface=household-world world=agibot-g2/map-12 backend=agibot-gdk preset=map-build agent_engine=openai-agents-sdk provider_profile=kimi-openai-chat evidence_lane=camera-grounded-labels \
  context_json=output/agibot/map-context/<stamp>/agibot_map_context.completed.json \
  output_dir=output/agibot/map-build-hardware \
  policy=openai_agents_agibot_map_build \
  prompt="$OPEN_EVIDENCE_REFRESH_PROMPT" \
  camera_labeler=grounding-dino \
  visual_grounding_timeout_s=20 \
  real_movement_enabled=true
```

产物应写到：

```text
output/agibot/map-build-hardware/<stamp>/seed-7/
```

## HTML control console

可以和 HTML control console 结合。console 仍然走同一个 public selection：
`surface=household-world world=agibot-g2/map-12 backend=agibot-gdk preset=map-build agent_engine=openai-agents-sdk provider_profile=kimi-openai-chat evidence_lane=camera-grounded-labels`。

启动 console：

```bash
just console::run
```

浏览器打开：

```text
http://127.0.0.1:8765
```

选择 route：

```text
Agibot G2 Map Build
```

console 当前支持：

- 选择 Agibot G2 Map Build route。
- 输入 `context_json`。
- 显示 provider、MCP port、context、localization、run enablement、E-stop gates。
- 勾选 `Real movement enabled` 时传入 `real_movement_enabled=true`；不勾选时传入
  `real_movement_enabled=false`，也就是 dry-run。
- route 默认带 `policy=codex_agibot_map_build_pilot`、
  `camera_labeler=grounding-dino` 和 `visual_grounding_timeout_s=20`。
- 自定义 task prompt。
- 持有 `agibot_g2` backend lock。
- 启动 Codex `surface=household-world preset=map-build` run。
- 显示 FPV、map、grounding、outputs、raw evidence。
- 提供 Stop Run 和 Emergency Stop 控件。

建议用法：

- 先不勾选 `Real movement enabled`，跑一次 dry-run，确认 Codex、MCP、context 和 report
  surface 正常。
- operator 完成 localization、run enablement、E-stop 和 DINO sidecar 确认后，再勾选
  `Real movement enabled` 启动 hardware run。
- 勾选后这次 run 会移动机器人；不要在无人看守时使用。

## Hardware checker

hardware run 后执行：

```bash
.venv/bin/python -m roboclaws.household.cleanup_validation_cli \
  output/agibot/map-build-hardware/<stamp>/seed-7/run_result.json \
  --expect-backend agibot_gdk \
  --expect-mcp-server agibot_map_build \
  --require-agent-driven \
  --require-camera-model-policy \
  --expect-visual-grounding-pipeline grounding-dino \
  --require-runtime-metric-map \
  --require-map-build \
  --require-agibot-g2-hardware \
  --min-generated-mess-count 0 \
  --min-sweep-coverage 1.0 \
  --allow-partial-cleanup
```

checker 失败就不接受硬件验收。按 checker 报告的 evidence gap 从最小必要步骤重跑。

## 验收 checklist

`report.html` 和 `run_result.json` 必须同时满足：

- `agent_driven=true`
- `mcp_server=agibot_map_build`
- `evidence_lane=physical-robot-evidence` for physical route evidence, with
  backend provenance described by task-neutral household capability metadata
- `backend_variant=agibot_gdk`
- `physical_navigation_pilot=true`
- `physical_cleanup_ready=false`
- `real_movement_enabled=true`
- `agent_view.policy_view.policy_observation_camera=head_color`
- real movement navigation evidence 是 `agibot_gdk_normal_navi`
- live observation evidence 是 `agibot_gdk_head_color_camera`，并带 image artifacts
- `camera-grounded-labels` 有成功的 External Visual Grounding Service evidence
- `cleanup_policy_trace.agent_reasoning_visible=true`
- visited 和 skipped public waypoint 都包含 decision、progress 和 reason
- no Human Takeover Stop
- manipulation tools 保持 blocked

## 失败处理

出现以下情况，停止 run，把控制权交回 operator：

- 当前 GDK map 与 completed context 不匹配
- localization gate 或 run-enablement gate 缺失
- waypoint 未验证、blocked、timeout 或 unresolved
- `Pnc.normal_navi` 失败或 timeout
- live `head_color` observation 缺失
- hardware acceptance run 中 visual grounding 失败
- robot-side obstacle stop 或 human E-stop 触发

不要在硬件验收里加入隐藏 fallback waypoint、map switch、relocalization attempt、
arbitrary coordinate navigation 或额外 local nudge。

## 不作为当前步骤

- `intent=cleanup` 真机验收：manipulation 未证明，当前不跑。
- `camera-raw-fpv` / RAW_FPV-only cleanup lane：当前 Agibot 硬件验收使用
  `camera-grounded-labels`。但 `head_color` RAW_FPV preflight 是现场前置检查，用来证明
  policy camera 本身可读。
- fake visual-grounding service：不是当前验收路径，不能作为 hardware evidence。
- synthetic cleanup 消费 Agibot snapshot：这是后续合约清理项，不是现场前置条件。
