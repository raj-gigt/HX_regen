import unittest
import builtins
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
from io import StringIO
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

import main
from core.contracts import ModuleInput
from core.input_handler import TerminalInputHandler
from core.registry import ModuleRegistry
from core.selection import select_module
from modules.placeholders import MODULES, PlaceholderModule, register_modules
from modules.plate_hx.adapter import PlateHeatExchangerAdapter
from modules.evaporator.adapter import EvaporatorAdapter, load_case
from modules.condenser.adapter import CondenserAdapter
from modules.regenerator import fixed_bed_legacy
from modules.regenerator.adapter import RegeneratorAdapter


def sensible_inputs(pairing="Q2-LIQ-LIQ", **overrides):
    values = {
        "Q1": "Q1-SENSIBLE",
        "Q2": pairing,
        "Q3": "Q3-LOW-P",
        "Q4": "Q4-MOD-T",
        "Q5": "Q5-CLEAN",
        "Q6": "Q6-LEAK-OK",
        "Q7": "Q7-MODERATE",
        "Q10": "Q10-COMPACT-CAPEX",
    }
    if pairing == "Q2-LIQ-LIQ":
        values["Q9"] = "Q9-LOW-VISC"
    elif pairing == "Q2-GAS-LIQ":
        values["Q8"] = "Q8-LOWP-GAS-OR-AIR"
    values.update(overrides)
    return values


def path_cases():
    return (
        ("P01", {"Q1": "Q1-COND", "Q3": "Q3-LOW-P", "Q4": "Q4-MOD-T", "Q5": "Q5-CLEAN", "Q6": "Q6-LEAK-OK"}, "MOD-COND", "condenser"),
        ("P02", {"Q1": "Q1-EVAP", "Q3": "Q3-LOW-P", "Q4": "Q4-MOD-T", "Q5": "Q5-CLEAN", "Q6": "Q6-LEAK-OK", "Q9": "Q9-LOW-VISC"}, "MOD-EVAP", "evaporator"),
        ("P03", sensible_inputs("Q2-GAS-GAS", Q3="Q3-LOW-P", Q4="Q4-VHIGH-T", Q6="Q6-LEAK-OK"), "MOD-REGEN", "regenerator"),
        ("P04", sensible_inputs("Q2-GAS-GAS", Q3="Q3-VHIGH-P", Q4="Q4-HIGH-T", Q5="Q5-CLEAN", Q6="Q6-ZERO-LEAK-STD"), "MOD-PFHE", "plate_fin_tube_hx"),
        ("P05", sensible_inputs("Q2-GAS-GAS", Q3="Q3-MED-P", Q5="Q5-MODERATE"), "MOD-STHE", "bell_delaware_shell_and_tube_hx"),
        ("P06", sensible_inputs("Q2-GAS-LIQ", Q3="Q3-HIGH-P", Q4="Q4-VHIGH-T", Q8="Q8-LOWP-GAS-OR-AIR"), "MOD-TFHE", "plate_fin_tube_hx"),
        ("P07", sensible_inputs("Q2-GAS-LIQ", Q3="Q3-HIGH-P", Q4="Q4-MOD-T", Q5="Q5-CLEAN", Q8="Q8-MEDP-GAS", Q10="Q10-COMPACT-CAPEX"), "MOD-PFHE", "plate_fin_tube_hx"),
        ("P08", sensible_inputs("Q2-GAS-LIQ", Q8="Q8-MEDP-GAS", Q5="Q5-MODERATE"), "MOD-STHE", "bell_delaware_shell_and_tube_hx"),
        ("P09", sensible_inputs("Q2-LIQ-LIQ", Q3="Q3-VHIGH-P"), "MOD-STHE", "bell_delaware_shell_and_tube_hx"),
        ("P10", sensible_inputs("Q2-LIQ-LIQ", Q3="Q3-MED-P", Q4="Q4-MOD-T", Q5="Q5-HEAVY", Q6="Q6-ZERO-LEAK-STD", Q10="Q10-COMPACT-CAPEX"), "MOD-PHE", "plate_hx"),
        ("P11", sensible_inputs("Q2-LIQ-LIQ", Q3="Q3-HIGH-P", Q4="Q4-ELEV-T", Q5="Q5-HEAVY", Q6="Q6-ZERO-LEAK-HAZ", Q10="Q10-ROBUST-CLEAN"), "MOD-STHE", "bell_delaware_shell_and_tube_hx"),
        ("P12", sensible_inputs("Q2-LIQ-LIQ", Q3="Q3-HIGH-P", Q4="Q4-ELEV-T", Q5="Q5-MODERATE", Q7="Q7-WIDE", Q9="Q9-MED-VISC"), "MOD-PHE", "plate_hx"),
        ("P13", sensible_inputs("Q2-LIQ-LIQ", Q3="Q3-HIGH-P", Q4="Q4-ELEV-T", Q5="Q5-CLEAN", Q7="Q7-MODERATE", Q9="Q9-LOW-VISC", Q10="Q10-COMPACT-CAPEX"), "MOD-PHE", "plate_hx"),
        ("P14", sensible_inputs("Q2-LIQ-LIQ", Q3="Q3-HIGH-P", Q4="Q4-ELEV-T", Q5="Q5-CLEAN", Q7="Q7-MODERATE", Q9="Q9-LOW-VISC", Q10="Q10-ROBUST-CLEAN"), "MOD-STHE", "bell_delaware_shell_and_tube_hx"),
    )


