"""Canonical one-way Opik projection for persisted Roboclaws evidence."""

from roboclaws.evals.opik_projection.client import (
    OpikClientError,
    OpikHttp,
    project_snapshot,
    write_receipt,
)
from roboclaws.evals.opik_projection.harness import (
    ProjectionError,
    build_projection_snapshot,
)
from roboclaws.evals.opik_projection.suite import (
    build_suite_projection_snapshot,
    project_completed_eval_to_opik,
    project_eval_to_opik,
)

__all__ = [
    "OpikClientError",
    "OpikHttp",
    "ProjectionError",
    "build_projection_snapshot",
    "build_suite_projection_snapshot",
    "project_completed_eval_to_opik",
    "project_eval_to_opik",
    "project_snapshot",
    "write_receipt",
]
