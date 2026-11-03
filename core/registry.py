"""Module registration and dispatch."""

from typing import Dict, Iterable

from core.contracts import (
    HeatExchangerModule,
    ModuleInput,
    ModuleResult,
    ModuleUnavailableError,
)


class ModuleRegistry:
    def __init__(self) -> None:
        self._modules: Dict[str, HeatExchangerModule] = {}

    def register(self, module: HeatExchangerModule) -> None:
        if module.module_id in self._modules:
            raise ValueError(f"Module already registered: {module.module_id}")
        self._modules[module.module_id] = module

    def all(self) -> Iterable[HeatExchangerModule]:
        return tuple(self._modules.values())

    def get(self, module_id: str) -> HeatExchangerModule:
        try:
            return self._modules[module_id]
        except KeyError as exc:
            raise KeyError(f"Unknown module: {module_id}") from exc

    def run(self, module_id: str, module_input: ModuleInput) -> ModuleResult:
        module = self.get(module_id)
        try:
            return module.run(module_input)
        except ModuleUnavailableError as exc:
            return ModuleResult(status="unavailable", errors=(str(exc),))
        except Exception as exc:
            return ModuleResult(status="failed", errors=(str(exc),))
