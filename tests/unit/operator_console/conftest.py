"""Shared selection constants for the operator-console test suite."""

from __future__ import annotations

MUJOCO_OPENAI_AGENTS_OPEN_TASK = (
    "molmospaces/procthor-objaverse-val/0::mujoco::open-task::openai-agents-sdk::"
    "world-public-labels"
)
MUJOCO_SDK_CLEANUP = (
    "molmospaces/procthor-objaverse-val/0::mujoco::cleanup::openai-agents-sdk::world-public-labels"
)
MUJOCO_DIRECT_MAP_BUILD = (
    "molmospaces/procthor-objaverse-val/0::mujoco::map-build::direct-runner::world-public-labels"
)
MUJOCO_SDK_MAP_BUILD = (
    "molmospaces/procthor-objaverse-val/0::mujoco::map-build::openai-agents-sdk::"
    "world-public-labels"
)
B1_OPENAI_AGENTS_OPEN_TASK = "b1-map12::isaaclab::open-task::openai-agents-sdk::world-public-labels"
B1_OPENAI_AGENTS_MAP_BUILD = (
    "b1-map12::isaaclab::map-build::openai-agents-sdk::camera-grounded-labels"
)
B1_OPENAI_AGENTS_CAMERA_GROUNDED = (
    "b1-map12::isaaclab::open-task::openai-agents-sdk::camera-grounded-labels"
)
B1_OPENAI_AGENTS_CLEANUP = "b1-map12::isaaclab::cleanup::openai-agents-sdk::camera-grounded-labels"
AGIBOT_SDK_CLEANUP = (
    "agibot-g2/map-12::agibot-gdk::cleanup::openai-agents-sdk::camera-grounded-labels"
)
AGIBOT_SDK_OPEN_TASK = (
    "agibot-g2/map-12::agibot-gdk::open-task::openai-agents-sdk::camera-grounded-labels"
)
AGIBOT_SDK_MAP_BUILD = (
    "agibot-g2/map-12::agibot-gdk::map-build::openai-agents-sdk::camera-grounded-labels"
)
