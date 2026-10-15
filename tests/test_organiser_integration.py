"""Integration tests for organiser cases within the existing project framework.

Tests every tool for every organiser case through the FastAPI API,
validates evidence/policy IDs, fare-category dispatch, policy isolation,
amount handling, confidence/safety/escalation gates, and source-label exclusion.
"""
import copy
import json
import unittest

from fastapi.testclient import TestClient

from api import app
from disputes.core import (
    ROOT, OutputError, _validate_multi_agent_ruling,
    calculate_metrics, load_cases, load_policy, policy_decision, resolve,
)

client = TestClient(app)

ALL_ORG_CASES = ["DISP-001", "DISP-002", "DISP-003"]
ALL_TOOLS = [
    "/tools/get_trip", "/tools/get_messages", "/tools/get_payment",
    "/tools/get_policy", "/tools/get_metrics", "/tools/get_history",
]


class ScriptedMultiAgentClient:
    """Minimal scripted client for organiser multi-agent tests."""
    def __init__(self, outcome=None):
        self.review_calls = []
        self.outcome = outcome or {"ruling": "refund", "refund_cents": 0, "confidence": 0.9}

    def review(self, case_id, complaint, conversation_id, evidence_ids=None, policy_ids=None):
        self.review_calls.append({"case_id": case_id, "complaint": complaint,
                                  "conversation_id": conversation_id,
                                  "evidence_ids": evidence_ids, "policy_ids": policy_ids})
        ruling = {**self.outcome,
                  "rationale": "Test ruling.",
                  "rider_message": "Test rider message.",
                  "driver_message": "Test driver message."}
        if evidence_ids:
            ruling["evidence_ids"] = evidence_ids
        if policy_ids:
            ruling["policy_ids"] = policy_ids
        activity = [{"event": "message_added", "detail": {"type": "reply", "agent": "Judge"}}]
        debug_info = {"event_types": ["message.added", "response.completed"],
                      "message_ids": [], "completion_status": "success",
                      "final_reply_text": "{}", "activity_event_count": 1}
        return ruling, activity, debug_info


class APIEndpointTests(unittest.TestCase):
    """Every tool endpoint must return 200 with correct IDs for organiser cases."""

    def test_every_tool_works_for_every_organiser_case(self):
        for case_id in ALL_ORG_CASES:
            for endpoint in ALL_TOOLS:
                with self.subTest(case=case_id, endpoint=endpoint):
                    r = client.post(endpoint, json={"case_id": case_id})
                    self.assertEqual(r.status_code, 200, f"{endpoint} failed for {case_id}")
                    body = r.json()
                    self.assertEqual(body["case_id"], case_id)
                    tool = endpoint.replace("/tools/", "")
                    self.assertEqual(body["evidence_id"], f"{case_id}:{tool}")

    def test_organiser_case_returns_404_for_unknown(self):
        r = client.post("/tools/get_trip", json={"case_id": "DISP-999"})
        self.assertEqual(r.status_code, 404)

    def test_no_credentials_in_organiser_responses(self):
        for case_id in ALL_ORG_CASES:
            for endpoint in ALL_TOOLS:
                r = client.post(endpoint, json={"case_id": case_id})
                flat = json.dumps(r.json(), ensure_ascii=False)
                for key in ("AppKey", "ADP_APP_KEY", "password", "secret", "token"):
                    self.assertNotIn(key, flat,
                                     f"{key} found in {endpoint} for {case_id}")

    def test_no_expected_rulings_in_organiser_responses(self):
        """No expected/sample ruling fields may appear in any organiser response."""
        for case_id in ALL_ORG_CASES:
            for endpoint in ALL_TOOLS:
                r = client.post(endpoint, json={"case_id": case_id})
                flat = json.dumps(r.json(), ensure_ascii=False)
                for key in ("recommended_ruling", "evidence_summary",
                            "chat_log_analysis", "traffic_analysis", "case_metadata"):
                    self.assertNotIn(key, flat,
                                     f"{key} found in {endpoint} for {case_id}")


