"""Engineering-agnostic module contract."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol, Sequence

InputMode = Literal["structured", "interactive", "unavailable"]
ExecutionStatus = Literal["success", "failed", "unavailable", "unknown"]


@dataclass(frozen=True)
class ModuleInput:
    values: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModuleResult:
    status: ExecutionStatus = "success"
    results: Mapping[str, Any] = field(default_factory=dict)
    warnings: Sequence[str] = ()
    errors: Sequence[str] = ()
    artifacts: Sequence[Path] = ()


class HeatExchangerModule(Protocol):
    module_id: str
    display_name: str
    input_mode: InputMode

    def run(self, module_input: ModuleInput) -> ModuleResult: ...


class ModuleUnavailableError(RuntimeError):
    pass
