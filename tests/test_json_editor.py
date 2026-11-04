"""Exercise bundled/uploaded case selection, live edits, and original-value reload."""

import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from ui.inputs import ROOT
from ui.json_cases import discover_cases, register_upload, validate_case


class Upload:
    def __init__(self, name, payload):
        self.name = name
        self.raw = json.dumps(payload).encode()

    def getvalue(self):
        return self.raw


def click(app, label):
    next(item for item in app.button if item.label == label).click().run()


def use_workflow(app, name):
    app.selectbox(key="scenario").select(name).run()
    click(app, "Use workflow")


def json_mode(app):
    next(item for item in app.radio if item.label == "Starting values").set_value("JSON files").run()


def picker(app):
    return next(item for item in app.selectbox if str(item.key).startswith("json_case_picker:"))


def parameter(app, suffix):
    return next(item for item in app.number_input if item.key.startswith("json_editor:") and item.key.endswith(":" + suffix))


class JsonEditorTests(unittest.TestCase):
    def start(self):
        app = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=60).run()
        self.assertFalse(app.exception)
        return app

    def test_bundled_case_edits_reach_solver_and_reload_restores_original(self):
        path = ROOT / "examples/plate_hx/water_sizing.json"
        original = path.read_bytes()
        app = self.start()
        json_mode(app)
        self.assertFalse(app.exception)
        self.assertEqual(picker(app).value, "bundled:plate_hx/water_sizing.json")
        self.assertTrue(app.sidebar.subheader)
        parameter(app, "hot.M").set_value(12.0).run()
        click(app, "Calculate")
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["calculation"]["inputs"]["phe_payload"]["process"]["hot"]["M"], 12.0)
        self.assertEqual(app.session_state["calculation"]["output"]["results"]["native_status"], "DESIGNED")
        parameter(app, "hot.M").set_value(11.0).run()
        self.assertFalse(app.metric)
        self.assertTrue(any("Calculate again" in item.value for item in app.info))
        reload_button = next(item for item in app.button if str(item.key).startswith("reload_json:"))
        reload_button.click().run()
        self.assertFalse(app.exception)
        self.assertEqual(parameter(app, "hot.M").value, 10.0)
        self.assertEqual(path.read_bytes(), original)

    def test_multiple_uploads_are_selectable_editable_and_reloadable(self):
        base = json.loads((ROOT / "examples/plate_hx/water_sizing.json").read_text())
        first, second = copy.deepcopy(base), copy.deepcopy(base)
        first["process"]["hot"]["M"] = 13.0
        second["process"]["hot"]["M"] = 14.0
        uploads = [Upload("my_first_case.json", first), Upload("my_second_case.json", second)]
        app = self.start()
        with patch("streamlit.file_uploader", return_value=uploads):
            json_mode(app)
            self.assertFalse(app.exception)
            self.assertEqual(len(app.session_state["json_upload_library"]), 2)
            self.assertEqual(parameter(app, "hot.M").value, 14.0)
            selected_second = picker(app).value
            first_id = next(key for key, case in app.session_state["json_upload_library"].items() if case["filename"] == "my_first_case.json")
            picker(app).select(first_id).run()
            parameter(app, "hot.M").set_value(15.0).run()
            picker(app).select(selected_second).run()
            picker(app).select(first_id).run()
            self.assertEqual(parameter(app, "hot.M").value, 15.0)
            click(app, "Calculate")
            self.assertEqual(app.session_state["calculation"]["inputs"]["phe_payload"]["process"]["hot"]["M"], 15.0)
            next(item for item in app.button if str(item.key).startswith("reload_json:")).click().run()
            self.assertEqual(parameter(app, "hot.M").value, 13.0)
            self.assertEqual(json.loads(app.session_state["json_upload_library"][first_id]["raw"])["process"]["hot"]["M"], 13.0)
        # Removing files from the uploader does not remove the session's case library.
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.session_state["json_upload_library"]), 2)

    def test_raw_json_errors_block_calculation_and_valid_edits_apply(self):
        app = self.start()
        json_mode(app)
        next(item for item in app.radio if item.label == "Edit as").set_value("JSON text").run()
        area = app.text_area[0]
        payload = json.loads(area.value)
        payload["process"]["hot"]["M"] = 12.5
        area.set_value(json.dumps(payload)).run()
        click(app, "Calculate")
        self.assertEqual(app.session_state["calculation"]["inputs"]["phe_payload"]["process"]["hot"]["M"], 12.5)
        next(item for item in app.radio if item.label == "Edit as").set_value("Parameters").run()
        self.assertEqual(parameter(app, "hot.M").value, 12.5)
        next(item for item in app.radio if item.label == "Edit as").set_value("JSON text").run()
        app.text_area[0].set_value("{").run()
        self.assertFalse(app.exception)
        self.assertTrue(next(item for item in app.button if item.label == "Calculate").disabled)
        self.assertFalse(app.metric)
        next(item for item in app.button if str(item.key).startswith("reload_json:")).click().run()
        self.assertEqual(json.loads(app.text_area[0].value)["process"]["hot"]["M"], 10.0)

    def test_json_cases_calculate_for_every_integrated_group(self):
        app = self.start()
        for name in ("Condenser", "Evaporator", "Shell and tube (Bell–Delaware)", "Rotary regenerator", "Fixed-bed regenerator"):
            with self.subTest(workflow=name):
                use_workflow(app, name)
                json_mode(app)
                self.assertFalse(app.exception)
                click(app, "Calculate")
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state["calculation"]["output"]["status"], "success")

    def test_case_discovery_filters_modes_and_notices_new_files(self):
        self.assertEqual([case["filename"] for case in discover_cases("plate_hx", mode="rating")], ["water_rating.json"])
        self.assertEqual([case["filename"] for case in discover_cases("condenser", "air_cooled")], ["air_cooled.json"])
        self.assertEqual([case["filename"] for case in discover_cases("regenerator", subtype="Rotary-Ljungstrom")], ["rotary.json"])
        payload = json.loads((ROOT / "examples/plate_hx/water_sizing.json").read_text())
        with TemporaryDirectory() as folder:
            path = Path(folder) / "future_case.json"
            path.write_text(json.dumps(payload))
            self.assertEqual(len(discover_cases("plate_hx", root=folder)), 1)
            payload["process"]["hot"]["M"] = 16
            path.write_text(json.dumps(payload))
            self.assertEqual(discover_cases("plate_hx", root=folder)[0]["payload"]["process"]["hot"]["M"], 16)
        with self.assertRaises(ValueError):
            register_upload({}, "bad.json", b"[]")
        with self.assertRaises(ValueError):
            validate_case(payload, "condenser", "air_cooled")
        library = {}
        first, _ = register_upload(library, "case.json", json.dumps(payload).encode())
        payload["process"]["hot"]["M"] += 1
        second, _ = register_upload(library, "case.json", json.dumps(payload).encode())
        self.assertNotEqual(library[first]["label"], library[second]["label"])

    def test_full_library_switches_calculator_configuration_and_mode(self):
        app = self.start()
        json_mode(app)
        cases = discover_cases()
        self.assertEqual(len(cases), 20)
        self.assertEqual(len(picker(app).options), 20)
        for case in cases:
            with self.subTest(case=case["id"]):
                picker(app).select(case["id"]).run()
                self.assertFalse(app.exception)
                self.assertEqual(picker(app).value, case["id"])
                click(app, "Calculate")
                self.assertFalse(app.exception)
                record = app.session_state["calculation"]
                self.assertEqual(record["inputs"].get("phe_payload", record["case"]).get("case_name"), case["payload"].get("case_name"))
                self.assertEqual(record["output"]["status"], "failed" if "infeasible" in case["filename"] else "success")

    def test_clearing_rating_plate_count_does_not_switch_to_sizing(self):
        app = self.start()
        app.radio(key="phe_mode").set_value("rating").run()
        json_mode(app)
        parameter(app, "plate.N").set_value(None).run()
        self.assertFalse(app.exception)
        self.assertTrue(next(item for item in app.button if item.label == "Calculate").disabled)
        self.assertFalse(app.metric)


if __name__ == "__main__":
    unittest.main()