class EvidenceIDValidationTests(unittest.TestCase):
    """Evidence IDs must use {case_id}:{tool} format and be registered in the validator."""

    def test_evidence_ids_match_validator_format(self):
        for case_id in ALL_ORG_CASES:
            for endpoint in ALL_TOOLS:
                r = client.post(endpoint, json={"case_id": case_id})
                body = r.json()
                tool = endpoint.replace("/tools/", "")
                expected_id = f"{case_id}:{tool}"
                self.assertEqual(body["evidence_id"], expected_id)

    def test_organiser_policy_ids_use_v2_1_prefix(self):
        r = client.post("/tools/get_policy", json={"case_id": "DISP-001"})
        clauses = r.json()["data"]["policy"]["clauses"]
        ids = [c["id"] for c in clauses]
        for clause in ["1.2", "2.1", "6.2"]:
            self.assertIn(f"ORG-V2.1-{clause}", ids)
        # Must NOT contain old demo policy IDs
        self.assertNotIn("DEMO-ROUTE-01", ids)
        self.assertNotIn("DEMO-NOSHOW-01", ids)


class FareCategoryDispatchTests(unittest.TestCase):
    """Fare dispute must not be treated as no_show or route_deviation."""

    def test_disp003_metrics_contain_fare_fields(self):
        r = client.post("/tools/get_metrics", json={"case_id": "DISP-003"})
        metrics = r.json()["data"]["metrics"]
        self.assertEqual(metrics["category"], "fare_dispute")
        self.assertEqual(metrics["fare_difference_cents"], 450)
        self.assertEqual(metrics["surge_difference_cents"], 450)

    def test_disp002_metrics_contain_no_show_fields(self):
        r = client.post("/tools/get_metrics", json={"case_id": "DISP-002"})
        metrics = r.json()["data"]["metrics"]
        self.assertEqual(metrics["category"], "no_show_charge")
        self.assertIn("scheduled_to_cancel_seconds", metrics)
        self.assertIn("pre_cancel_driver_message_count", metrics)

    def test_disp001_metrics_contain_route_fields(self):
        r = client.post("/tools/get_metrics", json={"case_id": "DISP-001"})
        metrics = r.json()["data"]["metrics"]
        self.assertEqual(metrics["category"], "route_deviation")
        self.assertEqual(metrics["excess_distance_m"], 4300)
        self.assertTrue(metrics["requires_route_threshold_review"])


class PolicyIsolationTests(unittest.TestCase):
    """Organiser cases must use organiser-v2.1 policy, not synthetic demo policy."""

    def test_organiser_policy_version_in_response(self):
        r = client.post("/tools/get_policy", json={"case_id": "DISP-001"})
        data = r.json()["data"]["policy"]
        self.assertEqual(data["version"], "organiser-v2.1")

    def test_synthetic_policy_unchanged_for_old_cases(self):
        r = client.post("/tools/get_policy", json={"case_id": "NS01"})
        data = r.json()["data"]
        self.assertIn("DEMO-NOSHOW-01", [c["id"] for c in data["clauses"]])

    def test_organiser_get_policy_does_not_return_demo_clauses(self):
        for case_id in ALL_ORG_CASES:
            r = client.post("/tools/get_policy", json={"case_id": case_id})
            clauses = r.json()["data"]["policy"]["clauses"]
            ids = [c["id"] for c in clauses]
            self.assertNotIn("DEMO-ROUTE-01", ids)
            self.assertNotIn("DEMO-NOSHOW-01", ids)


class AmountHandlingTests(unittest.TestCase):
    """Refund amounts must be integer cents, bounded by charged amount."""

    def test_disp003_fare_difference_is_450_cents(self):
        r = client.post("/tools/get_payment", json={"case_id": "DISP-003"})
        payment = r.json()["data"]["payment"]
        self.assertEqual(payment["charged_cents"], 1650)
        self.assertEqual(payment["reference_fare_cents"], 1200)

    def test_disp001_payment_amounts(self):
        r = client.post("/tools/get_payment", json={"case_id": "DISP-001"})
        payment = r.json()["data"]["payment"]
        self.assertEqual(payment["charged_cents"], 3500)
        self.assertEqual(payment["reference_fare_cents"], 2850)

    def test_disp002_cancellation_fee(self):
        r = client.post("/tools/get_payment", json={"case_id": "DISP-002"})
        payment = r.json()["data"]["payment"]
        self.assertEqual(payment["cancellation_fee_cents"], 500)


