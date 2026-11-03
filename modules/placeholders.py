"""Clearly labelled mock implementations for the six engineering groups."""

from core.contracts import ModuleInput, ModuleResult
from modules.plate_hx.adapter import PlateHeatExchangerAdapter
from modules.regenerator.adapter import RegeneratorAdapter


class PlaceholderModule:
    """Mock module that echoes input without performing engineering work."""

    def __init__(self, module_id: str, display_name: str) -> None:
        self.module_id = module_id
        self.display_name = f"{display_name} [PLACEHOLDER]"
        self.input_mode = "structured"

    def run(self, module_input: ModuleInput) -> ModuleResult:
        return ModuleResult(
            status="success",
            results={
                "placeholder": True,
                "module_id": self.module_id,
                "received_inputs": dict(module_input.values),
            },
            warnings=("Placeholder only; no engineering calculation was executed.",),
        )


MODULES = (
    ("plate_hx", "Plate HX"),
    ("plate_fin_tube_hx", "Plate Fin Tube HX"),
    ("regenerator", "Regenerator"),
    ("condenser", "Condenser"),
    ("evaporator", "Evaporator"),
    ("bell_delaware_shell_and_tube_hx", "Bell-Delaware Shell and Tube HX"),
)


def register_modules(registry) -> None:
    for module_id, display_name in MODULES:
        if module_id == "plate_hx":
            registry.register(PlateHeatExchangerAdapter())
        elif module_id == "regenerator":
            registry.register(RegeneratorAdapter())
        else:
            registry.register(PlaceholderModule(module_id, display_name))
