"""Fail-closed NVIDIA Omniverse EULA policy for Isaac process launches."""

from __future__ import annotations

import os
from collections.abc import MutableMapping

ENVIRONMENT_VARIABLE = "OMNI_KIT_ACCEPT_EULA"
ACCEPTED_VALUE = "YES"


def accepted(*, explicit: bool = False, env: MutableMapping[str, str] | None = None) -> bool:
    environment = os.environ if env is None else env
    return bool(explicit or environment.get(ENVIRONMENT_VARIABLE) == ACCEPTED_VALUE)


def record_acceptance(env: MutableMapping[str, str] | None = None) -> None:
    environment = os.environ if env is None else env
    environment[ENVIRONMENT_VARIABLE] = ACCEPTED_VALUE


def required_message(operation: str, *, supports_flag: bool = True) -> str:
    suffix = " or pass --accept-nvidia-eula" if supports_flag else ""
    return (
        f"{operation} requires NVIDIA Omniverse EULA acceptance; "
        f"set {ENVIRONMENT_VARIABLE}={ACCEPTED_VALUE}{suffix}"
    )
