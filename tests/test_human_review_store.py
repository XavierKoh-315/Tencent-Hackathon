"""Tests for the human-review record storage.

Uses controlled fixtures — no ADP calls, no paid tokens, no live network.
Tests against local SQLite (the default when DATABASE_URL is unset).
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure project root is on sys.path.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Force local SQLite for tests (override any DATABASE_URL).
os.environ.pop("DATABASE_URL", None)

import human_review_store as store

# Use a temp directory for the SQLite file.
_TMP = Path(tempfile.mkdtemp(prefix="hr_test_"))
_TMP_DB = _TMP / "runtime" / "human_reviews.sqlite3"
store.ROOT = _TMP  # Redirect the module's ROOT.


def _make_ai_result(case_id="NS02", run_id="test-run-001",
                    charged_cents=500):
    """Build a minimal AI result dict matching the app's contract."""
    return {
        "run_id": run_id,
        "trip_id": case_id,
        "category": "no_show",
        "complaint": "The driver cancelled after only two minutes.",
        "policy_version": "demo-v1",
        "payment": {"charged_cents": charged_cents},
        "ruling": {
            "ruling": "human_review",
            "refund_cents": 0,
            "confidence": 0.35,
            "original_confidence": 0.92,
            "original_ruling": "no_action",
            "escalation_reason": "The model recommendation differs from the deterministic demo-policy check.",
            "rationale": "Mismatch. Refer to reviewer.",
            "rider_message": "Your dispute needs a reviewer.",
            "driver_message": "This dispute needs a reviewer.",
            "policy_ids": ["DEMO-NOSHOW-01"],
        },
        "metrics": {},
        "evidence": [],
        "trace": [],
        "elapsed_seconds": 0.04,
    }


class TestToCents(unittest.TestCase):
    def test_valid_two_decimal(self):
        self.assertEqual(store._to_cents("5.00"), 500)
        self.assertEqual(store._to_cents("4.50"), 450)
        self.assertEqual(store._to_cents("10"), 1000)

    def test_empty_returns_none(self):
        self.assertIsNone(store._to_cents(""))
        self.assertIsNone(store._to_cents("   "))

    def test_more_than_two_decimals_raises(self):
        with self.assertRaises(ValueError):
            store._to_cents("5.001")

    def test_non_numeric_raises(self):
        with self.assertRaises(ValueError):
            store._to_cents("abc")

    def test_zero_or_negative_raises(self):
        with self.assertRaises(ValueError):
            store._to_cents("0")
        with self.assertRaises(ValueError):
            store._to_cents("-5.00")

    def test_uses_decimal_not_float(self):
        # 0.1 + 0.2 = 0.30000000000000004 in float; Decimal is exact.
        self.assertEqual(store._to_cents("0.30"), 30)


class TestSaveReviewSuccess(unittest.TestCase):
    def setUp(self):
        self._cleanup()
        self.ai_result = _make_ai_result()

    def tearDown(self):
        self._cleanup()

    def _cleanup(self):
        if _TMP_DB.exists():
            _TMP_DB.unlink()

    def test_successful_refund_review(self):
        record = store.save_review(
            case_id="NS02",
            run_id="test-run-001",
            ai_result=self.ai_result,
            original_confidence=0.92,
            escalation_reason="Mismatch",
            reviewer_id="reviewer-alice",
            human_decision="refund",
            refund_amount_str="5.00",
            rider_message="Your refund is approved.",
            driver_message="No action needed.",
            final_explanation="The evidence supports a refund of the cancellation fee.",
            policy_version="demo-v1",
        )
        self.assertEqual(record["case_id"], "NS02")
        self.assertEqual(record["run_id"], "test-run-001")
        self.assertEqual(record["human_decision"], "refund")
        self.assertEqual(record["refund_cents"], 500)
        self.assertEqual(record["reviewer_id"], "reviewer-alice")
        self.assertIn("review_id", record)
        self.assertIn("created_at", record)
        # AI result preserved unchanged.
        self.assertEqual(record["ai_result"]["ruling"]["ruling"], "human_review")
        self.assertEqual(record["original_confidence"], 0.92)

    def test_successful_no_action_review(self):
        record = store.save_review(
            case_id="NS02",
            run_id="test-run-002",
            ai_result=_make_ai_result(run_id="test-run-002"),
            original_confidence=0.92,
            escalation_reason="Mismatch",
            reviewer_id="reviewer-bob",
            human_decision="no_action",
            refund_amount_str=None,
            rider_message="Charge retained.",
            driver_message="Charge is valid.",
            final_explanation="The driver waited the required time.",
            policy_version="demo-v1",
        )
        self.assertEqual(record["human_decision"], "no_action")
        self.assertEqual(record["refund_cents"], 0)

    def test_successful_further_review(self):
        record = store.save_review(
            case_id="NS02",
            run_id="test-run-003",
            ai_result=_make_ai_result(run_id="test-run-003"),
            original_confidence=0.92,
            escalation_reason="Mismatch",
            reviewer_id="reviewer-carol",
            human_decision="further_review",
            refund_amount_str=None,
            rider_message="Further investigation needed.",
            driver_message="Further investigation needed.",
            final_explanation="Conflicting evidence requires escalation.",
            policy_version="demo-v1",
        )
        self.assertEqual(record["human_decision"], "further_review")
        self.assertEqual(record["refund_cents"], 0)


