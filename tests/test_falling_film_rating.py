"""Verify the supplied falling-film engine through the adapter and shared UI."""

import copy
import json
from pathlib import Path
import unittest

from streamlit.testing.v1 import AppTest

from core.contracts import ModuleInput
from modules.evaporator.adapter import EvaporatorAdapter, _load_solver
from ui.inputs import ROOT


class FallingFilmRatingTests(unittest.TestCase):
    def setUp(self):
        self.case = json.loads((ROOT / 'examples/evaporator/rating/falling_film.json').read_text())

    def run_case(self, case):
        return EvaporatorAdapter().run(ModuleInput(values={
            'calculation_type': 'rating', 'equipment_key': 'falling_film',
            'evaporator_payload': case,
        }))

    def test_adapter_preserves_native_rating_and_applicability_limits(self):
        solver = _load_solver('rating', 'falling_film')
        self.assertEqual(ROOT / 'modules/evaporator/rating/falling_film_rating.py', Path(solver.__file__))
        native = solver._compute_rating(copy.deepcopy(self.case['inputs']))
        result = self.run_case(self.case)
        self.assertEqual(result.status, 'success', result.errors)
        self.assertEqual(result.results['native_result'], native)
        outputs = native['outputs']
        self.assertAlmostEqual(outputs['Rated duty kW'], 256.056, places=3)
        self.assertEqual(outputs['Calculation status'], 'RATING COMPLETE')
        self.assertIn('NOT CALCULATED', outputs['Two-phase process pressure drop'])
        self.assertTrue(native['checks'])
        self.assertTrue(native['source_register'])
        self.assertEqual(result.warnings, tuple(native['warnings']))
        lower_service = copy.deepcopy(self.case)
        lower_service['inputs']['service_mdot'] *= 0.5
        smaller = self.run_case(lower_service).results['native_result']['outputs']
        self.assertLess(smaller['Rated duty kW'], outputs['Rated duty kW'])
        wetting = copy.deepcopy(self.case)
        wetting['inputs']['min_wetting_rate'] = 100.0
        self.assertEqual(self.run_case(wetting).results['native_result']['outputs']['Minimum wetting check'], 'FAIL')

    def test_invalid_process_flow_returns_native_errors(self):
        self.case['inputs']['mdot_feed'] = -1.0
        result = self.run_case(self.case)
        self.assertEqual(result.status, 'failed')
        self.assertEqual(result.errors, tuple(result.results['native_result']['errors']))
        self.assertTrue(any('Process flow' in error for error in result.errors))

    def test_evaporator_configuration_manual_and_edited_json_rating(self):
        app = AppTest.from_file(str(ROOT / 'streamlit_app.py'), default_timeout=60).run()
        self.assertNotIn('Falling-film evaporator rating', app.selectbox(key='scenario').options)
        app.selectbox(key='scenario').select('Evaporator').run()
        next(item for item in app.button if item.label == 'Use workflow').click().run()
        self.assertFalse(app.exception)
        app.radio(key='evap_mode').set_value('rating').run()
        configuration = next(item for item in app.selectbox if item.label == 'Evaporator configuration')
        self.assertIn('Falling-film evaporator rating', configuration.options)
        configuration.select('falling_film').run()
        self.assertEqual(app.selectbox(key='scenario').value, 'Evaporator')
        self.assertEqual(app.radio(key='evap_mode').value, 'rating')
        self.assertEqual(next(item for item in app.selectbox if item.label == 'Evaporator configuration').value, 'falling_film')
        next(item for item in app.button if item.label == 'Calculate').click().run()
        self.assertEqual(app.session_state['calculation']['output']['status'], 'success')
        next(item for item in app.radio if item.label == 'Starting values').set_value('JSON files').run()
        picker = next(item for item in app.selectbox if str(item.key).startswith('json_case_picker:'))
        self.assertEqual(picker.value, 'bundled:evaporator/rating/falling_film.json')
        field = next(item for item in app.number_input if item.key.startswith('json_editor:') and item.key.endswith(':service_mdot'))
        field.set_value(0.06).run()
        next(item for item in app.button if item.label == 'Calculate').click().run()
        self.assertFalse(app.exception)
        record = app.session_state['calculation']
        self.assertEqual(record['output']['results']['equipment_key'], 'falling_film')
        self.assertAlmostEqual(record['output']['results']['native_result']['outputs']['Rated duty kW'], 128.028, places=3)
        self.assertEqual(record['inputs']['evaporator_payload']['inputs']['service_mdot'], 0.06)
        next(item for item in app.button if str(item.key).startswith('reload_json:')).click().run()
        self.assertEqual(next(item for item in app.number_input if item.key.startswith('json_editor:') and item.key.endswith(':service_mdot')).value, 0.12)
        self.assertFalse(app.exception)


if __name__ == '__main__':
    unittest.main()
