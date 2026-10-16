"""Human-review record storage.

Persists reviewer decisions alongside (never overwriting) the original AI
result.  Supports PostgreSQL for durable deployment (e.g. Render) and falls
back to local SQLite for development.

Configuration
-------------
Set the ``DATABASE_URL`` environment variable to a PostgreSQL connection
string, e.g.::

    DATABASE_URL=postgresql://user:pass@host:5432/dbname

On Render, ``DATABASE_URL`` is required. For local development only,
if it is not set, a SQLite file at
``runtime/human_reviews.sqlite3`` is used.  This is fine for local
development but is **ephemeral on Render** — set ``DATABASE_URL`` to a
managed PostgreSQL instance (Render's managed Postgres or an external
provider) for durable storage in production.

No credentials are committed.  The connection string is read only from
the environment at runtime.

Schema
------
Human reviews are stored in their own table, separate from the AI result
table.  The original AI result JSON is preserved unchanged inside the
review record.  Later corrections create a new row with a ``linked_review_id``
pointing back to the original; the original row is never edited.
"""

from __future__ import annotations

import json
import os
import math
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent

_SCHEMA_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS human_reviews (
    review_id          TEXT PRIMARY KEY,
    case_id            TEXT NOT NULL,
    run_id             TEXT NOT NULL,
    ai_result_json     TEXT NOT NULL,
    original_confidence REAL,
    escalation_reason  TEXT,
    reviewer_id        TEXT NOT NULL,
    human_decision     TEXT NOT NULL,
    refund_cents        INTEGER NOT NULL,
    rider_message      TEXT NOT NULL,
    driver_message     TEXT NOT NULL,
    final_explanation  TEXT NOT NULL,
    policy_version     TEXT NOT NULL,
    linked_review_id   TEXT,
    created_at         TEXT NOT NULL
)""",
    "CREATE INDEX IF NOT EXISTS idx_hr_case_run ON human_reviews(case_id, run_id)",
    "CREATE INDEX IF NOT EXISTS idx_hr_case    ON human_reviews(case_id)",
]


def _get_connection():
    """Return a DB-API 2.0 connection.

    Uses PostgreSQL when ``DATABASE_URL`` is set, otherwise local SQLite.
    """
    db_url = os.environ.get("DATABASE_URL", "").strip()
    if db_url:
        try:
            import psycopg2  # type: ignore
        except ImportError:
            raise RuntimeError(
                "DATABASE_URL is set but psycopg2 is not installed. "
                "Add 'psycopg2-binary' to requirements.txt for PostgreSQL support."
            )
        conn = psycopg2.connect(db_url, connect_timeout=8)
        conn.autocommit = False
        return conn
    if os.environ.get("RENDER_SERVICE_ID") or os.environ.get("RENDER", "").lower() == "true":
        raise RuntimeError("Human-review storage needs DATABASE_URL on Render. Configure PostgreSQL on the Streamlit service.")
    # Local SQLite fallback for development.
    local = ROOT / "runtime" / "human_reviews.sqlite3"
    local.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(local))
    return conn


def _is_postgres(conn) -> bool:
    return conn.__class__.__module__.startswith("psycopg")


def _ph(conn) -> str:
    """Return the parameter placeholder for the connection's DB driver."""
    return "%s" if _is_postgres(conn) else "?"


def _initialise(conn):
    """Create tables if they don't exist."""
    cur = conn.cursor()
    for stmt in _SCHEMA_STATEMENTS:
        cur.execute(stmt)
    conn.commit()
    cur.close()


def _to_cents(amount_str: str | None) -> int | None:
    """Convert a decimal string to integer cents using Decimal.

    Returns None if the input is empty.
    Raises ValueError for invalid format or more than 2 decimal places.
    """
    if not amount_str or not amount_str.strip():
        return None
    raw = amount_str.strip()
    if len(raw) > 20 or not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", raw):
        raise ValueError("Refund amount must be a finite positive decimal with at most two decimal places.")
    cents = int(Decimal(raw) * 100)
    if cents <= 0:
        raise ValueError("Refund amount must be positive.")
    return cents



