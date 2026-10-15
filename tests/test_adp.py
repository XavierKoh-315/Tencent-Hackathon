import json
import unittest

from disputes.adp import (
    ADPClient, ADPError, _classify_error, collect_activity,
    parse_json_reply, reply_text, review_text, sse_events,
)


class ADPTests(unittest.TestCase):
    def test_final_reply_excludes_thought_and_does_not_duplicate_deltas(self):
        events = [
            {"Type": "message.added", "Message": {"MessageId": "thought", "Type": "thought"}},
            {"Type": "text.delta", "MessageId": "thought", "Text": "private reasoning"},
            {"Type": "message.added", "Message": {"MessageId": "reply", "Type": "reply"}},
            {"Type": "text.delta", "MessageId": "reply", "Text": "old"},
            {"Type": "text.replace", "MessageId": "reply", "Text": '{"ruling":"refund"}'},
            {"Type": "response.completed", "Response": {"Status": "success", "Messages": [
                {"Type": "thought", "MessageId": "thought", "Contents": [{"Type": "text", "Text": "private reasoning"}]},
                {"Type": "reply", "MessageId": "reply", "Contents": [{"Type": "text", "Text": '{"ruling":"refund"}'}]}]}}
        ]
        self.assertEqual(parse_json_reply(reply_text(events)), {"ruling": "refund"})

    def test_sse_multiline_data_and_done_marker(self):
        raw = [b': heartbeat\n', b'event: text.delta\n', b'data: {"Type":"text.delta",\n',
               b'data: "Text":"ok"}\n', b'\n', b'data: [DONE]\n', b'\n']
        self.assertEqual(list(sse_events(raw)), [{"Type": "text.delta", "Text": "ok"}])

    def test_incomplete_or_failed_stream_is_not_accepted(self):
        with self.assertRaises(ADPError):
            reply_text([{"Type": "text.delta", "MessageId": "r", "Text": "partial"}])
        with self.assertRaises(ADPError):
            reply_text([{"Type": "response.completed", "Response": {"Status": "failed"}}])

    def test_missing_credentials_and_foreign_endpoint_are_rejected(self):
        with self.assertRaises(ADPError):
            ADPClient({})
        with self.assertRaises(ADPError):
            ADPClient({"ADP_APP_KEY": "test-only", "ADP_ENDPOINT": "https://example.com/chat"})

    def test_invalid_json_is_rejected(self):
        with self.assertRaises(ADPError):
            parse_json_reply("An answer that is not structured JSON.")
        self.assertEqual(parse_json_reply('```json\n{"tools": []}\n```'), {"tools": []})

    def test_parse_json_reply_extracts_from_prose(self):
        """When the Judge wraps JSON in prose, the parser should extract the JSON block."""
        prose = 'Here is my ruling:\n{"ruling": "refund", "refund_cents": 500}\nThat is all.'
        obj = parse_json_reply(prose)
        self.assertEqual(obj["ruling"], "refund")
        self.assertEqual(obj["refund_cents"], 500)

    def test_parse_json_reply_strips_markdown_fence(self):
        """Markdown code fences should be stripped before parsing."""
        obj = parse_json_reply('```json\n{"ruling": "no_action"}\n```')
        self.assertEqual(obj["ruling"], "no_action")

    def test_parse_json_reply_rejects_pure_prose_without_json(self):
        """Prose with no JSON object should still raise ADPError."""
        with self.assertRaises(ADPError):
            parse_json_reply("The driver was present at the pickup point.")


