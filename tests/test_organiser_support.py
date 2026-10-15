import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import organiser_support as o

class OrganiserTests(unittest.TestCase):
    def test_route_uses_supplied_road_distances_and_threshold(self):
        m = o.get_evidence('DISP-001', 'get_metrics')['data']['metrics']
        self.assertEqual(m['excess_distance_m'], 4300)
        self.assertEqual(m['excess_distance_fare_cents'], 344)
        self.assertEqual(m['fare_difference_cents'], 650)
        self.assertTrue(m['requires_route_threshold_review'])
    def test_route_arrays(self):
        t = o.get_evidence('DISP-001', 'get_trip')['data']['trip']
        self.assertEqual(len(t['actual_route']), 16)
        self.assertEqual(len(t['reference_route']), 10)
    def test_no_show_clocks_and_contacts(self):
        m = o.get_evidence('DISP-002', 'get_metrics')['data']['metrics']
        self.assertEqual(m['arrival_to_cancel_seconds'], 480)
        self.assertEqual(m['scheduled_to_cancel_seconds'], 360)
        self.assertEqual(m['pre_cancel_driver_message_count'], 4)
        self.assertEqual(m['pre_cancel_driver_call_attempt_count'], 1)
        self.assertEqual(m['rider_fraud_flags'], 1)
    def test_surge_amount(self):
        m = o.get_evidence('DISP-003', 'get_metrics')['data']['metrics']
        self.assertEqual(m['fare_difference_cents'], 450)
        self.assertEqual(m['surge_difference_cents'], 450)
        self.assertIs(m['surge_pricing_log']['rider_notified'], False)
    def test_no_answers_in_case_fixtures(self):
        for case in o.CASE_IDS:
            raw=o.load_case(case)
            self.assertFalse(set(raw) & {'case_metadata','recommended_ruling','evidence_summary','chat_log_analysis','traffic_analysis'})
    def test_every_tool_has_valid_ids(self):
        for case in o.CASE_IDS:
            for tool in o.TOOLS:
                result = o.get_evidence(case,tool)
                self.assertEqual(result['evidence_ids'], [f'{case}:{tool}'])
                json.dumps(result, allow_nan=False)
        ids = o.get_evidence('DISP-001','get_policy')['policy_ids']
        for clause in ['1.2','2.1','2.3','3.3','5.2','6.2','6.3','7.2']:
            self.assertIn('ORG-V2.1-'+clause,ids)
    def test_rejects_unknown_input(self):
        with self.assertRaises(ValueError): o.get_evidence('../secret','get_trip')
        with self.assertRaises(ValueError): o.get_evidence('DISP-001','execute_payment')

if __name__ == '__main__': unittest.main()
