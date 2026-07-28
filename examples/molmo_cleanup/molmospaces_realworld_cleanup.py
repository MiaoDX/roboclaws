#!/usr/bin/env python3
"""Thin wrapper for the household-world direct CLI."""

from __future__ import annotations

from roboclaws.household.household_world_episode import (
    SYNTHETIC_BACKEND,
    main,
    run_household_world_episode,
)

__all__ = ["SYNTHETIC_BACKEND", "main", "run_household_world_episode"]


if __name__ == "__main__":
    raise SystemExit(main())
