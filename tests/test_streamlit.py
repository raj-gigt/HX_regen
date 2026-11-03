"""Run real UI interactions and calculations with Streamlit's headless browser model."""

import json
from pathlib import Path
import unittest

from streamlit.testing.v1 import AppTest

from ui.inputs import build_payload, parse_upload

APP = Path(__file__).resolve().parents[1] / "streamlit_app.py"


def button(app, label):
    return next(item for item in app.button if item.label == label)


def workflow(app, name):
    app.selectbox(key="scenario").select(name).run()
    button(app, "Use workflow").click().run()
    return app


class StreamlitTests(unittest.TestCase):
    def start(self):
        app = AppTest.from_file(str(APP), default_timeout=60).run()
        self.assertFalse(app.exception)
        return app

    def calculate(self, app):
        button(app, "Calculate").click().run()
        self.assertFalse(app.exception)
        return app.session_state["calculation"]["output"]

    def test_phe_sizing_rating_and_missing_plate_count(self):
        app = self.start()
        result = self.calculate(app)
        self.assertEqual(result["results"]["native_status"], "DESIGNED")
        self.assertTrue(app.metric)
        self.assertEqual(app.session_state["calculation"]["case"]["routing"]["module"], "MOD-PHE")
        app.radio(key="phe_mode").set_value("rating").run()
        result = self.calculate(app)
        self.assertEqual(result["results"]["native_result"]["mode"], "rating")
        count = next(item for item in app.number_input if item.key.endswith(":plate.N"))
        count.set_value(None)
        button(app, "Calculate").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any("existing plate count" in item.value for item in app.error))

    def test_all_condenser_configurations_calculate_and_preserve_blanks(self):
        app = workflow(self.start(), "Condenser")
        for equipment in ("vertical_shell_tube", "air_cooled", "direct_contact", "plate", "selection"):
            with self.subTest(equipment=equipment):
                app.selectbox(key="condenser_equipment").select(equipment).run()
                result = self.calculate(app)
                self.assertEqual(result["status"], "success")
                self.assertEqual(result["results"]["equipment_key"], equipment)
                self.assertTrue(result["results"]["native_result"]["outputs"])
                if equipment == "air_cooled":
                    self.assertIsNone(result["results"]["effective_inputs"]["stream"]["pressure"])
                    self.assertIsNone(app.session_state["calculation"]["case"]["inputs"]["stream"]["pressure"])

    def test_condenser_invalid_input_shows_field_issue(self):
        app = workflow(self.start(), "Condenser")
        flow = next(item for item in app.number_input if item.key.endswith(":vapour.m_dot"))
        flow.set_value(-1.0)
        result = self.calculate(app)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["results"]["native_status"], "invalid_input")
        self.assertTrue(any("mass flow" in item.value.lower() for item in app.error))

    def test_evaporator_sizing_and_rating(self):
        app = workflow(self.start(), "Evaporator")
        for mode in ("sizing", "rating"):
            app.radio(key="evap_mode").set_value(mode).run()
            for equipment in ("kettle", "horizontal_thermosyphon", "vertical_thermosyphon"):
                with self.subTest(mode=mode, equipment=equipment):
                    next(item for item in app.selectbox if item.label == "Evaporator configuration").select(equipment).run()
                    result = self.calculate(app)
                    self.assertEqual(result["status"], "success")
                    self.assertEqual(result["results"]["calculation_type"], mode)
        app.selectbox(key="route_Q9").select("Q9-HIGH-VISC").run()
        for mode in ("sizing", "rating"):
            app.radio(key="evap_mode").set_value(mode).run()
            result = self.calculate(app)
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["results"]["equipment_key"], "falling_film")

    def test_regenerator_branches(self):
        app = self.start()
        for name in ("Rotary regenerator", "Fixed-bed regenerator"):
            with self.subTest(workflow=name):
                workflow(app, name)
                result = self.calculate(app)
                self.assertEqual(result["status"], "success")
                self.assertTrue(result["results"].get("console_output"))

    def test_route_changes_hide_old_results_and_placeholders_do_not_run(self):
        app = self.start()
        self.calculate(app)
        app.selectbox(key="route_Q6").select("Q6-LEAK-OK").run()
        self.assertFalse(app.metric)
        self.assertTrue(any("Calculate again" in item.value for item in app.info))
        app.selectbox(key="route_Q2").select("Q2-GAS-LIQ").run()
        app.selectbox(key="route_Q3").select("Q3-LOW-P").run()
        self.assertFalse(app.exception)
        self.assertFalse(any(item.label == "Calculate" for item in app.button))
        self.assertTrue(any("not been integrated" in item.value for item in app.warning))

    def test_conditional_questionnaire(self):
        app = workflow(self.start(), "Condenser")
        keys = [item.key for item in app.selectbox]
        self.assertNotIn("route_Q2", keys)
        self.assertNotIn("route_Q7", keys)
        self.assertNotIn("route_Q10", keys)
        workflow(app, "Plate heat exchanger")
        self.assertIn("route_Q2", [item.key for item in app.selectbox])

    def test_bell_delaware_ui_and_expanded_labels(self):
        app = workflow(self.start(), "Shell and tube (Bell–Delaware)")
        self.assertTrue(any("Uo (Overall Heat-transfer Coefficient" in item.label for item in app.number_input))
        result = self.calculate(app)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["results"]["native_status"], "designed")
        self.assertTrue(app.metric)
        self.assertTrue(any("MOD-STHE (Shell and Tube Heat Exchanger Module)" in item.value for item in app.caption))

    def test_upload_validation_and_optional_phe_values(self):
        for raw in ("[]", "{", '{"inputs": []}'):
            with self.assertRaises(ValueError):
                parse_upload(raw, "condenser", "plate")
        with self.assertRaises(ValueError):
            parse_upload(json.dumps({"equipment_key": "plate", "inputs": {}}), "condenser", "air_cooled")
        with self.assertRaises(ValueError):
            parse_upload('{"process": {"plate": null}}', "plate_hx")
        payload = build_payload({"process": {"hot": {"M": 10}, "plate": {"N": 91}}},
                                {"hot.M": None, "plate.N": None}, "plate_hx")
        self.assertNotIn("M", payload["process"]["hot"])
        self.assertNotIn("N", payload["process"]["plate"])


if __name__ == "__main__":
    unittest.main()
