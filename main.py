"""Terminal entry point for questionnaire, routing, execution, and results."""

from core.contracts import ModuleInput
from core.input_handler import TerminalInputHandler
from core.registry import ModuleRegistry
from core.results import TerminalResultPresenter
from core.selection import select_module
from modules.placeholders import register_modules
from core.labels import expand


def build_registry() -> ModuleRegistry:
    registry = ModuleRegistry()
    register_modules(registry)
    return registry


def main() -> None:
    registry = build_registry()
    input_handler = TerminalInputHandler()
    result_presenter = TerminalResultPresenter()

    while True:
        print("\nHeat Exchanger Routing")
        print("1. Start a new run")
        print("2. Close")
        choice = input("Choose an option: ").strip()
        if choice == "2":
            print("Closing application.")
            return
        if choice != "1":
            print("Invalid menu choice. Enter 1 or 2.")
            continue

        answers = input_handler.collect()
        decision = select_module(answers)
        module = registry.get(decision.module_id)
        print(f"\nRouting path: {decision.path_id}")
        print(expand(f"Solver route: {decision.solver_code}"))
        print(expand(f"Selected module: {module.display_name}"))
        if decision.subtype:
            print(expand(f"Sub-configuration: {decision.subtype}"))
        if decision.alternative_solver_codes:
            alternatives = ", ".join(decision.alternative_solver_codes)
            print(expand(f"Alternative route(s): {alternatives}"))

        if module.module_id == "regenerator":
            if decision.subtype == "Rotary-Ljungstrom":
                if module.rotary_module is None:
                    module_values = {"selected_subtype": decision.subtype}
                else:
                    module_values = {
                        "selected_subtype": decision.subtype,
                        "rotary_inputs": input_handler.collect_rotary_regenerator_inputs(
                            module.rotary_module
                        ),
                    }
            else:
                module_values = input_handler.collect_regenerator_inputs()
                module_values["selected_subtype"] = decision.subtype
        elif module.module_id == "plate_hx":
            module_values = {
                "phe_payload": input_handler.collect_phe_payload(),
                "routing_answers": answers,
                "selected_subtype": decision.subtype,
            }
        elif module.module_id == "evaporator":
            module_values = input_handler.collect_evaporator_inputs(decision.subtype)
            module_values["routing_answers"] = answers
        elif module.module_id == "condenser":
            module_values = input_handler.collect_condenser_inputs()
            module_values["routing_answers"] = answers
        elif module.module_id == "bell_delaware_shell_and_tube_hx":
            module_values = input_handler.collect_bell_delaware_inputs()
            module_values["routing_answers"] = answers
        else:
            module_values = answers
        result = registry.run(module.module_id, ModuleInput(values=module_values))
        result_presenter.present(result)


if __name__ == "__main__":
    main()