def phe_example_payload():
    """Documented MOD-PHE README example (sizing with supplied geometry)."""
    return {
        "routing": {
            "module": "MOD-PHE", "rule": "Rule 6.1", "subtype": "Gasketed-PHE",
            "Q1": "Q1-SENSIBLE", "Q2": "Q2-LIQ-LIQ", "Q3": "Q3-MED-P",
            "Q4": "Q4-MOD-T", "Q5": "Q5-CLEAN", "Q6": "Q6-ZERO-LEAK-STD",
            "Q7": "Q7-MODERATE", "Q9": "Q9-LOW-VISC", "Q10": "Q10-COMPACT-CAPEX",
            "P_max_bar": 6, "T_max_C": 95,
        },
        "process": {
            "hot": {
                "name": "water", "M": 10, "T_in": 95,
                "rho": 985.2, "cp": 4183, "k": 0.648, "mu": 0.000505,
                "dp_allow": 50000, "Rf": 0,
            },
            "cold": {
                "name": "water", "M": 5, "T_in": 15, "T_out": 90,
                "rho": 985.2, "cp": 4183, "k": 0.648, "mu": 0.000505,
                "dp_allow": 50000, "Rf": 0,
            },
            "plate": {
                "L": 1.0, "W": 0.25, "b": 0.005, "t": 0.0006, "k_w": 17,
                "beta": 30, "d_port": 0.1, "construction": "gasketed", "gasket": "EPDM",
            },
        },
    }


def phe_routing_answers():
    return {
        "Q1": "Q1-SENSIBLE", "Q2": "Q2-LIQ-LIQ", "Q3": "Q3-MED-P",
        "Q4": "Q4-MOD-T", "Q5": "Q5-CLEAN", "Q6": "Q6-ZERO-LEAK-STD",
        "Q7": "Q7-MODERATE", "Q9": "Q9-LOW-VISC", "Q10": "Q10-COMPACT-CAPEX",
    }


def workspace_tempdir():
    """Create test scratch space within the checkout, including on clean clones."""
    temp_root = Path(__file__).resolve().parents[1] / "tmp"
    temp_root.mkdir(exist_ok=True)
    return TemporaryDirectory(dir=temp_root)


class FailingModule:
    module_id = "condenser"
    display_name = "Failing [TEST MOCK]"

    def run(self, module_input):
        raise RuntimeError("example execution failure")