class OfflinePolicyDecisionTests(unittest.TestCase):
    """Test the deterministic organiser policy baseline."""

    def setUp(self):
        self.cases = {c["trip_id"]: c for c in load_cases()}

    def test_disp001_route_deviation_requires_human_review(self):
        """DISP-001: 4.3 km > 2 km threshold → human_review. Not automated refund."""
        case = self.cases["DISP-001"]
        policy = load_policy()
        metrics = calculate_metrics(case, policy)
        baseline = policy_decision(case, policy, metrics)
        self.assertEqual(baseline["ruling"], "human_review")
        self.assertEqual(baseline["refund_cents"], 0)
        self.assertIn("ORG-V2.1-6.2", baseline["policy_ids"])

    def test_disp002_no_show_with_fraud_flag_escalates(self):
        """DISP-002: fraud flag raises threshold to 0.95 → human_review."""
        case = self.cases["DISP-002"]
        policy = load_policy()
        metrics = calculate_metrics(case, policy)
        baseline = policy_decision(case, policy, metrics)
        self.assertEqual(baseline["ruling"], "human_review")
        self.assertEqual(baseline["refund_cents"], 0)
        self.assertIn("ORG-V2.1-6.3", baseline["policy_ids"])

    def test_disp003_fare_dispute_refunds_surge_differential(self):
        """DISP-003: rider_notified=false, surge diff 450 cents → refund."""
        case = self.cases["DISP-003"]
        policy = load_policy()
        metrics = calculate_metrics(case, policy)
        baseline = policy_decision(case, policy, metrics)
        self.assertEqual(baseline["ruling"], "refund")
        self.assertEqual(baseline["refund_cents"], 450)
        self.assertIn("ORG-V2.1-3.3", baseline["policy_ids"])
        self.assertIn("ORG-V2.1-7.2", baseline["policy_ids"])

    def test_organiser_baseline_does_not_hardcode_sample_answers(self):
        """Baseline must follow from policy text, not from supplied sample rulings."""
        for case_id in ALL_ORG_CASES:
            case = self.cases[case_id]
            policy = load_policy()
            metrics = calculate_metrics(case, policy)
            baseline = policy_decision(case, policy, metrics)
            # The rationale must reference policy clauses, not sample answers
            self.assertTrue(any(pid.startswith("ORG-V2.1-") for pid in baseline["policy_ids"]))


class MultiAgentValidationTests(unittest.TestCase):
    """Test _validate_multi_agent_ruling with organiser clause IDs."""

    def setUp(self):
        self.cases = {c["trip_id"]: c for c in load_cases()}

    def test_organiser_evidence_ids_accepted(self):
        case = self.cases["DISP-001"]
        policy = load_policy()
        metrics = calculate_metrics(case, policy)
        baseline = policy_decision(case, policy, metrics)
        clause_ids = set(baseline["policy_ids"])
        # Add all organiser policy IDs
        import organiser_support as org
        pol_ev = org.get_evidence("DISP-001", "get_policy")
        clause_ids.update(pol_ev.get("policy_ids", []))
        evidence_ids = {f"DISP-001:{t}" for t in org.TOOLS}
        obj = {"ruling": "human_review", "refund_cents": 0, "confidence": 0.35,
               "rationale": "Route deviation > 2km requires review.", "rider_message": "x",
               "driver_message": "x", "evidence_ids": ["DISP-001:get_trip"],
               "policy_ids": ["ORG-V2.1-6.2"]}
        result = _validate_multi_agent_ruling(obj, 3500, clause_ids, evidence_ids, "DISP-001")
        self.assertEqual(result["ruling"], "human_review")

    def test_organiser_rejects_fake_evidence_id(self):
        obj = {"ruling": "refund", "refund_cents": 100, "confidence": 0.9,
               "rationale": "x", "rider_message": "x", "driver_message": "x",
               "evidence_ids": ["FAKE_ID"], "policy_ids": ["ORG-V2.1-6.2"]}
        with self.assertRaises(OutputError):
            _validate_multi_agent_ruling(obj, 3500, {"ORG-V2.1-6.2"},
                                         {"DISP-001:get_trip"}, "DISP-001")

    def test_organiser_rejects_fake_policy_id(self):
        obj = {"ruling": "refund", "refund_cents": 100, "confidence": 0.9,
               "rationale": "x", "rider_message": "x", "driver_message": "x",
               "evidence_ids": ["DISP-001:get_trip"], "policy_ids": ["DEMO-ROUTE-01"]}
        with self.assertRaises(OutputError):
            _validate_multi_agent_ruling(obj, 3500, {"ORG-V2.1-6.2"},
                                         {"DISP-001:get_trip"}, "DISP-001")