def charged_cents_for(result: dict) -> int | None:
    """Read the verified payment record, preserving zero and unknown amounts."""
    payments = [e.get("data", {}) for e in result.get("evidence", [])
                if isinstance(e, dict) and e.get("tool") == "get_payment"]
    payment = payments[0] if payments else result.get("payment", {})
    value = payment.get("charged_cents") if isinstance(payment, dict) else None
    if not payments and value is None:
        value = result.get("charged_cents")
    return value if type(value) is int and value >= 0 else None


def model_confidence_for(result: dict):
    ruling = result.get("ruling", {})
    original = result.get("original_ai_ruling", {})
    value = original.get("confidence", ruling.get("original_confidence", ruling.get("confidence")))
    return value if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1 else None

def save_review(
    *,
    case_id: str,
    run_id: str,
    ai_result: dict,
    original_confidence: float | None,
    escalation_reason: str | None,
    reviewer_id: str,
    human_decision: str,
    refund_amount_str: str | None,
    rider_message: str,
    driver_message: str,
    final_explanation: str,
    policy_version: str,
    linked_review_id: str | None = None,
    submission_id: str | None = None,
) -> dict:
    """Persist a human-review record.

    Returns the saved record dict (including server-generated review_id and
    timestamp).

    Raises ValueError on validation failure.
    Raises RuntimeError on storage failure.
    """
    # --- Validation (mirrors the UI validation; defence in depth) --------
    reviewer_id = (reviewer_id or "").strip()
    if not reviewer_id:
        raise ValueError("Reviewer name is required.")

    human_decision = (human_decision or "").strip()
    if human_decision not in {"refund", "no_action", "further_review"}:
        raise ValueError("Human decision must be refund, no_action, or further_review.")

    rider_message = (rider_message or "").strip()
    driver_message = (driver_message or "").strip()
    final_explanation = (final_explanation or "").strip()
    if not rider_message:
        raise ValueError("Rider message is required.")
    if not driver_message:
        raise ValueError("Driver message is required.")
    if not final_explanation:
        raise ValueError("Final decision explanation is required.")

    # Refund logic: only "refund" may carry a positive amount.
    if human_decision == "refund":
        refund_cents = _to_cents(refund_amount_str)
        if refund_cents is None:
            raise ValueError("Refund amount is required for a refund decision.")
        charged_cents = charged_cents_for(ai_result)
        if charged_cents is None:
            raise ValueError(
                "The charged amount is unknown; cannot accept a final refund amount."
            )
        if refund_cents > int(charged_cents):
            raise ValueError(
                f"Refund cannot exceed the charged amount "
                f"(S${int(charged_cents) / 100:.2f})."
            )
    else:
        refund_cents = 0
        # No refund award for non-refund decisions.
        if refund_amount_str and refund_amount_str.strip():
            raise ValueError(
                "No action and further review must not contain a refund award."
            )

    if not case_id or not run_id:
        raise ValueError("Case and investigation IDs are required.")
    if ai_result.get("trip_id") != case_id or ai_result.get("run_id") != run_id:
        raise ValueError("The original AI result must match this case and investigation.")
    if ai_result.get("ruling", {}).get("ruling") != "human_review":
        raise ValueError("Only a valid human-review recommendation can be reviewed here.")
    if ai_result.get("policy_version") != policy_version:
        raise ValueError("The policy version must match the investigation.")
    # Validate the audit snapshot before opening a transaction.
    snapshot = json.dumps(ai_result, allow_nan=False)
    original_confidence = model_confidence_for(ai_result)
    if submission_id:
        try:
            review_id = str(uuid.UUID(submission_id))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("Invalid review submission identifier.")
    else:
        review_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    record = {
        "review_id": review_id,
        "case_id": case_id,
        "run_id": run_id,
        "ai_result": json.loads(snapshot),
        "original_confidence": original_confidence,
        "escalation_reason": escalation_reason,
        "reviewer_id": reviewer_id,
        "human_decision": human_decision,
        "refund_cents": refund_cents,
        "rider_message": rider_message,
        "driver_message": driver_message,
        "final_explanation": final_explanation,
        "policy_version": policy_version,
        "linked_review_id": linked_review_id,
        "created_at": created_at,
    }

    conn = None
    try:
        conn = _get_connection()
        _initialise(conn)
        cur = conn.cursor()
        p = _ph(conn)
        # Serialize submissions for this run, across processes and browser tabs.
        if _is_postgres(conn):
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))", (case_id, run_id))
        else:
            cur.execute("BEGIN IMMEDIATE")
        cur.execute(f"SELECT * FROM human_reviews WHERE case_id={p} AND run_id={p} ORDER BY created_at DESC LIMIT 1",
                    (case_id, run_id))
        latest = cur.fetchone()
        if latest and latest[0] == review_id:
            existing = _record(latest)
            # A retry of the same submission is idempotent, not a new decision.
            for key in ("reviewer_id", "human_decision", "refund_cents", "rider_message", "driver_message", "final_explanation"):
                if existing[key] != record[key]:
                    raise ValueError("A saved submission cannot be changed. Start a linked review instead.")
            return existing
        if latest and linked_review_id != latest[0]:
            raise ValueError("A duplicate review already exists for this investigation. Reload to see the saved review.")
        if linked_review_id and (not latest or latest[0] != linked_review_id):
            raise ValueError("A correction must link to the latest review for this exact case and investigation.")
        if latest and latest[7] != "further_review":
            raise ValueError("This investigation already has a completed human review.")

        cur.execute(
            f"INSERT INTO human_reviews "
            f"(review_id, case_id, run_id, ai_result_json, original_confidence, "
            f" escalation_reason, reviewer_id, human_decision, refund_cents, "
            f" rider_message, driver_message, final_explanation, policy_version, "
            f" linked_review_id, created_at) "
            f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})",
            (review_id, case_id, run_id, snapshot,
             original_confidence, escalation_reason, reviewer_id,
             human_decision, refund_cents, rider_message, driver_message,
             final_explanation, policy_version, linked_review_id, created_at),
        )
        conn.commit()
        cur.close()
    except ValueError:
        raise
    except Exception as exc:
        raise RuntimeError("Storage failure: the review could not be saved. Check DATABASE_URL and database availability.") from exc
    finally:
        if conn is not None:
            conn.close()

    return record



