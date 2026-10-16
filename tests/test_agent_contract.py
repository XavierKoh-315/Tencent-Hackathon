"""Replays supplied model outputs locally. No paid ADP calls."""
import copy
import json
import unittest
from pathlib import Path

from disputes.adp import ADPClient, ADPError, review_text
from disputes.core import load_cases, resolve
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


class ReplyClient:
    def __init__(self, reply): self.reply = reply
    def review(self, *args, **kwargs):
        return copy.deepcopy(self.reply), [], {}


class AgentContractTests(unittest.TestCase):
    def fixture(self, name):
        return json.loads((ROOT / 'tests' / 'fixtures' / name).read_text())

    def resolve(self, cid, reply):
        case = next(c for c in load_cases() if c['trip_id'] == cid)
        return resolve(case, mode='multi_agent', client=ReplyClient(reply))

    def test_actual_ns02_contradiction_is_preserved_and_not_awarded(self):
        original = self.fixture('ns02_inconsistent.json')
        result = self.resolve('NS02', original)
        self.assertEqual(result['ruling']['ruling'], 'human_review')
        self.assertEqual(result['ruling']['refund_cents'], 0)
        self.assertEqual(result['original_ai_ruling'], original)
        self.assertEqual(result['validation']['status'], 'policy_mismatch')
        self.assertEqual(result['validation']['policy_baseline']['ruling'], 'no_action')
        self.assertEqual(result['validation']['original_model_confidence'], .95)

    def test_actual_rt01_missing_reports_keeps_specific_reason_and_zero_confidence(self):
        original = self.fixture('rt01_missing_reports.json')
        result = self.resolve('RT01', original)
        self.assertEqual(result['ruling']['rationale'], original['rationale'])
        self.assertEqual(result['ruling']['rider_message'], original['rider_message'])
        self.assertEqual(result['ruling']['confidence'], 0)
        self.assertEqual(result['validation']['status'], 'model_requested_review')
        self.assertEqual(result['validation']['policy_baseline']['refund_cents'], 369)
        self.assertEqual(result['original_ai_ruling'], original)

    def test_consistent_ns02_no_action_is_accepted(self):
        reply = self.fixture('ns02_inconsistent.json')
        reply.update(ruling='no_action', refund_cents=0,
                     rationale='Verified pickup presence and waiting time satisfy the supplied demo policy. Retain the fee.')
        result = self.resolve('NS02', reply)
        self.assertEqual(result['ruling']['ruling'], 'no_action')
        self.assertEqual(result['validation']['status'], 'accepted')

    def test_consistent_rt01_refund_is_accepted_without_forcing_missing_reports(self):
        reply = self.fixture('rt01_missing_reports.json')
        reply.update(ruling='refund', refund_cents=369, confidence=.9,
                     rationale='Both actual advocate reports support the documented route comparison and demo-policy calculation.',
                     rider_message='Proposed partial refund: SGD 3.69.',
                     driver_message='Proposed refund is limited to the supported excess-distance fare.')
        result = self.resolve('RT01', reply)
        self.assertEqual(result['ruling']['ruling'], 'refund')
        self.assertEqual(result['ruling']['refund_cents'], 369)
        self.assertEqual(result['validation']['status'], 'accepted')

    def test_labelled_advocate_cannot_end_as_judge_even_with_judge_shaped_json(self):
        reply = json.dumps(self.fixture('rt01_missing_reports.json'))
        for role in ('Rider Advocate', 'Driver Advocate'):
            events = [{'Type':'message.done', 'Message':{'MessageId':'a','Type':'reply',
                       'ExtraInfo':{'AgentName':role}, 'Contents':[{'Type':'text','Text':reply}]}},
                      {'Type':'response.completed','Response':{'Status':'success'}}]
            with self.subTest(role=role), self.assertRaises(ADPError) as ctx:
                review_text(events)
            self.assertEqual(ctx.exception.final_reply_agent, role)
            self.assertEqual(ctx.exception.final_reply_text, reply)

    def test_request_contains_handoff_and_consistency_contract_without_expected_answer(self):
        client = ADPClient({'ADP_APP_KEY':'test-only'})
        captured = {}
        reply = json.dumps(self.fixture('rt01_missing_reports.json'))
        def post(body):
            captured.update(body)
            return [{'Type':'response.completed','Response':{'Status':'success','Messages':[
                {'MessageId':'j','Type':'reply','ExtraInfo':{'AgentName':'Judge'},
                 'Contents':[{'Type':'text','Text':reply}]}]}}]
        client._post = post
        client.review('RT01', 'Unapproved detour.', 'test-conv', ['RT01:get_trip'], ['DEMO-ROUTE-01'])
        payload = json.loads(captured['Contents'][0]['Text'])
        self.assertIn('actual completed public report', payload['output_instruction'])
        self.assertIn('same resolution', payload['output_instruction'])
        self.assertIn('get_history is optional', payload['output_instruction'])
        self.assertNotIn('369', payload['output_instruction'])
        self.assertNotIn('SystemRole', captured)

    def test_rt01_screen_shows_missing_reports_instead_of_generic_mismatch(self):
        result = self.resolve('RT01', self.fixture('rt01_missing_reports.json'))
        at = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=15)
        at.session_state['selected_case'] = 'RT01'
        at.session_state['result'] = result
        # Read storage independently of the deployment environment.
        from unittest.mock import patch
        with patch('human_review_store.get_review_for_run', return_value=None):
            at.run()
        self.assertFalse(at.exception, str(at.exception))
        card = next(m.value for m in at.markdown if 'Resolution recommendation' in m.value)
        self.assertIn('Both advocate reports are missing', card)
        self.assertNotIn('protective mismatch', card)
        self.assertIn('0%', card)
        html_blocks = [e.proto.body for e in at.get('html')]
        self.assertTrue(any('Both advocate reports are missing' in b for b in html_blocks))


if __name__ == '__main__': unittest.main()
