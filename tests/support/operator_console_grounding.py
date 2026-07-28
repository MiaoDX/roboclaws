from __future__ import annotations

import json
from pathlib import Path


def write_grounding_gallery_agent_view(run_dir: Path) -> None:
    (run_dir / "agent_view.json").write_text(
        json.dumps(
            {
                "active_perception": {
                    "raw_fpv_observations": [
                        {
                            "observation_id": "raw_fpv_001",
                            "fpv_image": "robot_views/raw_fpv_001.fpv.png",
                            "image_artifacts": {"fpv": "robot_views/raw_fpv_001.fpv.png"},
                        },
                        {
                            "observation_id": "raw_fpv_002",
                            "fpv_image": "robot_views/raw_fpv_002.fpv.png",
                            "image_artifacts": {"fpv": "robot_views/raw_fpv_002.fpv.png"},
                        },
                    ],
                    "model_declared_observations": [
                        {
                            "object_id": "observed_001",
                            "declaration_id": "declared_001",
                            "category": "book",
                            "confidence": 0.379536,
                            "source_observation_id": "raw_fpv_001",
                            "image_region": {"type": "bbox", "value": [0.1, 0.2, 0.3, 0.4]},
                            "grounding_status": "unresolved",
                            "candidate_state": "semantic_candidate",
                            "actionability_status": "needs_clarification",
                            "visual_grounding_evidence": {
                                "source_observation_id": "raw_fpv_001",
                                "image_bbox": [0.1, 0.2, 0.3, 0.4],
                                "grounding_status": "unresolved",
                                "candidate_state": "semantic_candidate",
                                "actionability_status": "needs_clarification",
                                "reviewability_status": "reviewable",
                                "visual_grounding_overlay": (
                                    "visual_grounding/overlays/raw_fpv_001/candidate_001.jpg"
                                ),
                            },
                        },
                        {
                            "object_id": "observed_002",
                            "declaration_id": "declared_002",
                            "category": "electronics",
                            "confidence": 0.272813,
                            "source_observation_id": "raw_fpv_001",
                            "image_region": {"type": "bbox", "value": [0.4, 0.1, 0.2, 0.2]},
                            "visual_grounding_evidence": {
                                "source_observation_id": "raw_fpv_001",
                                "image_bbox": [0.4, 0.1, 0.2, 0.2],
                                "visual_grounding_overlay": (
                                    "visual_grounding/overlays/raw_fpv_001/candidate_002.jpg"
                                ),
                            },
                        },
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
