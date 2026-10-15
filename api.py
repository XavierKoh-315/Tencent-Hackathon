"""Read-only FastAPI evidence API for the Ryde dispute prototype.

Run with:
    .\\.venv\\Scripts\\python.exe -m uvicorn api:app --reload --port 8000

All data is synthetic. No credentials, expected outcomes, saved
investigation results, or judge decisions are exposed.
"""
from __future__ import annotations

import copy

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, field_validator

from disputes.core import calculate_metrics, load_cases, load_policy

try:
    import organiser_support as org
    _ORGANISER_IDS = frozenset(org.CASE_IDS)
except Exception:
    _ORGANISER_IDS = frozenset()

app = FastAPI(
    title="Ryde Dispute Evidence API",
    description="Read-only synthetic evidence and demo-policy API. Not production data.",
)

# --- Load cases once at startup for validation ------------------------------

_cases: dict[str, dict] = {c["trip_id"]: c for c in load_cases()}


class CaseRequest(BaseModel):
    """Request body for all evidence endpoints."""
    case_id: str

    @field_validator("case_id")
    @classmethod
    def case_id_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("case_id must be a non-empty string.")
        return v.strip()


def _resolve_case(case_id: str) -> dict:
    """Return a deep copy of the case for the given ID or 404."""
    case = _cases.get(case_id)
    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown case_id '{case_id}'. Available: {sorted(_cases)}",
        )
    return copy.deepcopy(case)


def _is_organiser(case_id: str) -> bool:
    return case_id in _ORGANISER_IDS


def _organiser_response(req: CaseRequest, tool: str) -> dict:
    """Route to organiser_support and adapt the response to the API contract."""
    ev = org.get_evidence(req.case_id, tool)
    return {
        "case_id": ev["case_id"],
        "evidence_id": ev["evidence_ids"][0],
        "synthetic": True,
        "data": ev["data"],
    }


def _base_response(case_id: str, tool: str, data: dict) -> dict:
    """Build a standardised response: case_id, evidence_id, synthetic flag, and data.

    evidence_id uses the format {case_id}:{tool} so agents can cite it in their
    rulings and the backend validator recognises the same ID.
    """
    return {
        "case_id": case_id,
        "evidence_id": f"{case_id}:{tool}",
        "synthetic": True,
        "data": data,
    }


# --- Endpoints --------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "ryde-dispute-evidence-api", "synthetic_only": True}


@app.post("/tools/get_trip")
def get_trip(req: CaseRequest) -> dict:
    if _is_organiser(req.case_id):
        return _organiser_response(req, "get_trip")
    case = _resolve_case(req.case_id)
    return _base_response(req.case_id, "get_trip", {"trip": case["trip"]})


@app.post("/tools/get_messages")
def get_messages(req: CaseRequest) -> dict:
    if _is_organiser(req.case_id):
        return _organiser_response(req, "get_messages")
    case = _resolve_case(req.case_id)
    return _base_response(req.case_id, "get_messages", {"messages": case["messages"]})


@app.post("/tools/get_payment")
def get_payment(req: CaseRequest) -> dict:
    if _is_organiser(req.case_id):
        return _organiser_response(req, "get_payment")
    case = _resolve_case(req.case_id)
    return _base_response(req.case_id, "get_payment", {"payment": case["payment"]})


@app.post("/tools/get_policy")
def get_policy(req: CaseRequest) -> dict:
    if _is_organiser(req.case_id):
        return _organiser_response(req, "get_policy")
    case = _resolve_case(req.case_id)
    policy = load_policy()
    clause_key = "DEMO-ROUTE-01" if case["category"] == "route_deviation" else "DEMO-NOSHOW-01"
    data = {
        "demo_policy": True,
        "version": policy["version"],
        "notice": policy["notice"],
        "parameters": policy["route" if case["category"] == "route_deviation" else "no_show"],
        "clauses": [policy["clauses"][clause_key]],
    }
    return _base_response(req.case_id, "get_policy", data)


@app.post("/tools/get_metrics")
def get_metrics(req: CaseRequest) -> dict:
    if _is_organiser(req.case_id):
        return _organiser_response(req, "get_metrics")
    case = _resolve_case(req.case_id)
    policy = load_policy()
    metrics = calculate_metrics(case, policy)
    return _base_response(req.case_id, "get_metrics", {"metrics": metrics})


@app.post("/tools/get_history")
def get_history(req: CaseRequest) -> dict:
    if _is_organiser(req.case_id):
        return _organiser_response(req, "get_history")
    case = _resolve_case(req.case_id)
    return _base_response(req.case_id, "get_history", {"history": case.get("history", {})})