_FIELDS = ("review_id", "case_id", "run_id", "ai_result", "original_confidence",
           "escalation_reason", "reviewer_id", "human_decision", "refund_cents",
           "rider_message", "driver_message", "final_explanation", "policy_version",
           "linked_review_id", "created_at")


def _record(row) -> dict:
    value = dict(zip(_FIELDS, row))
    value["ai_result"] = json.loads(value["ai_result"])
    return value


def _read(where: str, params: tuple, *, latest=False) -> list[dict]:
    conn = None
    try:
        conn = _get_connection()
        _initialise(conn)
        cur = conn.cursor()
        query = "SELECT * FROM human_reviews WHERE " + where.replace("?", _ph(conn))
        query += " ORDER BY created_at DESC" + (" LIMIT 1" if latest else "")
        cur.execute(query, params)
        rows = cur.fetchall()
        return [_record(row) for row in rows]
    except Exception as exc:
        raise RuntimeError("Human-review records could not be loaded. Check DATABASE_URL and database availability.") from exc
    finally:
        if conn is not None:
            conn.close()


def get_review_for_run(case_id: str, run_id: str) -> dict | None:
    records = _read("case_id=? AND run_id=?", (case_id, run_id), latest=True)
    return records[0] if records else None


def get_review_by_id(review_id: str) -> dict | None:
    records = _read("review_id=?", (review_id,), latest=True)
    return records[0] if records else None


def get_review_history(case_id: str) -> list[dict]:
    return _read("case_id=?", (case_id,))
