"""Validation, audit and concurrency checks for the review workflow."""
import copy
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import human_review_store as store
from disputes.core import load_cases, resolve, _validate_multi_agent_ruling, OutputError


class ReviewRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root_patch = patch.object(store, "ROOT", Path(self.tmp.name))
        self.env_patch = patch.dict("os.environ", {"DATABASE_URL":"", "RENDER":"", "RENDER_SERVICE_ID":""})
        self.root_patch.start(); self.env_patch.start()
        case = next(c for c in load_cases() if c["trip_id"] == "NS04")
        self.ai = resolve(case, mode="offline")
        self.kw = dict(case_id="NS04", run_id=self.ai["run_id"], ai_result=self.ai,
                       original_confidence=None, escalation_reason="Missing GPS",
                       reviewer_id="demo", human_decision="no_action", refund_amount_str=None,
                       rider_message="Proposed resolution", driver_message="Proposed resolution",
                       final_explanation="Reviewed the supplied evidence.", policy_version=self.ai["policy_version"])

    def tearDown(self):
        self.root_patch.stop(); self.env_patch.stop(); self.tmp.cleanup()

    def test_nonfinite_and_scientific_refund_inputs_rejected(self):
        for amount in ("NaN", "Infinity", "-Infinity", "1e2", "1.001", "-1", "0", "1"*200):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                store._to_cents(amount)

    def test_actual_evidence_charge_caps_refund_including_zero(self):
        self.assertEqual(store.charged_cents_for(self.ai), 500)
        with self.assertRaises(ValueError):
            store.save_review(**{**self.kw, "human_decision":"refund", "refund_amount_str":"5.01"})
        result = copy.deepcopy(self.ai)
        next(e for e in result["evidence"] if e["tool"] == "get_payment")["data"]["charged_cents"] = 0
        result["charged_cents"] = 99999  # A stale duplicate must not override the evidence.
        self.assertEqual(store.charged_cents_for(result), 0)
        with self.assertRaises(ValueError):
            store.save_review(**{**self.kw, "ai_result":result, "human_decision":"refund", "refund_amount_str":"0.01"})

    def test_unknown_charge_never_becomes_zero(self):
        ai = copy.deepcopy(self.ai)
        next(e for e in ai["evidence"] if e["tool"] == "get_payment")["data"]["charged_cents"] = None
        self.assertIsNone(store.charged_cents_for(ai))
        with self.assertRaises(ValueError):
            store.save_review(**{**self.kw, "ai_result":ai, "human_decision":"refund", "refund_amount_str":"1.00"})

    def test_duplicate_unchanged_token_returns_original_record(self):
        kw = {**self.kw, "submission_id":str(uuid.uuid4())}
        first = store.save_review(**kw)
        self.assertEqual(store.save_review(**kw), first)
        with self.assertRaises(ValueError):
            store.save_review(**{**kw, "final_explanation":"Changed after saving"})
        self.assertEqual(len(store.get_review_history("NS04")), 1)

    def test_simultaneous_submissions_only_create_one_review(self):
        # Initialise schema before releasing simultaneous writers.
        store.get_review_for_run("NS04", self.ai["run_id"])
        def save(_):
            try:
                return store.save_review(**self.kw)["review_id"]
            except ValueError:
                return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(save, range(4)))
        self.assertEqual(sum(r is not None for r in results), 1)
        self.assertEqual(len(store.get_review_history("NS04")), 1)

    def test_rejects_wrong_case_run_policy_and_non_review_outcome(self):
        for changed in ({"case_id":"NS01"}, {"run_id":"other"}, {"policy_version":"wrong"}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                store.save_review(**{**self.kw, **changed})
        ai = copy.deepcopy(self.ai); ai["ruling"]["ruling"] = "no_action"
        with self.assertRaises(ValueError):
            store.save_review(**{**self.kw, "ai_result":ai})

    def test_cross_case_link_rejected_and_original_immutable(self):
        pending = store.save_review(**{**self.kw, "human_decision":"further_review"})
        with self.assertRaises(ValueError):
            store.save_review(**{**self.kw, "linked_review_id":"wrong"})
        final = store.save_review(**{**self.kw, "linked_review_id":pending["review_id"]})
        self.assertEqual(store.get_review_by_id(pending["review_id"])["human_decision"], "further_review")
        self.assertEqual(final["ai_result"], self.ai)
        self.assertEqual(final["linked_review_id"], pending["review_id"])

    def test_render_requires_durable_database(self):
        with patch.dict("os.environ", {"RENDER":"true", "DATABASE_URL":""}):
            with self.assertRaises(RuntimeError):
                store.get_review_for_run("NS04", "x")

    def test_missing_citations_and_zero_refund_are_not_filled_in(self):
        obj = dict(ruling="no_action", refund_cents=0, confidence=.9,
                   rationale="Reason", rider_message="Rider", driver_message="Driver")
        for extra in ({}, {"evidence_ids":["NS01:get_trip"]}, {"policy_ids":["DEMO-NOSHOW-01"]}):
            with self.subTest(extra=extra), self.assertRaises(OutputError):
                _validate_multi_agent_ruling({**obj, **extra}, 500, {"DEMO-NOSHOW-01"}, {"NS01:get_trip"}, "NS01")
        with self.assertRaises(OutputError):
            _validate_multi_agent_ruling({**obj, "ruling":"refund", "evidence_ids":["NS01:get_trip"], "policy_ids":["DEMO-NOSHOW-01"]}, 500, {"DEMO-NOSHOW-01"}, {"NS01:get_trip"}, "NS01")


if __name__ == "__main__":
    unittest.main()