class TestSaveReviewValidation(unittest.TestCase):
    def setUp(self):
        self._cleanup()
        self.ai_result = _make_ai_result()

    def tearDown(self):
        self._cleanup()

    def _cleanup(self):
        if _TMP_DB.exists():
            _TMP_DB.unlink()

    def test_empty_reviewer_raises(self):
        with self.assertRaises(ValueError):
            store.save_review(
                case_id="NS02", run_id="r1", ai_result=self.ai_result,
                original_confidence=0.9, escalation_reason=None,
                reviewer_id="  ", human_decision="no_action",
                refund_amount_str=None,
                rider_message="msg", driver_message="msg",
                final_explanation="exp", policy_version="demo-v1",
            )

    def test_empty_rider_message_raises(self):
        with self.assertRaises(ValueError):
            store.save_review(
                case_id="NS02", run_id="r1", ai_result=self.ai_result,
                original_confidence=0.9, escalation_reason=None,
                reviewer_id="rev", human_decision="no_action",
                refund_amount_str=None,
                rider_message="  ", driver_message="msg",
                final_explanation="exp", policy_version="demo-v1",
            )

    def test_refund_without_amount_raises(self):
        with self.assertRaises(ValueError):
            store.save_review(
                case_id="NS02", run_id="r1", ai_result=self.ai_result,
                original_confidence=0.9, escalation_reason=None,
                reviewer_id="rev", human_decision="refund",
                refund_amount_str="",
                rider_message="msg", driver_message="msg",
                final_explanation="exp", policy_version="demo-v1",
            )

    def test_refund_exceeds_charged_raises(self):
        with self.assertRaises(ValueError):
            store.save_review(
                case_id="NS02", run_id="r1",
                ai_result=_make_ai_result(charged_cents=500),
                original_confidence=0.9, escalation_reason=None,
                reviewer_id="rev", human_decision="refund",
                refund_amount_str="6.00",
                rider_message="msg", driver_message="msg",
                final_explanation="exp", policy_version="demo-v1",
            )

    def test_no_action_with_refund_amount_raises(self):
        with self.assertRaises(ValueError):
            store.save_review(
                case_id="NS02", run_id="r1", ai_result=self.ai_result,
                original_confidence=0.9, escalation_reason=None,
                reviewer_id="rev", human_decision="no_action",
                refund_amount_str="5.00",
                rider_message="msg", driver_message="msg",
                final_explanation="exp", policy_version="demo-v1",
            )

    def test_refund_with_unknown_charged_raises(self):
        ai = _make_ai_result()
        ai["payment"] = {}  # No charged_cents
        with self.assertRaises(ValueError):
            store.save_review(
                case_id="NS02", run_id="r1", ai_result=ai,
                original_confidence=0.9, escalation_reason=None,
                reviewer_id="rev", human_decision="refund",
                refund_amount_str="5.00",
                rider_message="msg", driver_message="msg",
                final_explanation="exp", policy_version="demo-v1",
            )

    def test_more_than_two_decimals_raises(self):
        with self.assertRaises(ValueError):
            store.save_review(
                case_id="NS02", run_id="r1",
                ai_result=_make_ai_result(charged_cents=500),
                original_confidence=0.9, escalation_reason=None,
                reviewer_id="rev", human_decision="refund",
                refund_amount_str="5.001",
                rider_message="msg", driver_message="msg",
                final_explanation="exp", policy_version="demo-v1",
            )


class TestDuplicatePrevention(unittest.TestCase):
    def setUp(self):
        self._cleanup()
        self.ai_result = _make_ai_result()

    def tearDown(self):
        self._cleanup()

    def _cleanup(self):
        if _TMP_DB.exists():
            _TMP_DB.unlink()

    def test_exact_duplicate_within_same_second_raises(self):
        kwargs = dict(
            case_id="NS02", run_id="dup-run-001",
            ai_result=_make_ai_result(run_id="dup-run-001"),
            original_confidence=0.9, escalation_reason="Mismatch",
            reviewer_id="reviewer-dup", human_decision="no_action",
            refund_amount_str=None,
            rider_message="msg", driver_message="msg",
            final_explanation="exp", policy_version="demo-v1",
        )
        # First save succeeds.
        store.save_review(**kwargs)
        # Second identical save (same case+run+reviewer+decision, same second)
        # should be rejected.
        with self.assertRaises(ValueError) as ctx:
            store.save_review(**kwargs)
        self.assertIn("duplicate", str(ctx.exception).lower())


