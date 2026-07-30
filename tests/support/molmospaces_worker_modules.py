from __future__ import annotations

import importlib
from typing import Any


def load_molmospaces_worker_modules() -> Any:
    modules = tuple(
        importlib.import_module(f"roboclaws.backends.molmospaces.{name}")
        for name in (
            "common",
            "dispatch",
            "navigation_runtime",
            "operations",
            "perception_runtime",
            "state_runtime",
        )
    )
    return _WorkerModuleProxy(modules)


class _WorkerModuleProxy:
    def __init__(self, modules: tuple[Any, ...]) -> None:
        object.__setattr__(self, "_modules", modules)

    def __getattr__(self, name: str) -> Any:
        for module in self._modules:
            if hasattr(module, name):
                return getattr(module, name)
        raise AttributeError(name)

    def __setattr__(self, name: str, value: Any) -> None:
        owners = [module for module in self._modules if hasattr(module, name)]
        if not owners:
            raise AttributeError(name)
        for module in owners:
            setattr(module, name, value)