class MultiAgentParserTests(unittest.TestCase):
    """Test the review_text() parser for multi-agent SSE streams."""

    def _make_stream(self, reply_text_str, agent_name="", procedures=None, stat_info=None):
        """Build a minimal multi-agent SSE event list."""
        events = [
            {"Type": "request_ack", "RequestAck": {"Status": "success",
             "ConversationId": "test-conv-id"}},
            {"Type": "response.created", "Response": {"Status": "processing",
             "ExtraInfo": {"AgentName": agent_name}}},
        ]
        if agent_name:
            events.append({"Type": "response.processing", "Response": {
                "StatusDesc": "Invoke reasoning model"}})
        events.append({"Type": "message.added", "Message": {
            "Type": "reply", "MessageId": "rpl_1", "Status": "processing",
            "ExtraInfo": {"AgentName": agent_name}}})
        events.append({"Type": "text.delta", "MessageId": "rpl_1", "Text": reply_text_str})
        events.append({"Type": "message.done", "MessageId": "rpl_1", "Message": {
            "Type": "reply", "Status": "success",
            "Contents": [{"Type": "text", "Text": reply_text_str}],
            "ExtraInfo": {"AgentName": agent_name}}})
        completed = {"Status": "success", "Messages": [
            {"Type": "reply", "MessageId": "rpl_1",
             "Contents": [{"Type": "text", "Text": reply_text_str}]}]}
        if procedures is not None:
            completed["Procedures"] = procedures
        if stat_info is not None:
            completed["StatInfo"] = stat_info
        completed["ExtraInfo"] = {"ReplyMethod": 18, "IsLlmGenerated": True}
        events.append({"Type": "response.completed", "Response": completed})
        return events

    def test_review_text_parses_reply_and_activity(self):
        reply = '{"ruling":"refund","refund_cents":500,"confidence":0.9,' \
                '"rationale":"x","rider_message":"x","driver_message":"x"}'
        events = self._make_stream(reply, agent_name="Judge Agent",
                                   procedures=[{"Type": "agent", "Name": "tool_call"}],
                                   stat_info={"TotalTokens": 100})
        text, activity = review_text(events)
        obj = parse_json_reply(text)
        self.assertEqual(obj["ruling"], "refund")
        self.assertTrue(len(activity) > 0)
        # Should capture message_added, message_done, procedure, stat_info, response_completed
        event_types = [a["event"] for a in activity]
        self.assertIn("message_added", event_types)
        self.assertIn("message_done", event_types)
        self.assertIn("procedure", event_types)
        self.assertIn("stat_info", event_types)
        self.assertIn("response_completed", event_types)

    def test_review_text_rejects_error_event(self):
        events = [{"Type": "error", "Error": {
            "Code": 4505004, "Message": "APPKEY is invalid."}}]
        with self.assertRaises(ADPError) as ctx:
            review_text(events)
        self.assertIn("AppKey", str(ctx.exception))

    def test_review_text_rejects_auth_error_code(self):
        events = [{"Type": "error", "Error": {
            "Code": 460001, "Message": "Token validation failed."}}]
        with self.assertRaises(ADPError) as ctx:
            review_text(events)
        self.assertIn("AppKey", str(ctx.exception))

    def test_review_text_rejects_quota_error_code(self):
        events = [{"Type": "error", "Error": {
            "Code": 460032, "Message": "Insufficient balance."}}]
        with self.assertRaises(ADPError) as ctx:
            review_text(events)
        self.assertIn("quota", str(ctx.exception).lower())

    def test_review_text_rejects_timeout_error_code(self):
        events = [{"Type": "error", "Error": {
            "Code": 460020, "Message": "Model request timeout."}}]
        with self.assertRaises(ADPError) as ctx:
            review_text(events)
        self.assertIn("timed out", str(ctx.exception).lower())

    def test_review_text_rejects_incomplete_stream(self):
        events = [
            {"Type": "message.added", "Message": {"MessageId": "r", "Type": "reply"}},
            {"Type": "text.delta", "MessageId": "r", "Text": "partial"},
        ]
        with self.assertRaises(ADPError):
            review_text(events)

    def test_review_text_rejects_failed_completion_status(self):
        events = [{"Type": "response.completed", "Response": {"Status": "failed"}}]
        with self.assertRaises(ADPError):
            review_text(events)

    def test_review_text_tracks_separate_messages_by_message_id(self):
        """Two reply messages with different MessageIds — only the LAST reply
        should be returned as the final text (Judge's ruling), not both."""
        events = [
            {"Type": "message.added", "Message": {"MessageId": "rpl_a", "Type": "reply"}},
            {"Type": "text.delta", "MessageId": "rpl_a", "Text": '{"first":"yes"}'},
            {"Type": "message.done", "MessageId": "rpl_a", "Message": {
                "Type": "reply", "Status": "success",
                "Contents": [{"Type": "text", "Text": '{"first":"yes"}'}]}},
            {"Type": "message.added", "Message": {"MessageId": "rpl_b", "Type": "reply"}},
            {"Type": "text.replace", "MessageId": "rpl_b", "Text": '{"second":"no"}'},
            {"Type": "message.done", "MessageId": "rpl_b", "Message": {
                "Type": "reply", "Status": "success",
                "Contents": [{"Type": "text", "Text": '{"second":"no"}'}]}},
            {"Type": "response.completed", "Response": {"Status": "success", "Messages": [
                {"Type": "reply", "MessageId": "rpl_a",
                 "Contents": [{"Type": "text", "Text": '{"first":"yes"}'}]},
                {"Type": "reply", "MessageId": "rpl_b",
                 "Contents": [{"Type": "text", "Text": '{"second":"no"}'}]}]}},
        ]
        text, activity = review_text(events)
        # Only the last reply should be returned, not both
        self.assertNotIn('"first"', text)
        self.assertIn('"second"', text)

    def test_classify_error_handles_unknown_code(self):
        self.assertIn("service error", _classify_error(999999))
        self.assertIn("service error", _classify_error("not-a-code"))

    def test_collect_activity_captures_agent_metadata(self):
        events = [
            {"Type": "request_ack", "RequestAck": {"Status": "success",
             "ConversationId": "c1"}},
            {"Type": "response.created", "Response": {"Status": "processing",
             "ExtraInfo": {"AgentName": "Judge Agent"}}},
            {"Type": "message.added", "Message": {"Type": "reply", "Status": "processing",
             "ExtraInfo": {"AgentName": "Judge Agent"}}},
        ]
        activity = collect_activity(events)
        types = [a["event"] for a in activity]
        self.assertIn("request_ack", types)
        self.assertIn("response_created", types)
        self.assertIn("message_added", types)
        # Agent name should be captured
        added = next(a for a in activity if a["event"] == "message_added")
        self.assertEqual(added["detail"]["agent"], "Judge Agent")


