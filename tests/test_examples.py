"""Verify the user-facing examples against routing and real native solver results."""

import json
import unittest

from main import build_registry
from run_examples import EXAMPLES, load_manifest, run_case


class ExampleTests(unittest.TestCase):
    def test_every_published_case_returns_its_expected_native_result(self):
        registry = build_registry()
        cases = load_manifest()
        self.assertEqual(len({case["file"] for case in cases}), len(cases))
        for case in cases:
            with self.subTest(file=case["file"]):
                summary, result = run_case(case, registry)
                self.assertTrue(summary["passed"], summary)
                if case["case_type"] == "routing_only":
                    self.assertIsNone(result)
                else:
                    self.assertIsNotNone(result)
                    self.assertNotIn("placeholder", result["results"])
                    json.dumps(result, default=str, allow_nan=False)

    def test_manifest_covers_all_modules_and_all_input_json_files(self):
        cases = load_manifest()
        registry = build_registry()
        self.assertEqual({case["module_id"] for case in cases}, {module.module_id for module in registry.all()})
        files = {path.relative_to(EXAMPLES).as_posix() for path in EXAMPLES.rglob("*.json")}
        self.assertEqual(files - {"manifest.json", "test_report.json"}, {case["file"] for case in cases})
