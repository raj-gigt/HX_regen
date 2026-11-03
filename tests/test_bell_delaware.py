import copy
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import main
from core.contracts import ModuleInput
from core.labels import expand
from modules.bell_delaware.adapter import BellDelawareAdapter, load_case, validate
from modules.bell_delaware import engine, properties
from modules.bell_delaware.streams import prepare_streams

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "modules/bell_delaware/examples"


class BellDelawareTests(unittest.TestCase):
    def payload(self):
        return load_case(EXAMPLES / "water_water_feasible.json")

    def run_case(self, payload):
        return BellDelawareAdapter().run(ModuleInput(values={"bell_delaware_payload": payload}))

    def test_native_results_preserved_and_json_serializable(self):
        payload = self.payload()
        original = copy.deepcopy(payload)
        inputs = payload["inputs"]
        h, c, _, _ = prepare_streams(inputs["hot"], inputs["cold"])
        expected = engine.design(h, c, validate(inputs))
        result = self.run_case(payload)
        self.assertEqual(result.status, "success")
        native = result.results["native_result"]
        for key in ("Nt", "Ds", "Uo", "dP_s", "dP_t", "margin", "iterations", "converged", "feasible"):
            self.assertEqual(native[key], expected[key])
        self.assertEqual(result.results["console_output"], engine.report(expected))
        self.assertEqual(payload, original)
        json.dumps(result.results, allow_nan=False)
        notebook = json.loads((ROOT / "modules/bell_delaware/Shell_and_Tube_Heat_Exchanger_Bell_Delaware_v3.ipynb").read_text())
        self.assertEqual((ROOT / "modules/bell_delaware/engine.py").read_text(), "".join(notebook["cells"][2]["source"]))

    def test_original_notebook_example_is_reported_infeasible(self):
        result = self.run_case(load_case(EXAMPLES / "water_water.json"))
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.results["native_status"], "infeasible")
        self.assertTrue(result.warnings)
        self.assertFalse(result.results["native_result"]["feasible"])

    def test_missing_outlets_use_explicit_effectiveness_and_custom_properties_are_isolated(self):
        payload = self.payload()
        for stream in ("hot", "cold"):
            payload["inputs"][stream]["T_out"] = None
        result = self.run_case(payload)
        self.assertEqual(result.results["effective_inputs"]["assumed_effectiveness_used"], 0.85)
        self.assertIsNotNone(result.results["effective_inputs"]["cold"]["T_out"])
        payload = self.payload()
        payload["inputs"]["hot"].update(fluid="custom", properties={"rho": 980, "cp": 4185, "k": 0.66, "mu": 0.0005})
        before = dict(properties.CUSTOM_FLUIDS)
        result = self.run_case(payload)
        self.assertTrue(result.results)
        self.assertEqual(properties.CUSTOM_FLUIDS, before)
        self.assertEqual(result.results["effective_inputs"]["hot"]["cp"], 4185)

    def test_bad_inputs_and_nonconvergence_are_not_success(self):
        for path, value in (("L", 0), ("max_iter", 0), ("layout", 20), ("Uo_assumed", "oops"),
                            ("Bc", 1), ("passes", True), ("delta_tb", -1), ("n_shells", -1), ("wall_iterations", 0)):
            with self.subTest(field=path):
                payload = self.payload()
                payload["inputs"]["config"][path] = value
                result = self.run_case(payload)
                self.assertEqual(result.status, "failed")
                self.assertTrue(result.errors)
        payload = self.payload()
        payload["inputs"]["hot"]["m"] = -1
        self.assertEqual(self.run_case(payload).status, "failed")
        payload = self.payload()
        payload["inputs"]["config"].update(max_iter=1, Uo_assumed=5000)
        self.assertEqual(self.run_case(payload).status, "failed")

    def test_cli_routes_and_executes_bell_delaware(self):
        entries = ["1", "Q1-SENSIBLE", "Q2-LIQ-LIQ", "Q3-LOW-P", "Q4-MOD-T", "Q5-MODERATE",
                   "Q6-LEAK-OK", "Q7-WIDE", "Q9-LOW-VISC", "Q10-ROBUST-CLEAN",
                   str(EXAMPLES / "water_water_feasible.json"), "2"]
        output = StringIO()
        with patch("builtins.input", side_effect=entries), redirect_stdout(output):
            main.main()
        self.assertIn('"native_status": "designed"', output.getvalue())
        self.assertIn("MOD-STHE (Shell and Tube Heat Exchanger Module)", output.getvalue())
        self.assertIn("Closing application.", output.getvalue())

    def test_abbreviation_labels_are_expanded_and_stable(self):
        label = "PHE HX LMTD NTU Re Pr Nu OD ID TEMA JSON CSV"
        expanded = expand(label)
        self.assertIn("HX (Heat Exchanger)", expanded)
        self.assertIn("LMTD (Logarithmic Mean Temperature Difference)", expanded)
        self.assertEqual(expand(expanded), expanded)
