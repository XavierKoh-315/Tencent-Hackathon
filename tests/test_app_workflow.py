"""Streamlit interaction regressions. All AI results are local test fixtures."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import human_review_store as store
from disputes.core import load_cases, resolve
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {"NS01": ("refund", 500), "NS02": ("no_action", 0),
            "NS03": ("refund", 500), "NS04": ("human_review", 0),
            "RT01": ("refund", 369), "RT02": ("no_action", 0),
            "DISP-001": ("human_review", 0), "DISP-003": ("refund", 450)}


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root_patch = patch.object(store, "ROOT", Path(self.tmp.name))
        self.env_patch = patch.dict("os.environ", {"DATABASE_URL": "", "RENDER": "", "RENDER_SERVICE_ID": ""})
        self.root_patch.start()
        self.env_patch.start()
        self.cases = {c["trip_id"]: c for c in load_cases()}

    def tearDown(self):
        self.root_patch.stop()
        self.env_patch.stop()
        self.tmp.cleanup()

    def app(self, case_id="NS04"):
        result = resolve(self.cases[case_id], mode="offline")
        result["ruling"]["confidence"] = .83
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=15)
        at.session_state["selected_case"] = case_id
        at.session_state["result"] = result
        at.run()
        self.assertFalse(at.exception, str(at.exception))
        return at, result

    def open_form(self, at):
        next(b for b in at.button if b.label == "📝 Review case").click().run()
        self.assertFalse(at.exception, str(at.exception))
        return at

    def fill(self, at, result, decision="refund", amount="5.00"):
        cid, rid = result["trip_id"], result["run_id"]
        at.selectbox(key=f"review_decision_{cid}_{rid}").set_value(decision).run()
        at.text_input(key=f"reviewer_id_{cid}_{rid}").set_value("demo-reviewer")
        if decision == "refund":
            at.text_input(key=f"refund_amount_{cid}_{rid}").set_value(amount)
        for prefix in ("rider_msg", "driver_msg", "final_expl"):
            at.text_area(key=f"{prefix}_{cid}_{rid}").set_value("Proposed resolution based on the supplied evidence.")

    def save(self, at):
        next(b for b in at.button if b.label == "Save human review").click().run()
        self.assertFalse(at.exception, str(at.exception))

    def test_all_eight_local_results_and_rendering(self):
        for cid, expected in EXPECTED.items():
            with self.subTest(case=cid):
                at, result = self.app(cid)
                self.assertEqual((result["ruling"]["ruling"], result["ruling"]["refund_cents"]), expected)
                self.assertEqual(at.selectbox(key="case_select").options.__len__(), 8)
                self.assertTrue(any("Investigation completed" in m.value for m in at.markdown))
                # HTML must not become visible Markdown source-code blocks.
                self.assertFalse(any('<div class="card"' in c.value for c in at.code))

    def test_dollar_amounts_and_bold_prose_never_enter_math_parser(self):
        at, result = self.app("NS01")
        text = ("Rider was charged $5. **Evidence shows the driver was 333.6 meters away.** "
                "The driver waited **360 seconds**. Refund the **$5** (500 cents). "
                "Policy **DEMO-NOSHOW-01** applies. <script>alert('x')</script>")
        result["ruling"]["rationale"] = text
        at.session_state["result"] = result
        at.run()
        self.assertFalse(at.exception, str(at.exception))
        blocks = [e.proto.body for e in at.get("html")]
        prose = next(body for body in blocks if 'class="public-explanation"' in body)
        self.assertIn("Evidence shows the driver was 333.6 meters away.", prose)
        self.assertIn("<strong>$5</strong>", prose)
        self.assertIn("<strong>360 seconds</strong>", prose)
        self.assertIn("<strong>DEMO-NOSHOW-01</strong>", prose)
        self.assertNotIn("**", prose)
        self.assertNotIn("<script>", prose)
        self.assertIn("&lt;script&gt;", prose)
        self.assertFalse(any("Rider was charged" in m.value for m in at.markdown))

    def test_review_context_preserves_dollars_spaces_and_untrusted_text(self):
        at, result = self.app("DISP-001")
        result["complaint"] = "The quote was $28 and the fare was $35. <script>bad()</script>"
        result["ruling"]["escalation_reason"] = (
            "The dispute is $6.50; a candidate remedy of **$3.44** requires review."
        )
        at.session_state["result"] = result
        at.run()
        self.open_form(at)
        context = next(e.proto.body for e in at.get("html") if 'class="review-context"' in e.proto.body)
        self.assertIn("The quote was <strong>$28</strong> and the fare was <strong>$35</strong>.", context)
        self.assertIn("<strong>$6.50</strong>", context)
        self.assertIn("<strong>$3.44</strong>", context)
        self.assertIn("&lt;script&gt;", context)
        self.assertNotIn("<script>", context)
        self.assertFalse(any("The quote was" in m.value for m in at.markdown))

    def test_refund_choice_updates_amount_immediately_and_saves(self):
        at, result = self.app()
        original = copy.deepcopy(result)
        self.open_form(at)
        self.fill(at, result)
        self.assertFalse(at.text_input(key=f'refund_amount_NS04_{result["run_id"]}').disabled)
        self.save(at)
        self.assertFalse(at.error, str(at.error))
        saved = store.get_review_for_run("NS04", result["run_id"])
        self.assertEqual(saved["refund_cents"], 500)
        self.assertEqual(saved["ai_result"], original)
        self.assertEqual(saved["original_confidence"], .83)
        self.assertTrue(any("Human review completed" in m.value for m in at.markdown))
        self.assertTrue(any("Not applicable — human decision" in m.value for m in at.markdown))
        # Full refresh restores the saved run from the durable review link.
        fresh = AppTest.from_file(str(ROOT / "app.py"), default_timeout=15)
        fresh.query_params.update(at.query_params)
        fresh.run()
        self.assertFalse(fresh.exception, str(fresh.exception))
        self.assertEqual(fresh.session_state["result"]["run_id"], result["run_id"])

    def test_invalid_amount_keeps_draft_and_no_record(self):
        at, result = self.app()
        self.open_form(at)
        self.fill(at, result, amount="NaN")
        self.save(at)
        self.assertTrue(at.error)
        self.assertIsNone(store.get_review_for_run("NS04", result["run_id"]))
        self.assertEqual(at.text_input(key=f'reviewer_id_NS04_{result["run_id"]}').value, "demo-reviewer")

    def test_further_review_stays_pending_and_can_be_completed(self):
        at, result = self.app()
        self.open_form(at)
        self.fill(at, result, decision="further_review")
        self.save(at)
        first = store.get_review_for_run("NS04", result["run_id"])
        self.assertTrue(any("Further human review required" in m.value for m in at.markdown))
        self.open_form(at)
        self.fill(at, result, decision="no_action")
        self.save(at)
        latest = store.get_review_for_run("NS04", result["run_id"])
        self.assertEqual(latest["human_decision"], "no_action")
        self.assertEqual(latest["linked_review_id"], first["review_id"])
        self.assertEqual(len(store.get_review_history("NS04")), 2)

    def test_database_read_failure_keeps_ai_result_and_disables_form(self):
        with patch("human_review_store._get_connection", side_effect=RuntimeError("secret-password")):
            at, _ = self.app()
        self.assertTrue(at.warning)
        self.assertFalse(any("secret-password" in w.value for w in at.warning))
        self.assertFalse(any(b.label == "📝 Review case" for b in at.button))

    def test_switching_case_and_back_reuses_result_without_adp(self):
        at, result = self.app()
        at.selectbox(key="case_select").set_value("NS01").run()
        at.selectbox(key="case_select").set_value("NS04").run()
        self.assertFalse(at.exception, str(at.exception))
        self.assertEqual(at.session_state["result"]["run_id"], result["run_id"])


if __name__ == "__main__":
    unittest.main()