class IntegrationTests(unittest.TestCase):
    def test_registry_contains_six_groups_four_real_adapters_and_two_placeholders(self):
        registry = ModuleRegistry()
        register_modules(registry)
        modules = tuple(registry.all())
        self.assertEqual(len(modules), 6)
        self.assertEqual([module.module_id for module in modules], [item[0] for item in MODULES])
        by_id = {module.module_id: module for module in modules}
        self.assertIsInstance(by_id["plate_hx"], PlateHeatExchangerAdapter)
        self.assertIsInstance(by_id["regenerator"], RegeneratorAdapter)
        self.assertIsInstance(by_id["evaporator"], EvaporatorAdapter)
        self.assertIsInstance(by_id["condenser"], CondenserAdapter)
        self.assertEqual(sum(isinstance(module, PlaceholderModule) for module in modules), 2)
        self.assertTrue(all(
            "[PLACEHOLDER]" in module.display_name
            for module in modules if module.module_id not in {"plate_hx", "regenerator", "evaporator", "condenser"}
        ))

    def test_all_eight_documented_evaporator_cases_execute_real_solvers(self):
        adapter = EvaporatorAdapter()
        examples = Path(__file__).resolve().parents[1] / "modules" / "evaporator" / "examples"
        expected = {
            ("sizing", "kettle"): "PRELIMINARY SIZING COMPLETE",
            ("sizing", "falling_film"): "PRELIMINARY SIZING COMPLETE",
            ("sizing", "horizontal_thermosyphon"): "PRELIMINARY SIZING COMPLETE",
            ("sizing", "vertical_thermosyphon"): "PRELIMINARY SIZING COMPLETE",
            ("rating", "kettle"): "RATING COMPLETE",
            ("rating", "falling_film"): "RATING COMPLETE",
            ("rating", "horizontal_thermosyphon"): "RATING COMPLETE",
            ("rating", "vertical_thermosyphon"): "RATING COMPLETE",
        }
        for mode in ("sizing", "rating"):
            for case_file in sorted((examples / mode).glob("*.json")):
                with self.subTest(mode=mode, case=case_file.name):
                    payload = load_case(case_file)
                    result = adapter.run(ModuleInput(values={
                        "calculation_type": mode,
                        "equipment_key": payload["equipment_key"],
                        "evaporator_payload": payload,
                    }))
                    native = result.results["native_result"]
                    self.assertEqual(result.status, "success", result.errors)
                    self.assertEqual(native["outputs"]["Calculation status"], expected[(mode, payload["equipment_key"])])
                    self.assertTrue(native["outputs"])
                    self.assertEqual(result.warnings, tuple(native.get("warnings", ())))

    def test_evaporator_required_input_errors_and_native_warnings_are_preserved(self):
        base = Path(__file__).resolve().parents[1] / "modules" / "evaporator" / "examples"
        payload = load_case(base / "sizing" / "kettle_example_case.json")
        payload["inputs"]["mdot_feed"] = -1
        rejected = EvaporatorAdapter().run(ModuleInput(values={
            "calculation_type": "sizing", "equipment_key": "kettle", "evaporator_payload": payload,
        }))
        self.assertEqual(rejected.status, "failed")
        self.assertTrue(rejected.errors)
        self.assertEqual(rejected.errors, tuple(rejected.results["native_result"]["errors"]))

        missing = load_case(base / "sizing" / "kettle_example_case.json")
        del missing["inputs"]["mdot_feed"]
        missing_result = EvaporatorAdapter().run(ModuleInput(values={
            "calculation_type": "sizing", "equipment_key": "kettle", "evaporator_payload": missing,
        }))
        self.assertEqual(missing_result.status, "failed")
        self.assertIn("mdot_feed", missing_result.errors[0])

        rating = load_case(base / "rating" / "k_type_reboiler_rating_example.json")
        warned = EvaporatorAdapter().run(ModuleInput(values={
            "calculation_type": "rating", "equipment_key": "kettle", "evaporator_payload": rating,
        }))
        self.assertEqual(warned.status, "success")
        self.assertTrue(warned.warnings)
        self.assertEqual(warned.warnings, tuple(warned.results["native_result"]["warnings"]))

    def test_evaporator_rejects_case_selection_mismatches(self):
        examples = Path(__file__).resolve().parents[1] / "modules" / "evaporator" / "examples"
        payload = load_case(examples / "sizing" / "kettle_example_case.json")
        result = EvaporatorAdapter().run(ModuleInput(values={
            "calculation_type": "rating", "equipment_key": "falling_film", "evaporator_payload": payload,
        }))
        self.assertEqual(result.status, "failed")
        self.assertIn("does not match", result.errors[0])

    def test_evaporator_runs_from_elsewhere_without_creating_files(self):
        example = Path(__file__).resolve().parents[1] / "modules" / "evaporator" / "examples" / "rating" / "falling_film_rating_example.json"
        payload = load_case(example)
        with workspace_tempdir() as temp_dir:
            original_cwd = os.getcwd()
            try:
                os.chdir(temp_dir)
                result = EvaporatorAdapter().run(ModuleInput(values={
                    "calculation_type": "rating", "equipment_key": "falling_film", "evaporator_payload": payload,
                }))
                files = list(Path(temp_dir).iterdir())
            finally:
                os.chdir(original_cwd)
        self.assertEqual(result.status, "success", result.errors)
        self.assertEqual(files, [])

    def test_main_executes_a_real_evaporator_case_and_returns_to_menu(self):
        output = StringIO()
        user_entries = [
            "1", "Q1-EVAP", "Q3-LOW-P", "Q4-MOD-T", "Q5-CLEAN", "Q6-LEAK-OK", "Q9-LOW-VISC",
            "1", "1", "modules/evaporator/examples/sizing/kettle_example_case.json", "2",
        ]
        with patch("builtins.input", side_effect=user_entries):
            with redirect_stdout(output):
                main.main()
        text = output.getvalue()
        self.assertIn("Routing path: P02", text)
        self.assertIn("Selected module: Evaporator", text)
        self.assertIn('"calculation_type": "sizing"', text)
        self.assertIn('"Calculation status": "PRELIMINARY SIZING COMPLETE"', text)
        self.assertIn("Closing application.", text)

    def test_main_executes_rating_case_for_forced_film_route(self):
        output = StringIO()
        user_entries = [
            "1", "Q1-EVAP", "Q3-LOW-P", "Q4-MOD-T", "Q5-CLEAN", "Q6-LEAK-OK", "Q9-HIGH-VISC",
            "2", "1", "modules/evaporator/examples/rating/falling_film_rating_example.json", "2",
        ]
        with patch("builtins.input", side_effect=user_entries):
            with redirect_stdout(output):
                main.main()
        text = output.getvalue()
        self.assertIn("Selected module: Evaporator", text)
        self.assertIn("no Forced-circulation solver was supplied", text)
        self.assertIn('"calculation_type": "rating"', text)
        self.assertIn('"Rated duty kW": 256.056', text)
        self.assertIn("Closing application.", text)

    def test_pdf_canonical_paths_p01_to_p14(self):
        for path_id, inputs, solver_code, module_id in path_cases():
            with self.subTest(path=path_id):
                decision = select_module(inputs)
                self.assertEqual(decision.path_id, path_id)
                self.assertEqual(decision.solver_code, solver_code)
                self.assertEqual(decision.module_id, module_id)

    def test_fin_solver_codes_map_to_the_single_approved_group(self):
        for _, inputs, solver_code, _ in path_cases():
            if solver_code in ("MOD-PFHE", "MOD-TFHE"):
                self.assertEqual(select_module(inputs).module_id, "plate_fin_tube_hx")

    def test_questionnaire_only_asks_questions_visible_for_duty(self):
        inputs = iter(("Q1-COND", "Q3-LOW-P", "Q4-MOD-T", "Q5-CLEAN", "Q6-LEAK-OK"))
        prompts = []
        handler = TerminalInputHandler(input_fn=lambda prompt: (prompts.append(prompt), next(inputs))[1], output_fn=lambda _: None)
        answers = handler.collect()
        self.assertEqual(set(answers), {"Q1", "Q3", "Q4", "Q5", "Q6"})
        self.assertFalse(any("Q2" in prompt or "Q7" in prompt or "Q10" in prompt for prompt in prompts))

    def test_q3_and_q4_numeric_inputs_are_bucketed_by_pdf_boundaries(self):
        inputs = sensible_inputs(Q3=25.0, Q4=180.0, Q7="Q7-MODERATE", Q9="Q9-LOW-VISC")
        self.assertEqual(select_module(inputs).path_id, "P13")

    def test_overlapping_gas_routes_follow_pdf_step_order(self):
        inputs = sensible_inputs(
            "Q2-GAS-GAS",
            Q3="Q3-LOW-P",
            Q5="Q5-MODERATE",
            Q6="Q6-LEAK-OK",
        )
        self.assertEqual(select_module(inputs).path_id, "P03")

    def test_invalid_question_code_is_reprompted(self):
        entries = iter(("not-a-code", "Q1-COND", "Q3-LOW-P", "Q4-MOD-T", "Q5-CLEAN", "Q6-LEAK-OK"))
        messages = []
        handler = TerminalInputHandler(input_fn=lambda _: next(entries), output_fn=messages.append)
        answers = handler.collect()
        self.assertEqual(answers["Q1"], "Q1-COND")
        self.assertTrue(any("Invalid Q1 option" in message for message in messages))

    def test_main_routes_executes_condenser_and_returns_to_menu(self):
        output = StringIO()
        user_entries = [
            "1", "Q1-COND", "Q3-LOW-P", "Q4-MOD-T", "Q5-CLEAN", "Q6-LEAK-OK",
            "2", str(Path(__file__).resolve().parents[1] / "modules/condenser/examples/plate.json"), "2",
        ]
        with patch("builtins.input", side_effect=user_entries):
            with redirect_stdout(output):
                main.main()
        text = output.getvalue()
        self.assertIn("Routing path: P01", text)
        self.assertIn("Solver route: MOD-COND", text)
        self.assertIn("Selected module: Condenser", text)
        self.assertIn('"native_status": "ok_with_warnings"', text)
        self.assertIn("Heat Exchanger Routing", text)
        self.assertIn("Closing application.", text)

    def test_regenerator_adapter_executes_real_code_and_maps_printed_result(self):
        values = {
            "fluid_choice": "1",
            "mat_choice": "1",
            "matrix_choice": "1",
            "m_dot": "0.5",
            "T_hot_in": "700",
        }
        standalone_output = StringIO()
        with patch("builtins.input", side_effect=[values[key] for key in RegeneratorAdapter.INPUT_KEYS]):
            with redirect_stdout(standalone_output):
                fixed_bed_legacy.run_simple_regenerator()

        result = RegeneratorAdapter().run(ModuleInput(values=values))
        standalone_text = standalone_output.getvalue()
        marker = min(
            position for position in (
                standalone_text.find("[WARNING]"),
                standalone_text.find("RESULT:"),
            ) if position >= 0
        )
        expected_output = standalone_text[marker:].strip()

        self.assertEqual(result.status, "success")
        self.assertEqual(result.results["console_output"], expected_output)
        self.assertIn("RESULT: OPTIMUM DESIGN FOUND!", result.results["console_output"])
        self.assertIn("Optimal Diameter (D):", result.results["console_output"])

    def test_central_to_real_regenerator_end_to_end_and_back_to_menu(self):
        output = StringIO()
        user_entries = [
            "1",
            "Q1-SENSIBLE", "Q2-GAS-GAS", "Q3-LOW-P", "Q4-VHIGH-T", "Q5-CLEAN",
            "Q6-LEAK-OK", "Q7-MODERATE", "Q10-COMPACT-CAPEX",
            "1", "1", "1", "0.5", "700",
            "2",
        ]
        with patch("builtins.input", side_effect=user_entries):
            with redirect_stdout(output):
                main.main()
        text = output.getvalue()
        self.assertIn("Routing path: P03", text)
        self.assertIn("Selected module: Regenerator", text)
        self.assertIn('"console_output": "RESULT: OPTIMUM DESIGN FOUND!', text)
        self.assertIn("Optimal Diameter (D):", text)
        self.assertIn("Closing application.", text)

    def test_phe_payload_mapping_and_native_output_are_preserved(self):
        payload = phe_example_payload()
        central_answers = phe_routing_answers()
        native = {"status": "DESIGNED", "warnings": ["native warning"], "design": {"N": 91}}
        adapter = PlateHeatExchangerAdapter()

        with patch("modules.plate_hx.adapter.run_mod_phe", return_value=native) as run_solver:
            result = adapter.run(ModuleInput(values={
                "phe_payload": payload,
                "routing_answers": {**central_answers, "Q3": "Q3-LOW-P"},
                "selected_subtype": "Gasketed-Plate",
            }))

        passed_payload = run_solver.call_args.args[0]
        self.assertEqual(passed_payload["routing"]["module"], "MOD-PHE")
        self.assertEqual(passed_payload["routing"]["Q3"], "Q3-LOW-P")
        self.assertEqual(passed_payload["routing"]["subtype"], "Gasketed-PHE")
        self.assertEqual(passed_payload["routing"]["P_max_bar"], 6)
        self.assertEqual(passed_payload["process"], payload["process"])
        run_solver.assert_called_once_with(passed_payload, verbose=False, out_file=None)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.results["native_status"], "DESIGNED")
        self.assertEqual(result.results["native_result"], native)
        self.assertEqual(result.warnings, ("native warning",))

    def test_phe_numeric_envelopes_are_mapped_to_submitted_category_codes(self):
        adapter = PlateHeatExchangerAdapter()
        answers = {**phe_routing_answers(), "Q3": 6.0, "Q4": 95.0}
        native = {"status": "DESIGNED", "warnings": []}
        with patch("modules.plate_hx.adapter.run_mod_phe", return_value=native) as run_solver:
            adapter.run(ModuleInput(values={
                "phe_payload": phe_example_payload(),
                "routing_answers": answers,
                "selected_subtype": "Gasketed-Plate",
            }))
        passed_routing = run_solver.call_args.args[0]["routing"]
        self.assertEqual(passed_routing["Q3"], "Q3-MED-P")
        self.assertEqual(passed_routing["Q4"], "Q4-MOD-T")

    def test_phe_required_fields_are_reported_by_native_rejection(self):
        payload = phe_example_payload()
        del payload["process"]["hot"]["T_in"]
        result = PlateHeatExchangerAdapter().run(ModuleInput(values={
            "phe_payload": payload,
            "routing_answers": phe_routing_answers(),
        }))

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.results["native_status"], "REJECTED")
        self.assertIn("process.hot is missing ['T_in']", result.errors[0])
        self.assertEqual(result.results["native_result"]["reason"], result.errors[0])

    def test_phe_documented_example_runs_without_console_or_file_side_effects(self):
        adapter = PlateHeatExchangerAdapter()
        original_cwd = os.getcwd()
        output = StringIO()
        with workspace_tempdir() as temp_dir:
            try:
                os.chdir(temp_dir)
                with redirect_stdout(output):
                    result = adapter.run(ModuleInput(values={
                        "phe_payload": phe_example_payload(),
                        "routing_answers": phe_routing_answers(),
                    }))
                created_files = list(Path(temp_dir).iterdir())
            finally:
                os.chdir(original_cwd)

        self.assertEqual(output.getvalue(), "")
        self.assertEqual(created_files, [])
        self.assertEqual(result.status, "success")
        self.assertEqual(result.results["native_status"], "DESIGNED")
        self.assertIn("design", result.results["native_result"])
        self.assertTrue(result.results["native_result"]["design"])

    def test_main_executes_real_phe_from_documented_payload_path(self):
        output = StringIO()
        with workspace_tempdir() as temp_dir:
            payload_path = Path(temp_dir) / "phe_input.json"
            payload_path.write_text(json.dumps(phe_example_payload()), encoding="utf-8")
            user_entries = [
                "1", "Q1-SENSIBLE", "Q2-LIQ-LIQ", "Q3-MED-P", "Q4-MOD-T",
                "Q5-CLEAN", "Q6-ZERO-LEAK-STD", "Q7-MODERATE", "Q9-LOW-VISC",
                "Q10-COMPACT-CAPEX", str(payload_path), "2",
            ]
            with patch("builtins.input", side_effect=user_entries):
                with redirect_stdout(output):
                    main.main()

        text = output.getvalue()
        self.assertIn("Routing path: P13", text)
        self.assertIn("Selected module: Plate HX", text)
        self.assertIn('"native_status": "DESIGNED"', text)
        self.assertIn('"DESIGNED"', text)
        self.assertIn("Closing application.", text)

    def test_adapter_preserves_legacy_numeric_input_error(self):
        values = {
            "fluid_choice": "1",
            "mat_choice": "1",
            "matrix_choice": "1",
            "m_dot": "not-a-number",
            "T_hot_in": "700",
        }
        with patch("builtins.input", side_effect=[values[key] for key in RegeneratorAdapter.INPUT_KEYS]):
            with redirect_stdout(StringIO()):
                with self.assertRaises(ValueError) as direct_error:
                    fixed_bed_legacy.run_simple_regenerator()
        with self.assertRaises(ValueError) as adapter_error:
            RegeneratorAdapter().run(ModuleInput(values=values))
        self.assertEqual(str(adapter_error.exception), str(direct_error.exception))

    def test_adapter_restores_input_and_stdout_after_execution_error(self):
        values = {
            "fluid_choice": "1",
            "mat_choice": "1",
            "matrix_choice": "1",
            "m_dot": "not-a-number",
            "T_hot_in": "700",
        }
        original_input = builtins.input
        outer_stdout = StringIO()
        registry = ModuleRegistry()
        registry.register(RegeneratorAdapter())

        with redirect_stdout(outer_stdout):
            caller_stdout = sys.stdout
            result = registry.run("regenerator", ModuleInput(values=values))
            self.assertIs(sys.stdout, caller_stdout)

        self.assertIs(builtins.input, original_input)
        self.assertEqual(result.status, "failed")
        self.assertEqual(len(result.errors), 1)
        self.assertIn("could not convert string to float", result.errors[0])
        self.assertEqual(outer_stdout.getvalue(), "")

    def test_consecutive_adapter_runs_have_isolated_results(self):
        adapter = RegeneratorAdapter()
        air_inputs = {
            "fluid_choice": "1", "mat_choice": "1", "matrix_choice": "1",
            "m_dot": "0.5", "T_hot_in": "700",
        }
        water_inputs = {
            "fluid_choice": "2", "mat_choice": "2", "matrix_choice": "2",
            "m_dot": "0.5", "T_hot_in": "700",
        }

        original_input = builtins.input
        outer_stdout = StringIO()
        with redirect_stdout(outer_stdout):
            caller_stdout = sys.stdout
            first = adapter.run(ModuleInput(values=air_inputs))
            self.assertIs(sys.stdout, caller_stdout)
            second = adapter.run(ModuleInput(values=water_inputs))
            self.assertIs(sys.stdout, caller_stdout)
            third = adapter.run(ModuleInput(values=air_inputs))
            self.assertIs(sys.stdout, caller_stdout)

        self.assertIs(builtins.input, original_input)
        self.assertEqual(outer_stdout.getvalue(), "")
        first_output = first.results["console_output"]
        second_output = second.results["console_output"]
        third_output = third.results["console_output"]
        self.assertIn("Fluid: Air | Material: Cordierite", first_output)
        self.assertIn("[WARNING] Inlet temp 700.0°C exceeds Stainless Steel limit (600.0°C)!", second_output)
        self.assertNotIn("RESULT:", second_output)
        self.assertNotIn("Water", first_output)
        self.assertNotIn("Air", second_output)
        self.assertEqual(first_output, third_output)
        self.assertEqual(first.status, second.status)
        self.assertEqual(second.status, third.status)

    def test_invalid_main_menu_choice_is_handled(self):
        output = StringIO()
        with patch("builtins.input", side_effect=["9", "2"]):
            with redirect_stdout(output):
                main.main()
        self.assertIn("Invalid menu choice.", output.getvalue())
        self.assertIn("Closing application.", output.getvalue())

    def test_module_execution_failure_is_reported_and_menu_remains_available(self):
        registry = ModuleRegistry()
        registry.register(FailingModule())
        output = StringIO()
        user_entries = ["1", "Q1-COND", "Q3-LOW-P", "Q4-MOD-T", "Q5-CLEAN", "Q6-LEAK-OK",
                        "2", str(Path(__file__).resolve().parents[1] / "modules/condenser/examples/plate.json"), "2"]
        with patch("main.build_registry", return_value=registry):
            with patch("builtins.input", side_effect=user_entries):
                with redirect_stdout(output):
                    main.main()
        self.assertIn('"status": "failed"', output.getvalue())
        self.assertIn("example execution failure", output.getvalue())
        self.assertIn("Closing application.", output.getvalue())

    def test_duplicate_module_id_is_rejected(self):
        registry = ModuleRegistry()
        registry.register(PlaceholderModule("same", "First"))
        with self.assertRaises(ValueError):
            registry.register(PlaceholderModule("same", "Second"))


if __name__ == "__main__":
    unittest.main()