class MultiAgentClientTests(unittest.TestCase):
    """Test ADPClient construction and the review() method with a mock."""

    def test_client_rejects_missing_key(self):
        with self.assertRaises(ADPError):
            ADPClient({})

    def test_client_rejects_foreign_endpoint(self):
        with self.assertRaises(ADPError):
            ADPClient({"ADP_APP_KEY": "test-only", "ADP_ENDPOINT": "https://evil.com/chat"})

    def test_client_accepts_valid_config(self):
        client = ADPClient({"ADP_APP_KEY": "test-only-1234567890123456789012"})
        self.assertEqual(client.endpoint, "https://wss.lke.tencentcloud.com/adp/v2/chat")
        self.assertEqual(client.timeout, 45)

    def test_client_timeout_range_enforced(self):
        with self.assertRaises(ADPError):
            ADPClient({"ADP_APP_KEY": "test-only", "ADP_TIMEOUT_SECONDS": "1"})
        with self.assertRaises(ADPError):
            ADPClient({"ADP_APP_KEY": "test-only", "ADP_TIMEOUT_SECONDS": "200"})

    def test_review_builds_correct_request_body(self):
        """Verify review() does not send SystemRole or ModelName."""
        captured = {}

        class MockClient(ADPClient):
            def __init__(self):
                super().__init__({"ADP_APP_KEY": "test-only-1234567890123456789012"})
                self._mock_events = None

            def _post(self, body):
                captured["body"] = body
                # Return a minimal valid SSE stream
                reply = ('{"ruling":"no_action","refund_cents":0,"confidence":0.9,'
                         '"rationale":"x","rider_message":"x","driver_message":"x"}')
                return [
                    {"Type": "message.added", "Message": {"MessageId": "rpl_1", "Type": "reply"}},
                    {"Type": "text.delta", "MessageId": "rpl_1", "Text": reply},
                    {"Type": "message.done", "MessageId": "rpl_1", "Message": {
                        "Type": "reply", "Status": "success",
                        "Contents": [{"Type": "text", "Text": reply}]}},
                    {"Type": "response.completed", "Response": {"Status": "success", "Messages": [
                        {"Type": "reply", "MessageId": "rpl_1",
                         "Contents": [{"Type": "text", "Text": reply}]}]}},
                ]

        client = MockClient()
        obj, activity, debug_info = client.review(
            "NS01", "Driver was late", "conv-12345678901234567890123456789012",
            evidence_ids=["NS01:get_trip"], policy_ids=["DEMO-NOSHOW-01"])
        body = captured["body"]
        # Must NOT contain SystemRole or ModelName
        self.assertNotIn("SystemRole", body)
        self.assertNotIn("ModelName", body)
        # Must contain required fields
        self.assertIn("RequestId", body)
        self.assertIn("ConversationId", body)
        self.assertIn("AppKey", body)
        self.assertIn("VisitorId", body)
        self.assertIn("Contents", body)
        self.assertEqual(body["Stream"], "enable")
        self.assertTrue(body["Incremental"])
        # Contents should contain case_id and complaint
        contents_text = body["Contents"][0]["Text"]
        payload = json.loads(contents_text)
        self.assertEqual(payload["case_id"], "NS01")
        self.assertIn("complaint", payload)
        # Contents should include the English-output instruction
        self.assertEqual(payload["output_language"], "English")
        self.assertIn("JSON object matching the saved Judge schema", payload["output_instruction"])
        # Contents should also include evidence_ids and policy_ids
        self.assertEqual(payload["evidence_ids"], ["NS01:get_trip"])
        self.assertEqual(payload["policy_ids"], ["DEMO-NOSHOW-01"])
        # Should return parsed reply, activity, and debug_info
        self.assertEqual(obj["ruling"], "no_action")
        self.assertTrue(len(activity) > 0)
        self.assertIn("event_types", debug_info)
        self.assertIn("completion_status", debug_info)
        self.assertEqual(debug_info["completion_status"], "success")

    def test_review_returns_debug_info_even_on_parse_error(self):
        """When the Judge returns prose instead of JSON, debug_info must still be available."""
        prose = "After reviewing the evidence, I find the driver was present."

        class MockClient(ADPClient):
            def __init__(self):
                super().__init__({"ADP_APP_KEY": "test-only-1234567890123456789012"})

            def _post(self, body):
                return [
                    {"Type": "message.added", "Message": {"MessageId": "rpl_1", "Type": "reply"}},
                    {"Type": "text.delta", "MessageId": "rpl_1", "Text": prose},
                    {"Type": "message.done", "MessageId": "rpl_1", "Message": {
                        "Type": "reply", "Status": "success",
                        "Contents": [{"Type": "text", "Text": prose}]}},
                    {"Type": "response.completed", "Response": {"Status": "success", "Messages": [
                        {"Type": "reply", "MessageId": "rpl_1",
                         "Contents": [{"Type": "text", "Text": prose}]}]}},
                ]

        client = MockClient()
        with self.assertRaises(ADPError) as ctx:
            client.review("NS01", "Driver was late", "conv-test")
        self.assertTrue(hasattr(ctx.exception, "debug_info"))
        self.assertEqual(ctx.exception.debug_info["final_reply_text"], prose)
        self.assertIn("message.added", ctx.exception.debug_info["event_types"])
        self.assertEqual(ctx.exception.debug_info["completion_status"], "success")

    def test_review_text_selects_last_reply_from_multiple_messages(self):
        """When advocate reports and judge ruling all have Type=reply, only the
        last reply (Judge's ruling) should be returned — not a concatenation."""
        advocate_reply = "The rider has a strong case for a refund."
        judge_reply = ('{"ruling":"refund","refund_cents":500,"confidence":0.9,'
                       '"rationale":"x","rider_message":"x","driver_message":"x"}')
        events = [
            # Rider Advocate reply
            {"Type": "message.added", "Message": {"MessageId": "rpl_adv1", "Type": "reply"}},
            {"Type": "text.delta", "MessageId": "rpl_adv1", "Text": advocate_reply},
            {"Type": "message.done", "MessageId": "rpl_adv1", "Message": {
                "Type": "reply", "Status": "success",
                "Contents": [{"Type": "text", "Text": advocate_reply}]}},
            # Driver Advocate reply
            {"Type": "message.added", "Message": {"MessageId": "rpl_adv2", "Type": "reply"}},
            {"Type": "text.delta", "MessageId": "rpl_adv2", "Text": "The driver was present."},
            {"Type": "message.done", "MessageId": "rpl_adv2", "Message": {
                "Type": "reply", "Status": "success",
                "Contents": [{"Type": "text", "Text": "The driver was present."}]}},
            # Judge final ruling
            {"Type": "message.added", "Message": {"MessageId": "rpl_judge", "Type": "reply"}},
            {"Type": "text.delta", "MessageId": "rpl_judge", "Text": judge_reply},
            {"Type": "message.done", "MessageId": "rpl_judge", "Message": {
                "Type": "reply", "Status": "success",
                "Contents": [{"Type": "text", "Text": judge_reply}]}},
            {"Type": "response.completed", "Response": {"Status": "success", "Messages": [
                {"Type": "reply", "MessageId": "rpl_adv1",
                 "Contents": [{"Type": "text", "Text": advocate_reply}]},
                {"Type": "reply", "MessageId": "rpl_adv2",
                 "Contents": [{"Type": "text", "Text": "The driver was present."}]},
                {"Type": "reply", "MessageId": "rpl_judge",
                 "Contents": [{"Type": "text", "Text": judge_reply}]}]}},
        ]
        text, activity = review_text(events)
        obj = parse_json_reply(text)
        self.assertEqual(obj["ruling"], "refund")
        self.assertNotIn("strong case", text)

    def test_review_text_with_text_replace_on_last_message(self):
        """text.replace on the final reply should produce the correct JSON."""
        events = [
            {"Type": "message.added", "Message": {"MessageId": "rpl_1", "Type": "reply"}},
            {"Type": "text.delta", "MessageId": "rpl_1", "Text": "old text"},
            {"Type": "text.replace", "MessageId": "rpl_1", "Text": '{"ruling":"no_action"}'},
            {"Type": "message.done", "MessageId": "rpl_1", "Message": {
                "Type": "reply", "Status": "success",
                "Contents": [{"Type": "text", "Text": '{"ruling":"no_action"}'}]}},
            {"Type": "response.completed", "Response": {"Status": "success", "Messages": [
                {"Type": "reply", "MessageId": "rpl_1",
                 "Contents": [{"Type": "text", "Text": '{"ruling":"no_action"}'}]}]}},
        ]
        text, activity = review_text(events)
        self.assertEqual(parse_json_reply(text), {"ruling": "no_action"})

    def test_review_text_rt01_three_advocate_and_judge_replies(self):
        """Simulate the RT01 multi-agent flow: Rider Advocate, Driver Advocate,
        and Judge all produce reply messages. Only the Judge (last) reply should
        be returned, and it must be valid JSON matching the schema."""
        rider_advocate = ("The rider's complaint about an unapproved detour is "
                          "supported by the route deviation metrics.")
        driver_advocate = ("The driver took a longer route; however, there is no "
                           "evidence of approval or operational justification.")
        judge_ruling = (
            '{"ruling":"refund","refund_cents":500,"confidence":0.9,'
            '"rationale":"Unapproved route deviation with excess fare.",'
            '"evidence_ids":["RT01:get_trip","RT01:get_metrics"],'
            '"policy_ids":["DEMO-ROUTE-01"],'
            '"rider_message":"Your refund is approved.",'
            '"driver_message":"The detour was not approved."}'
        )
        events = [
            # Rider Advocate reply
            {"Type": "message.added", "Message": {"MessageId": "rpl_ra", "Type": "reply"}},
            {"Type": "text.delta", "MessageId": "rpl_ra", "Text": rider_advocate},
            {"Type": "message.done", "MessageId": "rpl_ra", "Message": {
                "Type": "reply", "Status": "success",
                "Contents": [{"Type": "text", "Text": rider_advocate}]}},
            # Driver Advocate reply
            {"Type": "message.added", "Message": {"MessageId": "rpl_da", "Type": "reply"}},
            {"Type": "text.delta", "MessageId": "rpl_da", "Text": driver_advocate},
            {"Type": "message.done", "MessageId": "rpl_da", "Message": {
                "Type": "reply", "Status": "success",
                "Contents": [{"Type": "text", "Text": driver_advocate}]}},
            # Judge final ruling
            {"Type": "message.added", "Message": {"MessageId": "rpl_j", "Type": "reply"}},
            {"Type": "text.delta", "MessageId": "rpl_j", "Text": judge_ruling},
            {"Type": "message.done", "MessageId": "rpl_j", "Message": {
                "Type": "reply", "Status": "success",
                "Contents": [{"Type": "text", "Text": judge_ruling}]}},
            {"Type": "response.completed", "Response": {"Status": "success", "Messages": [
                {"Type": "reply", "MessageId": "rpl_ra",
                 "Contents": [{"Type": "text", "Text": rider_advocate}]},
                {"Type": "reply", "MessageId": "rpl_da",
                 "Contents": [{"Type": "text", "Text": driver_advocate}]},
                {"Type": "reply", "MessageId": "rpl_j",
                 "Contents": [{"Type": "text", "Text": judge_ruling}]}]}},
        ]
        text, activity = review_text(events)
        obj = parse_json_reply(text)
        self.assertEqual(obj["ruling"], "refund")
        self.assertEqual(obj["refund_cents"], 500)
        self.assertNotIn("rider's complaint", text)
        self.assertNotIn("driver took a longer route", text)

    def test_review_text_judge_prose_wrapping_json(self):
        """When the Judge wraps JSON in prose, parse_json_reply should extract it."""
        judge_text = (
            'After reviewing both advocates, here is my ruling:\n'
            '{"ruling":"no_action","refund_cents":0,"confidence":0.85,'
            '"rationale":"No refund needed.","rider_message":"ok","driver_message":"ok"}\n'
            'This concludes the review.'
        )
        events = [
            {"Type": "message.added", "Message": {"MessageId": "rpl_1", "Type": "reply"}},
            {"Type": "text.delta", "MessageId": "rpl_1", "Text": judge_text},
            {"Type": "message.done", "MessageId": "rpl_1", "Message": {
                "Type": "reply", "Status": "success",
                "Contents": [{"Type": "text", "Text": judge_text}]}},
            {"Type": "response.completed", "Response": {"Status": "success", "Messages": [
                {"Type": "reply", "MessageId": "rpl_1",
                 "Contents": [{"Type": "text", "Text": judge_text}]}]}},
        ]
        text, activity = review_text(events)
        obj = parse_json_reply(text)
        self.assertEqual(obj["ruling"], "no_action")
        self.assertEqual(obj["refund_cents"], 0)

    def test_review_text_delta_chunks_assembled_per_message_id(self):
        """text.delta events for different MessageIds must be tracked separately."""
        events = [
            {"Type": "message.added", "Message": {"MessageId": "rpl_a", "Type": "reply"}},
            {"Type": "text.delta", "MessageId": "rpl_a", "Text": '{"ruling":'},
            {"Type": "text.delta", "MessageId": "rpl_a", "Text": '"refund"}'},
            {"Type": "message.done", "MessageId": "rpl_a", "Message": {
                "Type": "reply", "Status": "success",
                "Contents": [{"Type": "text", "Text": '{"ruling":"refund"}'}]}},
            {"Type": "message.added", "Message": {"MessageId": "rpl_b", "Type": "reply"}},
            {"Type": "text.delta", "MessageId": "rpl_b", "Text": '{"ruling":'},
            {"Type": "text.delta", "MessageId": "rpl_b", "Text": '"no_action"}'},
            {"Type": "message.done", "MessageId": "rpl_b", "Message": {
                "Type": "reply", "Status": "success",
                "Contents": [{"Type": "text", "Text": '{"ruling":"no_action"}'}]}},
            {"Type": "response.completed", "Response": {"Status": "success", "Messages": [
                {"Type": "reply", "MessageId": "rpl_a",
                 "Contents": [{"Type": "text", "Text": '{"ruling":"refund"}'}]},
                {"Type": "reply", "MessageId": "rpl_b",
                 "Contents": [{"Type": "text", "Text": '{"ruling":"no_action"}'}]}]}},
        ]
        text, activity = review_text(events)
        obj = parse_json_reply(text)
        self.assertEqual(obj["ruling"], "no_action")


if __name__ == "__main__":
    unittest.main()
