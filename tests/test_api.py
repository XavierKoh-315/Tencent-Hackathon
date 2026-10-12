"""API tests for the FastAPI evidence endpoints.

Uses FastAPI's TestClient (no network or deployed server required).
Verifies valid retrieval, unknown cases, malformed input, and the
exclusion of secrets, expected outcomes, and judge decisions.
"""
import json
import unittest

from fastapi.testclient import TestClient

from api import app
from disputes.core import load_cases, load_policy

client = TestClient(app)

ALL_ENDPOINTS = [
    "/tools/get_trip",
    "/tools/get_messages",
    "/tools/get_payment",
    "/tools/get_policy",
    "/tools/get_metrics",
]

FORBIDDEN_KEYS = {
    "AppKey", "ADP_APP_KEY", "ADP_ENDPOINT", "ADP_MODEL_NAME",
    "ruling", "refund_cents", "confidence", "rationale",
    "rider_message", "driver_message", "policy_ids", "evidence_ids",
}


class HealthTests(unittest.TestCase):
    def test_health_returns_ok(self):
        r = client.get("/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertTrue(body["synthetic_only"])


class ValidRetrievalTests(unittest.TestCase):
    """Every endpoint must return 200 with correct data for known cases."""

    def setUp(self):
        self.cases = {c["trip_id"]: c for c in load_cases()}
        self.policy = load_policy()

    def test_get_trip_returns_trip_data(self):
        r = client.post("/tools/get_trip", json={"case_id": "NS01"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["case_id"], "NS01")
        self.assertTrue(body["synthetic"])
        self.assertEqual(body["data"]["trip"], self.cases["NS01"]["trip"])

    def test_get_messages_returns_message_list(self):
        r = client.post("/tools/get_messages", json={"case_id": "RT01"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["case_id"], "RT01")
        self.assertEqual(body["data"]["messages"], self.cases["RT01"]["messages"])

    def test_get_payment_returns_payment_fields(self):
        r = client.post("/tools/get_payment", json={"case_id": "NS01"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["data"]["payment"], self.cases["NS01"]["payment"])

    def test_get_policy_returns_clause_for_noshow(self):
        r = client.post("/tools/get_policy", json={"case_id": "NS01"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        data = body["data"]
        self.assertTrue(data["demo_policy"])
        self.assertEqual(data["version"], self.policy["version"])
        self.assertEqual(len(data["clauses"]), 1)
        self.assertEqual(data["clauses"][0]["id"], "DEMO-NOSHOW-01")

    def test_get_policy_returns_clause_for_route(self):
        r = client.post("/tools/get_policy", json={"case_id": "RT01"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        data = body["data"]
        self.assertTrue(data["demo_policy"])
        self.assertEqual(data["clauses"][0]["id"], "DEMO-ROUTE-01")

    def test_get_metrics_returns_calculated_values_noshow(self):
        r = client.post("/tools/get_metrics", json={"case_id": "NS01"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        metrics = body["data"]["metrics"]
        self.assertIn("max_pickup_distance_m", metrics)
        self.assertIn("verified_wait_seconds", metrics)
        self.assertTrue(metrics["max_pickup_distance_m"] > 100)

    def test_get_metrics_returns_calculated_values_route(self):
        r = client.post("/tools/get_metrics", json={"case_id": "RT01"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        metrics = body["data"]["metrics"]
        self.assertIn("deviation_ratio", metrics)
        self.assertIn("calculated_refund_cents", metrics)
        self.assertTrue(metrics["deviation_ratio"] > 1.2)

    def test_every_endpoint_works_for_every_known_case(self):
        for case_id in self.cases:
            for endpoint in ALL_ENDPOINTS:
                with self.subTest(case=case_id, endpoint=endpoint):
                    r = client.post(endpoint, json={"case_id": case_id})
                    self.assertEqual(r.status_code, 200, f"{endpoint} failed for {case_id}")
                    self.assertEqual(r.json()["case_id"], case_id)


class UnknownCaseTests(unittest.TestCase):
    """Unknown case_id must return 404."""

    def test_unknown_case_returns_404(self):
        for endpoint in ALL_ENDPOINTS:
            with self.subTest(endpoint=endpoint):
                r = client.post(endpoint, json={"case_id": "ZZ99"})
                self.assertEqual(r.status_code, 404)
                self.assertIn("ZZ99", r.json()["detail"])

    def test_unknown_case_lists_available_ids(self):
        r = client.post("/tools/get_trip", json={"case_id": "FAKE"})
        self.assertEqual(r.status_code, 404)
        detail = r.json()["detail"]
        self.assertIn("NS01", detail)
        self.assertIn("RT01", detail)


class InvalidInputTests(unittest.TestCase):
    """Malformed requests must return validation errors."""

    def test_empty_case_id_returns_422(self):
        r = client.post("/tools/get_trip", json={"case_id": ""})
        self.assertEqual(r.status_code, 422)

    def test_missing_case_id_returns_422(self):
        r = client.post("/tools/get_trip", json={})
        self.assertEqual(r.status_code, 422)

    def test_non_string_case_id_returns_422(self):
        r = client.post("/tools/get_trip", json={"case_id": 123})
        self.assertEqual(r.status_code, 422)

    def test_whitespace_only_case_id_returns_422(self):
        r = client.post("/tools/get_trip", json={"case_id": "   "})
        self.assertEqual(r.status_code, 422)

    def test_missing_body_returns_422(self):
        r = client.post("/tools/get_trip")
        self.assertEqual(r.status_code, 422)


class SecretExclusionTests(unittest.TestCase):
    """No endpoint may expose credentials, expected outcomes, or judge decisions."""

    def _all_responses(self):
        from disputes.core import load_cases
        for case_id in [c["trip_id"] for c in load_cases()]:
            for endpoint in ALL_ENDPOINTS:
                r = client.post(endpoint, json={"case_id": case_id})
                self.assertEqual(r.status_code, 200)
                yield endpoint, case_id, r.json()

    def test_no_credentials_in_any_response(self):
        for endpoint, case_id, body in self._all_responses():
            flat = json.dumps(body, ensure_ascii=False)
            for key in ("AppKey", "ADP_APP_KEY", "ADP_ENDPOINT", "ADP_MODEL_NAME",
                        "password", "secret", "token"):
                self.assertNotIn(key, flat,
                                 f"{key} found in {endpoint} response for {case_id}")

    def test_no_expected_results_or_judge_outcomes(self):
        # Exact top-level keys that must never appear in any response.
        judge_keys = {"ruling", "refund_cents", "confidence", "rationale",
                      "rider_message", "driver_message", "policy_ids",
                      "evidence_ids", "expected_results"}
        for endpoint, case_id, body in self._all_responses():
            for key in body:
                self.assertNotIn(key, judge_keys,
                                 f"Judge key '{key}' in {endpoint} for {case_id}")
            if isinstance(body.get("data"), dict):
                for key in body["data"]:
                    self.assertNotIn(key, judge_keys,
                                     f"Judge key 'data.{key}' in {endpoint} for {case_id}")
            flat = json.dumps(body, ensure_ascii=False)
            self.assertNotIn("expected_results", flat)
            self.assertNotIn("rider_message", flat)
            self.assertNotIn("driver_message", flat)
            self.assertNotIn('"ruling"', flat)
            self.assertNotIn('"confidence"', flat)
            self.assertNotIn('"rationale"', flat)

    def test_response_keys_do_not_include_forbidden_fields(self):
        for endpoint, case_id, body in self._all_responses():
            for key in body:
                self.assertNotIn(key, FORBIDDEN_KEYS,
                                 f"Forbidden key '{key}' in {endpoint} for {case_id}")
            if isinstance(body.get("data"), dict):
                for key in body["data"]:
                    self.assertNotIn(key, FORBIDDEN_KEYS,
                                     f"Forbidden key 'data.{key}' in {endpoint} for {case_id}")


class IsolationTests(unittest.TestCase):
    """Each request returns only the requested tool's data, not other tools."""

    def test_get_trip_does_not_include_payment(self):
        r = client.post("/tools/get_trip", json={"case_id": "NS01"})
        data = r.json()["data"]
        self.assertNotIn("payment", data)
        trip = data["trip"]
        self.assertNotIn("charged_cents", trip)
        self.assertNotIn("cancellation_fee_cents", trip)

    def test_get_payment_does_not_include_trip(self):
        r = client.post("/tools/get_payment", json={"case_id": "NS01"})
        data = r.json()["data"]
        self.assertNotIn("trip", data)
        self.assertNotIn("messages", data)
        self.assertNotIn("metrics", data)

    def test_get_policy_does_not_include_metrics(self):
        r = client.post("/tools/get_policy", json={"case_id": "NS01"})
        data = r.json()["data"]
        self.assertNotIn("metrics", data)
        self.assertNotIn("deviation_ratio", data)
        self.assertNotIn("verified_wait_seconds", data)

    def test_response_has_only_four_top_level_keys(self):
        for case_id in ("NS01", "RT01"):
            for endpoint in ALL_ENDPOINTS:
                with self.subTest(case=case_id, endpoint=endpoint):
                    r = client.post(endpoint, json={"case_id": case_id})
                    self.assertEqual(r.status_code, 200)
                    body = r.json()
                    self.assertEqual(set(body.keys()),
                                     {"case_id", "evidence_id", "synthetic", "data"})

    def test_evidence_id_format_matches_validator(self):
        """evidence_id must be {case_id}:{tool} to match the Python validator."""
        for case_id in ("NS01", "RT01"):
            for endpoint in ALL_ENDPOINTS:
                with self.subTest(case=case_id, endpoint=endpoint):
                    r = client.post(endpoint, json={"case_id": case_id})
                    body = r.json()
                    tool = endpoint.replace("/tools/", "")
                    self.assertEqual(body["evidence_id"], f"{case_id}:{tool}")


if __name__ == "__main__":
    unittest.main()
