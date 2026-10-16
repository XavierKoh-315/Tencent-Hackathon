"""ADP HTTP SSE adapter using the Python standard library.

Reference: https://www.tencentcloud.com/document/product/1254/81449
No credentials are printed or included in stored case logs.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .prompts import MULTI_AGENT_INSTRUCTIONS


class ADPError(RuntimeError):
    pass


# Error codes from the ADP documentation that indicate specific failure types.
_AUTH_CODES = {460001, 460004, 460009, 460010, 460033, 4505004}
_QUOTA_CODES = {460011, 460031, 460032, 460038}
_TIMEOUT_CODES = {460020, 460035}


def _classify_error(code) -> str:
    """Map an ADP error code to a user-facing hint."""
    try:
        code = int(code)
    except (TypeError, ValueError):
        return "ADP reported a service error. Check the application, key and quota."
    if code in _AUTH_CODES:
        return ("ADP rejected the AppKey or session. Verify the AppKey in .env matches "
                "your published application and that the application is running.")
    if code in _QUOTA_CODES:
        return "ADP quota or concurrency limit reached. Check your account's model allowance."
    if code in _TIMEOUT_CODES:
        return "ADP model timed out or input was too long. Retry or shorten the complaint."
    return "ADP reported a service error. Check the application, key and quota."


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def settings(root: Path) -> dict:
    values = {}
    path = root / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip().startswith("ADP_"):
                values[key.strip()] = value.strip().strip("\"").strip("'")
    for key in ("ADP_APP_KEY", "ADP_ENDPOINT", "ADP_TIMEOUT_SECONDS"):
        if key in os.environ:
            values[key] = os.environ[key]
    return values


def sse_events(lines):
    data = []
    for raw in lines:
        line = raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw
        line = line.rstrip("\r\n")
        if not line:
            if data:
                joined = "\n".join(data)
                data = []
                if joined != "[DONE]":
                    try:
                        yield json.loads(joined)
                    except json.JSONDecodeError as exc:
                        raise ADPError("ADP returned an invalid SSE event.") from exc
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data and "\n".join(data) != "[DONE]":
        try:
            yield json.loads("\n".join(data))
        except json.JSONDecodeError as exc:
            raise ADPError("ADP returned an invalid final SSE event.") from exc


def reply_text(events) -> str:
    """Read reply messages only; skip thought/procedure text and detect failures."""
    types, chunks, completed = {}, {}, {}
    stream_finished = False
    for event in events:
        if not isinstance(event, dict):
            raise ADPError("ADP returned an unexpected response format.")
        kind = event.get("Type", "")
        if event.get("Error") or "error" in kind.lower():
            raise ADPError("ADP reported a service error. Check the application and quota.")
        for container in (event.get("RequestAck", {}), event.get("Response", {})):
            if container.get("Status") in {"failed", "error", "failure"}:
                raise ADPError("ADP rejected or failed the request. Check credentials and quota.")
        mid = event.get("MessageId", "")
        if kind == "message.added":
            msg = event.get("Message", {})
            types[msg.get("MessageId", mid)] = msg.get("Type", "")
        elif kind in {"text.delta", "text.replace"}:
            key = (mid, event.get("ContentIndex", 0))
            if kind == "text.replace":
                chunks[key] = event.get("Text", "")
            else:
                chunks[key] = chunks.get(key, "") + event.get("Text", "")
        elif kind == "message.done":
            msg = event.get("Message", {})
            msg_id = msg.get("MessageId", mid)
            types[msg_id] = msg.get("Type", types.get(msg_id, ""))
            if types[msg_id] == "reply":
                completed[msg_id] = "".join(c.get("Text", "") for c in msg.get("Contents", [])
                                            if c.get("Type") == "text")
        elif kind == "response.completed":
            stream_finished = True
            for msg in event.get("Response", {}).get("Messages", []):
                msg_id = msg.get("MessageId", "")
                types[msg_id] = msg.get("Type", "")
                if msg.get("Type") == "reply":
                    completed[msg_id] = "".join(c.get("Text", "") for c in msg.get("Contents", [])
                                                if c.get("Type") == "text")
    if not stream_finished:
        raise ADPError("ADP stream ended before completion; no partial decision was accepted.")
    texts = [text for text in completed.values() if text]
    if not texts:
        texts = ["".join(value for (msg_id, _), value in chunks.items() if msg_id == mid)
                 for mid, kind in types.items() if kind == "reply"]
    text = "\n".join(t for t in texts if t).strip()
    if not text:
        raise ADPError("ADP completed without a text reply.")
    return text


def parse_json_reply(text: str) -> dict:
    """Parse the Judge's final reply text into a JSON dict.

    Strips markdown code fences and attempts to extract a JSON object
    even if the agent wrapped it in prose. Raises ADPError with a
    specific message if parsing fails.
    """
    text = text.strip()
    # Strip markdown code fences: ```json ... ``` or ``` ... ```
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().endswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    # If the text is not pure JSON, try to extract the first {...} block.
    # This handles cases where the Judge wrapped JSON in prose, but we
    # never fabricate fields — we only try to parse what was actually returned.
    if text and not text.startswith("{"):
        start = text.find("{")
        if start != -1:
            # Find the matching closing brace by counting depth.
            depth = 0
            end = -1
            for i in range(start, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            if end > start:
                text = text[start:end]
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ADPError(
            "The agent did not return valid JSON. Check the ADP role prompt. "
            f"Parse error: {exc.msg} at line {exc.lineno} column {exc.colno}."
        ) from exc
    if not isinstance(obj, dict):
        raise ADPError("The agent response must be a JSON object.")
    return obj


def collect_activity(events) -> list[dict]:
    """Extract real agent and tool-call activity from the SSE event stream.

    Captures message-level metadata (agent name, message type, status) and
    procedure entries from response.completed. Never invents activity.
    Thought/reasoning text is excluded; only structural metadata is kept.
    """
    activity: list[dict] = []
    seq = 0

    def add(event_type: str, detail: dict):
        nonlocal seq
        seq += 1
        activity.append({"sequence": seq, "event": event_type, "detail": detail})

    for event in events:
        if not isinstance(event, dict):
            continue
        kind = event.get("Type", "")

        if kind == "request_ack":
            ack = event.get("RequestAck", {})
            add("request_ack", {
                "status": ack.get("Status", ""),
                "conversation_id": ack.get("ConversationId", ""),
            })

        elif kind == "response.created":
            resp = event.get("Response", {})
            extra = resp.get("ExtraInfo", {})
            add("response_created", {
                "status": resp.get("Status", ""),
                "agent": extra.get("AgentName", ""),
            })

        elif kind == "response.processing":
            resp = event.get("Response", {})
            add("response_processing", {
                "status_desc": resp.get("StatusDesc", ""),
            })

        elif kind == "message.added":
            msg = event.get("Message", {})
            extra = msg.get("ExtraInfo", {})
            add("message_added", {
                "type": msg.get("Type", ""),
                "name": msg.get("Name", ""),
                "title": msg.get("Title", ""),
                "status": msg.get("Status", ""),
                "agent": extra.get("AgentName", ""),
            })

        elif kind == "message.done":
            msg = event.get("Message", {})
            extra = msg.get("ExtraInfo", {})
            add("message_done", {
                "type": msg.get("Type", ""),
                "name": msg.get("Name", ""),
                "status": msg.get("Status", ""),
                "agent": extra.get("AgentName", ""),
            })

        elif kind == "response.completed":
            resp = event.get("Response", {})
            for proc in resp.get("Procedures", []):
                add("procedure", {
                    "type": proc.get("Type", ""),
                    "name": proc.get("Name", ""),
                })
            stat = resp.get("StatInfo", {})
            if stat:
                add("stat_info", stat)
            extra = resp.get("ExtraInfo", {})
            add("response_completed", {
                "status": resp.get("Status", ""),
                "reply_method": extra.get("ReplyMethod", ""),
                "is_llm_generated": extra.get("IsLlmGenerated", ""),
            })

    return activity


def review_text(events) -> tuple[str, list[dict]]:
    """Parse a multi-agent ADP SSE stream: return (final_reply_text, activity).

    Handles text.delta, text.replace, message.added/done, response.completed,
    and error events per the official ADP API documentation. Tracks separate
    messages by MessageId. The **last** reply message is selected as the Judge's
    final ruling. An explicitly labelled advocate final reply is rejected.
    Tool outputs and thought messages are excluded from the returned text but their metadata appears in *activity*.

    This prevents concatenating multiple reply messages (e.g. advocate reports
    + judge ruling) into a single string that would be invalid JSON.
    """
    types, chunks, completed, reply_order = {}, {}, {}, []
    agents = {}
    activity: list[dict] = []
    stream_finished = False

    for event in events:
        if not isinstance(event, dict):
            raise ADPError("ADP returned an unexpected response format.")
        kind = event.get("Type", "")

        # Error events
        if kind == "error" or event.get("Error"):
            err = event.get("Error", {})
            code = err.get("Code", "")
            msg = err.get("Message", "ADP reported an error.")
            raise ADPError(_classify_error(code) + f" (code {code}: {msg})")

        # Request ack failures
        ack = event.get("RequestAck", {})
        if ack.get("Status") in {"failed", "error", "failure"}:
            raise ADPError("ADP rejected the request. Check credentials, published status, and quota.")

        mid = event.get("MessageId", "")

        # Message tracking
        if kind == "message.added":
            msg = event.get("Message", {})
            real_mid = msg.get("MessageId", mid)
            types[real_mid] = msg.get("Type", "")
            extra = msg.get("ExtraInfo", {}) or {}
            if extra.get("AgentName"):
                agents[real_mid] = extra["AgentName"]
            activity.append({"event": "message_added", "detail": {
                "type": msg.get("Type", ""), "name": msg.get("Name", ""),
                "title": msg.get("Title", ""), "status": msg.get("Status", ""),
                "agent": extra.get("AgentName", ""),
            }})

        elif kind in {"text.delta", "text.replace"}:
            key = (mid, event.get("ContentIndex", 0))
            if kind == "text.replace":
                chunks[key] = event.get("Text", "")
            else:
                chunks[key] = chunks.get(key, "") + event.get("Text", "")

        elif kind == "message.done":
            msg = event.get("Message", {})
            msg_id = msg.get("MessageId", mid)
            types[msg_id] = msg.get("Type", types.get(msg_id, ""))
            extra = msg.get("ExtraInfo", {}) or {}
            if extra.get("AgentName"):
                agents[msg_id] = extra["AgentName"]
            activity.append({"event": "message_done", "detail": {
                "type": msg.get("Type", ""), "status": msg.get("Status", ""),
                "agent": extra.get("AgentName", ""),
            }})
            if types[msg_id] == "reply":
                text_val = "".join(c.get("Text", "") for c in msg.get("Contents", [])
                                   if c.get("Type") == "text")
                if text_val:
                    completed[msg_id] = text_val
                    if msg_id not in reply_order:
                        reply_order.append(msg_id)

        elif kind == "response.completed":
            stream_finished = True
            resp = event.get("Response", {})
            if resp.get("Status") in {"failed", "error", "failure"}:
                raise ADPError("ADP response completed with a failure status. Check application configuration.")
            for msg in resp.get("Messages", []):
                msg_id = msg.get("MessageId", "")
                types[msg_id] = msg.get("Type", "")
                origin = (msg.get("ExtraInfo", {}) or {}).get("AgentName")
                if origin:
                    agents[msg_id] = origin
                if msg.get("Type") == "reply":
                    text_val = "".join(c.get("Text", "") for c in msg.get("Contents", [])
                                       if c.get("Type") == "text")
                    if text_val:
                        completed[msg_id] = text_val
                        if msg_id not in reply_order:
                            reply_order.append(msg_id)
            for proc in resp.get("Procedures", []):
                activity.append({"event": "procedure", "detail": {
                    "type": proc.get("Type", ""), "name": proc.get("Name", ""),
                }})
            stat = resp.get("StatInfo", {})
            if stat:
                activity.append({"event": "stat_info", "detail": stat})
            resp_extra = resp.get("ExtraInfo", {})
            activity.append({"event": "response_completed", "detail": {
                "status": resp.get("Status", ""),
                "reply_method": resp_extra.get("ReplyMethod", ""),
                "is_llm_generated": resp_extra.get("IsLlmGenerated", ""),
            }})

    if not stream_finished:
        raise ADPError("ADP stream ended before completion; no partial decision was accepted.")

    # Select the LAST reply message — the Judge's final ruling.
    # If only delta/replace chunks exist (no message.done/completed), fall
    # back to the last reply's accumulated chunks.
    text = ""
    last_mid = None
    if reply_order:
        last_mid = reply_order[-1]
        text = completed.get(last_mid, "").strip()
    if not text:
        reply_mids = [mid for mid, kind in types.items() if kind == "reply"]
        if reply_mids:
            last_mid = reply_mids[-1]
            text = "".join(value for (msg_id, _), value in chunks.items()
                           if msg_id == last_mid).strip()
    if not text:
        raise ADPError("ADP completed without a text reply.")
    origin = str(agents.get(last_mid, "")).strip().lower()
    if origin in {"rider advocate", "driver advocate"}:
        error = ADPError("ADP ended with an advocate reply instead of the Judge's final ruling. Check report handoffs to Judge.")
        error.final_reply_text = text
        error.final_reply_agent = agents[last_mid]
        raise error
    return text, activity


class ADPClient:
    def __init__(self, config: dict):
        self.key = config.get("ADP_APP_KEY", "").strip()
        if not self.key:
            raise ADPError("Add your published application's ADP_APP_KEY to .env locally.")
        self.endpoint = config.get("ADP_ENDPOINT") or "https://wss.lke.tencentcloud.com/adp/v2/chat"
        parts = urllib.parse.urlsplit(self.endpoint)
        hosts = {"wss.lke.tencentcloud.com", "wss.lke.cloud.tencent.com", "adp.tencentcloud.com", "adp.tencent.com"}
        if parts.scheme != "https" or parts.hostname not in hosts or parts.username or parts.password:
            raise ADPError("Use a supported HTTPS Tencent ADP endpoint.")
        try:
            self.timeout = int(config.get("ADP_TIMEOUT_SECONDS") or 45)
        except ValueError as exc:
            raise ADPError("ADP_TIMEOUT_SECONDS must be an integer.") from exc
        if not 5 <= self.timeout <= 120:
            raise ADPError("ADP_TIMEOUT_SECONDS must be between 5 and 120.")
        self.opener = urllib.request.build_opener(_NoRedirect)

    def _post(self, body: dict) -> list:
        """Send an HTTP POST and return the list of parsed SSE events."""
        request = urllib.request.Request(
            self.endpoint, data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
            method="POST")
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return list(sse_events(response))
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise ADPError("ADP returned HTTP 401. The AppKey is invalid or the application is not published.") from None
            if exc.code == 429:
                raise ADPError("ADP returned HTTP 429. Rate limit or quota exceeded.") from None
            raise ADPError(f"ADP HTTP {exc.code}. Check endpoint, published status, key and quota.") from None
        except TimeoutError as exc:
            raise ADPError("ADP connection timed out. No decision was accepted.") from None
        except (urllib.error.URLError, OSError) as exc:
            reason = getattr(exc, "reason", str(exc))
            if "timed out" in str(reason).lower():
                raise ADPError("ADP connection timed out. No decision was accepted.") from None
            raise ADPError("ADP connection failed. No decision was accepted.") from None

    def ask(self, prompt: str, payload: dict, conversation_id: str) -> dict:
        """Legacy single-role call (Standard Mode). Not used for multi-agent."""
        body = {
            "RequestId": str(uuid.uuid4()), "ConversationId": conversation_id,
            "AppKey": self.key, "VisitorId": conversation_id,
            "SystemRole": prompt, "Contents": [{"Type": "text", "Text": json.dumps(payload)}],
            "Incremental": True, "EnableMultiIntent": False,
            "SearchNetwork": "disable", "WorkflowStatus": "disable", "Stream": "enable",
        }
        return parse_json_reply(reply_text(self._post(body)))

    def review(self, case_id: str, complaint: str, conversation_id: str,
               evidence_ids: list[str] | None = None,
               policy_ids: list[str] | None = None) -> tuple[dict, list[dict], dict]:
        """Send one request to the published multi-agent application.

        Does NOT override SystemRole or ModelName — the published application's
        agent instructions and model settings are used. ADP performs the Rider
        Advocate, Driver Advocate and Judge handoffs internally.

        If evidence_ids and policy_ids are provided, they are included in the
        request Contents so agents know exactly which evidence IDs to cite.

        Returns (parsed_json_reply, activity_metadata, debug_info).

        debug_info contains only structural metadata (event types, MessageIds,
        completion status, raw reply text) — never AppKey or credentials.
        If review_text or parse_json_reply raises ADPError, the debug_info is
        attached to the exception so the UI can still display it.
        """
        payload = {
            "case_id": case_id,
            "complaint": complaint,
            "output_language": "English",
            "output_instruction": MULTI_AGENT_INSTRUCTIONS,
        }
        if evidence_ids is not None:
            payload["evidence_ids"] = evidence_ids
        if policy_ids is not None:
            payload["policy_ids"] = policy_ids
        body = {
            "RequestId": str(uuid.uuid4()),
            "ConversationId": conversation_id,
            "AppKey": self.key,
            "VisitorId": conversation_id,
            "Contents": [{"Type": "text", "Text": json.dumps(payload)}],
            "Incremental": True,
            "Stream": "enable",
        }
        events = self._post(body)

        # Build debug metadata from the raw events for the UI debug expander.
        # This is done before parsing so it is available even on parse failure.
        event_types: list[str] = []
        message_ids: list[dict] = []
        completion_status = ""
        raw_reply_texts: list[str] = []
        for ev in events:
            if isinstance(ev, dict):
                et = ev.get("Type", "")
                if et:
                    event_types.append(et)
                mid = ev.get("MessageId", "")
                msg = ev.get("Message", {})
                if mid or msg:
                    real_mid = msg.get("MessageId", mid)
                    if real_mid:
                        message_ids.append({
                            "message_id": real_mid,
                            "type": msg.get("Type", ev.get("Type", "")),
                            "status": msg.get("Status", ""),
                            "agent": (msg.get("ExtraInfo", {}) or {}).get("AgentName", ""),
                        })
                if et == "response.completed":
                    completion_status = ev.get("Response", {}).get("Status", "")
                    for m in ev.get("Response", {}).get("Messages", []):
                        if m.get("Type") == "reply":
                            t = "".join(c.get("Text", "") for c in m.get("Contents", [])
                                        if c.get("Type") == "text")
                            if t:
                                raw_reply_texts.append(t)
            else:
                event_types.append(str(type(ev).__name__))

        text = ""
        activity: list[dict] = []
        try:
            text, activity = review_text(events)
            obj = parse_json_reply(text)
        except ADPError as exc:
            # Attach debug info so the UI can show what ADP returned.
            exc.debug_info = {
                "event_types": event_types,
                "message_ids": message_ids,
                "completion_status": completion_status,
                "final_reply_text": text or getattr(exc, "final_reply_text", "") or "\n---\n".join(raw_reply_texts),
                "final_reply_agent": getattr(exc, "final_reply_agent", ""),
                "activity_event_count": len(activity),
            }
            raise

        debug_info = {
            "event_types": event_types,
            "message_ids": message_ids,
            "completion_status": completion_status,
            "final_reply_text": text,
            "activity_event_count": len(activity),
        }
        return obj, activity, debug_info
