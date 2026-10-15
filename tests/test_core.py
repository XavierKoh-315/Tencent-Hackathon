import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from disputes.core import ROOT, OutputError, check_judge, load_cases, resolve, save_result, _validate_multi_agent_ruling


class ScriptedMultiAgentClient:
    """Simulate a multi-agent ADP response."""
    def __init__(self, outcome=None):
        self.review_calls = []
        self.outcome = outcome or {"ruling": "refund", "refund_cents": 500, "confidence": 0.9}

    def review(self, case_id, complaint, conversation_id, evidence_ids=None, policy_ids=None):
        self.review_calls.append({"case_id": case_id, "complaint": complaint,
                                  "conversation_id": conversation_id,
                                  "evidence_ids": evidence_ids, "policy_ids": policy_ids})
        ruling = {**self.outcome,
                  "rationale": "The driver was outside the agreed pickup radius.",
                  "rider_message": "Recommend refund of S$5.",
                  "driver_message": "GPS places the car outside the pickup radius."}
        # Cite the evidence_ids we received so the validator accepts them.
        if evidence_ids:
            ruling["evidence_ids"] = evidence_ids
        if policy_ids:
            ruling["policy_ids"] = policy_ids
        activity = [{"event": "message_added", "detail": {"type": "reply", "agent": "Judge"}}]
        debug_info = {
            "event_types": ["message.added", "text.delta", "message.done", "response.completed"],
            "message_ids": [{"message_id": "rpl_1", "type": "reply", "status": "success", "agent": "Judge"}],
            "completion_status": "success",
            "final_reply_text": "{}",
            "activity_event_count": 1,
        }
        return ruling, activity, debug_info