class TestCaseRunIsolation(unittest.TestCase):
    def setUp(self):
        self._cleanup()

    def tearDown(self):
        self._cleanup()

    def _cleanup(self):
        if _TMP_DB.exists():
            _TMP_DB.unlink()

    def test_review_only_for_matching_run(self):
        ai = _make_ai_result(case_id="NS02", run_id="run-A")
        store.save_review(
            case_id="NS02", run_id="run-A", ai_result=ai,
            original_confidence=0.9, escalation_reason="Mismatch",
            reviewer_id="rev1", human_decision="no_action",
            refund_amount_str=None,
            rider_message="msg", driver_message="msg",
            final_explanation="exp", policy_version="demo-v1",
        )
        # Querying a different run should return None.
        result = store.get_review_for_run("NS02", "run-B")
        self.assertIsNone(result)
        # Querying the correct run should return the record.
        result = store.get_review_for_run("NS02", "run-A")
        self.assertIsNotNone(result)
        self.assertEqual(result["run_id"], "run-A")

    def test_different_cases_isolated(self):
        ai1 = _make_ai_result(case_id="NS02", run_id="run-1")
        ai2 = _make_ai_result(case_id="NS03", run_id="run-2")
        store.save_review(
            case_id="NS02", run_id="run-1", ai_result=ai1,
            original_confidence=0.9, escalation_reason="Mismatch",
            reviewer_id="rev1", human_decision="no_action",
            refund_amount_str=None,
            rider_message="msg", driver_message="msg",
            final_explanation="exp", policy_version="demo-v1",
        )
        # NS03 should not see NS02's review.
        self.assertIsNone(store.get_review_for_run("NS03", "run-1"))
        self.assertIsNone(store.get_review_for_run("NS03", "run-2"))


class TestPreserveAIResult(unittest.TestCase):
    def setUp(self):
        self._cleanup()

    def tearDown(self):
        self._cleanup()

    def _cleanup(self):
        if _TMP_DB.exists():
            _TMP_DB.unlink()

    def test_ai_result_not_overwritten(self):
        ai = _make_ai_result()
        ai["ruling"]["ruling"] = "human_review"
        ai["ruling"]["refund_cents"] = 0
        ai["ruling"]["confidence"] = 0.35

        record = store.save_review(
            case_id="NS02", run_id=ai["run_id"], ai_result=ai,
            original_confidence=0.92, escalation_reason="Mismatch",
            reviewer_id="rev", human_decision="refund",
            refund_amount_str="5.00",
            rider_message="rider msg", driver_message="driver msg",
            final_explanation="explanation", policy_version="demo-v1",
        )
        # The saved AI result inside the review record should still be the
        # original human_review, not overwritten with the human decision.
        self.assertEqual(record["ai_result"]["ruling"]["ruling"], "human_review")
        self.assertEqual(record["ai_result"]["ruling"]["refund_cents"], 0)
        # The human decision is separate.
        self.assertEqual(record["human_decision"], "refund")
        self.assertEqual(record["refund_cents"], 500)


class TestReviewHistory(unittest.TestCase):
    def setUp(self):
        self._cleanup()

    def tearDown(self):
        self._cleanup()

    def _cleanup(self):
        if _TMP_DB.exists():
            _TMP_DB.unlink()

    def test_history_returns_all_for_case(self):
        ai = _make_ai_result()
        store.save_review(
            case_id="NS05", run_id="run-1", ai_result=_make_ai_result("NS05", "run-1"),
            original_confidence=0.9, escalation_reason=None,
            reviewer_id="rev", human_decision="no_action",
            refund_amount_str=None,
            rider_message="msg", driver_message="msg",
            final_explanation="exp1", policy_version="demo-v1",
        )
        store.save_review(
            case_id="NS05", run_id="run-2", ai_result=_make_ai_result("NS05", "run-2"),
            original_confidence=0.9, escalation_reason=None,
            reviewer_id="rev", human_decision="refund",
            refund_amount_str="3.00",
            rider_message="msg", driver_message="msg",
            final_explanation="exp2", policy_version="demo-v1",
        )
        history = store.get_review_history("NS05")
        self.assertEqual(len(history), 2)
        # Newest first.
        self.assertEqual(history[0]["human_decision"], "refund")
        self.assertEqual(history[1]["human_decision"], "no_action")


class TestStorageFailure(unittest.TestCase):
    def test_runtime_error_on_storage_failure(self):
        # Temporarily break the connection to simulate failure.
        original = store._get_connection
        store._get_connection = lambda: (_ for _ in ()).throw(
            Exception("Simulated DB failure"))
        try:
            with self.assertRaises(RuntimeError) as ctx:
                store.save_review(
                    case_id="X", run_id="Y", ai_result={**_make_ai_result("X", "Y"), "policy_version":"p"},
                    original_confidence=None, escalation_reason=None,
                    reviewer_id="rev", human_decision="no_action",
                    refund_amount_str=None,
                    rider_message="m", driver_message="m",
                    final_explanation="e", policy_version="p",
                )
            self.assertIn("Storage failure", str(ctx.exception))
        finally:
            store._get_connection = original


if __name__ == "__main__":
    unittest.main()
