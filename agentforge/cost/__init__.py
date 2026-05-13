"""Cost-projection utilities shared by `scripts/cost_extrapolate.py` and the
``/v1/cost/projections`` API route — sub-plan Next03 §3.3.

The projection model itself lives in :mod:`agentforge.cost.projections` so
the FastAPI handler can call it directly instead of globbing for a JSON file
that the operator had to remember to write.
"""

from agentforge.cost.projections import (
    DEFAULT_ASSUMPTIONS,
    SCALE_OVERLAYS,
    RoleAssumption,
    ScaleOverlay,
    ScaleProjection,
    actual_dev_spend,
    build_projections_payload,
    build_scale_projection,
    project_per_role_cost,
    serialize_payload,
)

__all__ = [
    "DEFAULT_ASSUMPTIONS",
    "SCALE_OVERLAYS",
    "RoleAssumption",
    "ScaleOverlay",
    "ScaleProjection",
    "actual_dev_spend",
    "build_projections_payload",
    "build_scale_projection",
    "project_per_role_cost",
    "serialize_payload",
]