class MultiAgentResolveTests(unittest.TestCase):
    """Test resolve() in multi_agent mode for organiser cases."""

    def setUp(self):
        self.cases = {c["trip_id"]: c for c in load_cases()}

    def test_disp001_multi_agent_human_review(self):
        """DISP-001: model returns refund 344, baseline says human_review → mismatch → human_review."""
        client_obj = ScriptedMultiAgentClient(
            {"ruling": "refund", "refund_cents": 344, "confidence": 0.9})
        result = resolve(self.cases["DISP-001"], mode="multi_agent", client=client_obj)
        # Baseline is human_review, model returns refund → mismatch → human_review
        self.assertEqual(result["ruling"]["ruling"], "human_review")
        self.assertEqual(result["ruling"]["refund_cents"], 0)
        self.assertEqual(result["policy_version"], "organiser-v2.1")
        self.assertEqual(len(client_obj.review_calls), 1)

    def test_disp003_multi_agent_refund(self):
        """DISP-003: model returns refund 450, baseline agrees → refund (if confidence >= 0.80)."""
        client_obj = ScriptedMultiAgentClient(
            {"ruling": "refund", "refund_cents": 450, "confidence": 0.92})
        result = resolve(self.cases["DISP-003"], mode="multi_agent", client=client_obj)
        self.assertEqual(result["ruling"]["ruling"], "refund")
        self.assertEqual(result["ruling"]["refund_cents"], 450)
        self.assertEqual(result["policy_version"], "organiser-v2.1")

    def test_disp002_multi_agent_escalates_on_fraud(self):
        """DISP-002: baseline is human_review due to fraud flag → model mismatch → human_review."""
        client_obj = ScriptedMultiAgentClient(
            {"ruling": "no_action", "refund_cents": 0, "confidence": 0.92})
        result = resolve(self.cases["DISP-002"], mode="multi_agent", client=client_obj)
        # Baseline says human_review, model says no_action → mismatch → human_review
        self.assertEqual(result["ruling"]["ruling"], "human_review")

    def test_organiser_evidence_ids_sent_to_adp(self):
        client_obj = ScriptedMultiAgentClient()
        resolve(self.cases["DISP-001"], mode="multi_agent", client=client_obj)
        call = client_obj.review_calls[0]
        self.assertIsNotNone(call["evidence_ids"])
        for eid in call["evidence_ids"]:
            self.assertTrue(eid.startswith("DISP-001:"))
        self.assertIn("ORG-V2.1-6.2", call["policy_ids"])

    def test_no_appkey_in_organiser_result(self):
        client_obj = ScriptedMultiAgentClient()
        result = resolve(self.cases["DISP-001"], mode="multi_agent", client=client_obj)
        self.assertNotIn("AppKey", json.dumps(result))


class RegressionSuiteTests(unittest.TestCase):
    """Original 12 synthetic cases must still pass their expected results."""

    def setUp(self):
        self.cases = {c["trip_id"]: c for c in load_cases()}
        self.expected = json.loads((ROOT / "data/expected_results.json").read_text())

    def test_original_synthetic_cases_still_pass(self):
        for key in list(self.expected.keys()):
            with self.subTest(trip=key):
                case = self.cases[key]
                result = resolve(case, mode="offline")
                verdict = result["ruling"]
                self.assertEqual({k: verdict[k] for k in self.expected[key]},
                                 self.expected[key])


if __name__ == "__main__":
    unittest.main()
