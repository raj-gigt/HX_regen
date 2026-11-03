"""Exercise the native condenser service through the central integration."""

import copy
from dataclasses import asdict
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from core.contracts import ModuleInput
from core.input_handler import TerminalInputHandler
from modules.condenser.adapter import CondenserAdapter, EQUIPMENT_OPTIONS, load_case
from modules.condenser.condenser_app.service import get_module, run_design


EXAMPLES = Path(__file__).resolve().parents[1] / "modules/condenser/examples"


class CondenserTests(unittest.TestCase):
    def run_payload(self, payload):
        return CondenserAdapter().run(ModuleInput(values={"condenser_payload": payload}))

    def test_all_examples_preserve_native_service_results(self):
        for key, _ in EQUIPMENT_OPTIONS:
            with self.subTest(equipment=key):
                payload = load_case(EXAMPLES / f"{key}.json")
                result = self.run_payload(payload)
                expected = run_design(key, get_module(key).example_inputs())
                self.assertEqual(result.status, "success")
                self.assertEqual(result.results["native_result"], asdict(expected))
                self.assertEqual(result.results["effective_inputs"], payload["inputs"])
                self.assertEqual(result.results["native_status"], expected.status.value)
                for warning in expected.warnings:
                    self.assertIn(warning, result.warnings)
                for check in expected.checks:
                    if check.state.value == "fail":
                        self.assertTrue(any(check.name in warning for warning in result.warnings))
                json.dumps(result.results)  # Native enums remain JSON-serializable strings.

    def test_missing_required_input_preserves_native_validation(self):
        payload = load_case(EXAMPLES / "plate.json")
        payload["inputs"] = {}
        result = self.run_payload(payload)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.results["native_status"], "invalid_input")
        self.assertTrue(result.errors)
        self.assertTrue(result.results["native_result"]["input_issues"])

    def test_bad_shapes_types_and_unknown_fields_fail_cleanly(self):
        original = load_case(EXAMPLES / "plate.json")
        cases = [None, {}, {"equipment_key": "missing", "inputs": {}},
                 {"equipment_key": "plate", "inputs": []}]
        for value in ("mistyped-number", True, []):
            payload = copy.deepcopy(original)
            payload["inputs"]["geometry"]["L"] = value
            cases.append(payload)
        payload = copy.deepcopy(original)
        payload["inputs"]["typo"] = 10
        cases.append(payload)
        nested = next(name for name, value in original["inputs"].items() if isinstance(value, dict))
        payload = copy.deepcopy(original)
        payload["inputs"][nested] = 10
        cases.append(payload)
        for payload in cases:
            with self.subTest(payload=payload):
                result = self.run_payload(payload)
                self.assertEqual(result.status, "failed")
                self.assertTrue(result.errors)

    def test_nonconvergence_maps_to_failed_and_retains_trace(self):
        from modules.condenser.condenser_app.schemas import DesignResult, Status
        native = DesignResult(module="plate", title="Plate", status=Status.NOT_CONVERGED,
                              message="Iteration did not converge")
        with patch("modules.condenser.condenser_app.service.run_design", return_value=native):
            result = self.run_payload(load_case(EXAMPLES / "plate.json"))
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.results["native_status"], "not_converged")
        self.assertIn("Iteration did not converge", result.errors)

    def test_selection_mismatch_rejected(self):
        result = CondenserAdapter().run(ModuleInput(values={
            "condenser_payload": load_case(EXAMPLES / "plate.json"), "equipment_key": "air_cooled",
        }))
        self.assertEqual(result.status, "failed")
        self.assertIn("does not match", result.errors[0])

    def test_input_handler_reprompts_for_bad_file_and_mismatch(self):
        with TemporaryDirectory() as directory:
            bad = Path(directory) / "bad.json"
            bad.write_text("[]")
            entries = iter(["0", "2", str(bad), str(EXAMPLES / "selection.json"), str(EXAMPLES / "plate.json")])
            messages = []
            handler = TerminalInputHandler(input_fn=lambda _: next(entries), output_fn=messages.append)
            values = handler.collect_condenser_inputs()
            self.assertEqual(values["equipment_key"], "plate")
            self.assertTrue(any("does not match" in message for message in messages))
            self.assertTrue(any("must be an object" in message for message in messages))

    def test_runs_from_other_directory_without_files_or_mutation(self):
        payload = load_case(EXAMPLES / "plate.json")
        original = copy.deepcopy(payload)
        cwd = Path.cwd()
        try:
            with TemporaryDirectory() as directory:
                os.chdir(directory)
                result = self.run_payload(payload)
                self.assertEqual(result.status, "success")
                self.assertEqual(list(Path(directory).iterdir()), [])
        finally:
            os.chdir(cwd)
        self.assertEqual(payload, original)


if __name__ == "__main__":
    unittest.main()