class ScriptedClient:
    """Simulate the provider contract, not the provider's AI quality."""
    def __init__(self, outcome=None):
        self.requests = []
        self.outcome = outcome or {"ruling": "refund", "refund_cents": 500, "confidence": 0.9}

    def ask(self, prompt, payload, conversation_id):
        self.requests.append((prompt, copy.deepcopy(payload), conversation_id))
        if payload["stage"] == "plan":
            return {"tools": payload["allowed_tools"]}
        refs = [e["id"] for e in payload["evidence"]]
        policies = next(e["data"]["clauses"] for e in payload["evidence"] if e["tool"] == "get_policy")
        if payload["stage"] == "case":
            return {"position": "refund" if payload["role"] == "Rider Advocate" else "no_action",
                    "statement": "Review these recorded facts against the cited demo clause.",
                    "evidence_ids": refs, "policy_ids": [p["id"] for p in policies]}
        return {**self.outcome, "rationale": "The driver was outside the agreed pickup radius.",
                "rider_message": "Recommend refund of S$5.", "driver_message": "GPS places the car outside the pickup radius.",
                "evidence_ids": refs, "policy_ids": [p["id"] for p in policies]}


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.cases = {c["trip_id"]: c for c in load_cases()}

    def test_declared_policy_outcomes(self):
        expected = json.loads((ROOT / "data/expected_results.json").read_text())
        for key, case in self.cases.items():
            with self.subTest(trip=key):
                verdict = resolve(case, mode="offline")["ruling"]
                self.assertEqual({k: verdict[k] for k in expected[key]}, expected[key])

    def test_low_ratings_do_not_change_policy_outcome(self):
        case = copy.deepcopy(self.cases["NS02"])
        case["history"]["rider"] = {"account_age_days": 1, "rating": 1.0, "previous_disputes": 100}
        self.assertEqual(resolve(case, mode="offline")["ruling"]["ruling"], "no_action")

    def test_refund_does_not_exceed_supported_excess_fare(self):
        case = copy.deepcopy(self.cases["RT01"])
        case["payment"]["reference_fare_cents"] = case["payment"]["charged_cents"] - 25
        self.assertEqual(resolve(case, mode="offline")["ruling"]["refund_cents"], 25)

    def test_provider_selects_tools_and_roles_are_isolated(self):
        client = ScriptedClient()
        result = resolve(self.cases["NS01"], mode="adp", client=client)
        self.assertEqual(result["ruling"]["ruling"], "refund")
        sessions = [entry[2] for entry in client.requests]
        self.assertEqual(sessions[0], sessions[1])
        self.assertEqual(sessions[2], sessions[3])
        self.assertEqual(len(set(sessions)), 3)
        self.assertEqual(len(client.requests), 5)
        self.assertNotIn("expected_results", json.dumps(client.requests))

    def test_unsupported_model_amount_escalates(self):
        client = ScriptedClient({"ruling": "refund", "refund_cents": 100, "confidence": 0.95})
        result = resolve(self.cases["NS01"], mode="adp", client=client)
        self.assertEqual(result["ruling"]["ruling"], "human_review")
        self.assertEqual(result["ruling"]["refund_cents"], 0)
        self.assertTrue(any(e["event"] == "review_required" for e in result["trace"]))

    def test_low_model_confidence_escalates(self):
        client = ScriptedClient({"ruling": "refund", "refund_cents": 500, "confidence": 0.4})
        self.assertEqual(resolve(self.cases["NS01"], mode="adp", client=client)["ruling"]["ruling"], "human_review")

    def test_fabricated_evidence_and_boolean_amount_rejected(self):
        obj = {"ruling": "refund", "refund_cents": True, "confidence": 0.9, "rationale": "x",
               "rider_message": "x", "driver_message": "x", "evidence_ids": ["gps"], "policy_ids": ["p"]}
        with self.assertRaises(OutputError):
            check_judge(obj, {"gps"}, {"p"}, 500)
        obj["refund_cents"] = 500
        obj["evidence_ids"] = ["invented"]
        with self.assertRaises(OutputError):
            check_judge(obj, {"gps"}, {"p"}, 500)

    def test_results_persist_without_provider_secret(self):
        result = resolve(self.cases["NS01"], mode="offline")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cases.sqlite3"
            save_result(result, path)
            db = sqlite3.connect(path)
            try:
                payload = db.execute("SELECT result_json FROM cases").fetchone()[0]
            finally:
                db.close()
            self.assertEqual(json.loads(payload)["run_id"], result["run_id"])
            self.assertNotIn("AppKey", payload)

    def test_new_dispute_does_not_reuse_agent_context(self):
        client = ScriptedClient()
        resolve(self.cases["NS01"], mode="adp", client=client)
        first = {r[2] for r in client.requests}
        client.requests.clear()
        resolve(self.cases["NS01"], mode="adp", client=client)
        self.assertTrue(first.isdisjoint({r[2] for r in client.requests}))

    def test_multi_agent_mode_single_call(self):
        """Multi-agent mode sends exactly one review() call, not five ask() calls."""
        client = ScriptedMultiAgentClient()
        result = resolve(self.cases["NS01"], mode="multi_agent", client=client)
        self.assertEqual(len(client.review_calls), 1)
        self.assertEqual(result["mode"], "multi_agent")
        self.assertEqual(result["ruling"]["ruling"], "refund")
        self.assertIn("adp_activity", result)
        self.assertTrue(len(result["adp_activity"]) > 0)

    def test_multi_agent_mode_uses_fresh_conversation_per_review(self):
        client = ScriptedMultiAgentClient()
        resolve(self.cases["NS01"], mode="multi_agent", client=client)
        first_conv = client.review_calls[0]["conversation_id"]
        resolve(self.cases["NS01"], mode="multi_agent", client=client)
        second_conv = client.review_calls[1]["conversation_id"]
        self.assertNotEqual(first_conv, second_conv)

    def test_multi_agent_mode_validates_amount_bounds(self):
        client = ScriptedMultiAgentClient({"ruling": "refund", "refund_cents": 99999, "confidence": 0.9})
        with self.assertRaises(OutputError):
            resolve(self.cases["NS01"], mode="multi_agent", client=client)

    def test_multi_agent_mode_no_appkey_in_result(self):
        client = ScriptedMultiAgentClient()
        result = resolve(self.cases["NS01"], mode="multi_agent", client=client)
        result_json = json.dumps(result)
        self.assertNotIn("AppKey", result_json)

    def test_multi_agent_ruling_validation_rejects_wrong_case(self):
        with self.assertRaises(OutputError):
            _validate_multi_agent_ruling(
                {"case_id": "WRONG", "ruling": "refund", "refund_cents": 0,
                 "confidence": 0.9, "rationale": "x", "rider_message": "x",
                 "driver_message": "x"},
                500, {"DEMO-NOSHOW-01"}, {"e1"}, "NS01")

    def test_multi_agent_ruling_validation_rejects_invalid_ruling(self):
        with self.assertRaises(OutputError):
            _validate_multi_agent_ruling(
                {"ruling": "execute", "refund_cents": 0,
                 "confidence": 0.9, "rationale": "x", "rider_message": "x",
                 "driver_message": "x"},
                500, {"DEMO-NOSHOW-01"}, {"e1"}, "NS01")

    def test_multi_agent_evidence_ids_sent_to_adp(self):
        """resolve() must pass evidence_ids and policy_ids to review()."""
        client = ScriptedMultiAgentClient()
        resolve(self.cases["NS01"], mode="multi_agent", client=client)
        call = client.review_calls[0]
        self.assertIsNotNone(call["evidence_ids"])
        self.assertIsNotNone(call["policy_ids"])
        # Evidence IDs should match the {trip_id}:{tool} format
        for eid in call["evidence_ids"]:
            self.assertTrue(eid.startswith("NS01:"))
        # Policy IDs should include the clause for this case category
        self.assertIn("DEMO-NOSHOW-01", call["policy_ids"])

    def test_multi_agent_evidence_ids_for_route_deviation(self):
        """Route-deviation cases should send the correct clause ID."""
        client = ScriptedMultiAgentClient()
        resolve(self.cases["RT01"], mode="multi_agent", client=client)
        call = client.review_calls[0]
        self.assertIn("DEMO-ROUTE-01", call["policy_ids"])
        for eid in call["evidence_ids"]:
            self.assertTrue(eid.startswith("RT01:"))

    def test_multi_agent_validation_debug_on_evidence_id_mismatch(self):
        """When the Judge returns unrecognised evidence_ids, OutputError should
        carry validation_debug with the expected vs returned IDs."""
        class BadClient(ScriptedMultiAgentClient):
            def review(self, case_id, complaint, conversation_id, evidence_ids=None, policy_ids=None):
                self.review_calls.append({"case_id": case_id, "complaint": complaint,
                                          "conversation_id": conversation_id,
                                          "evidence_ids": evidence_ids, "policy_ids": policy_ids})
                ruling = {**self.outcome,
                          "rationale": "x", "rider_message": "x", "driver_message": "x",
                          "evidence_ids": ["FAKE_ID"], "policy_ids": ["FAKE_CLAUSE"]}
                return ruling, [], {"event_types": [], "message_ids": [],
                                    "completion_status": "success",
                                    "final_reply_text": "{}", "activity_event_count": 0}

        client = BadClient()
        with self.assertRaises(OutputError) as ctx:
            resolve(self.cases["NS01"], mode="multi_agent", client=client)
        self.assertTrue(hasattr(ctx.exception, "validation_debug"))
        self.assertEqual(ctx.exception.validation_debug["judge_evidence_ids"], ["FAKE_ID"])
        self.assertIn("NS01:get_trip", ctx.exception.validation_debug["accepted_evidence_ids"])


if __name__ == "__main__":
    unittest.main()
