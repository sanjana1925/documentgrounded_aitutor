"""Dashboard / evaluation / quiz-reset endpoints."""
import logging

from fastapi import APIRouter, Depends, HTTPException

from backend.api.security import require_benchmark_password
from backend.budget import Budget
from backend.container import Container, get_container
from backend.evaluation.report import load_report
from backend.guardrails.input import validate_request_identity
from backend.services.retrieval_service import Scope

router = APIRouter()
logger = logging.getLogger("tutor.api")


def _scope(session_id: str, filename: str) -> Scope:
    ok, err = validate_request_identity(session_id, filename)
    if not ok:
        raise HTTPException(status_code=400, detail=err)
    return Scope(session_id, filename)


@router.get("/dashboard")
def get_dashboard(session_id: str = "default", filename: str = "", c: Container = Depends(get_container)):
    state = c.learner.get(_scope(session_id, filename))
    if state.total_attempted == 0:
        return {
            "status": "no_data",
            "message": "Not enough data yet. Complete an adaptive quiz to view performance metrics.",
            "overall_accuracy": 0.0,
            "total_attempted": 0,
            "total_correct": 0,
            "current_phase": state.current_phase,
        }
    return {
        "status": "ok",
        "overall_accuracy": round(state.get_overall_accuracy(), 1),
        "total_attempted": state.total_attempted,
        "total_correct": state.total_correct,
        "current_phase": state.current_phase,
        "simple_accuracy": round(state.get_simple_accuracy(), 1),
        "medium_accuracy": round(state.get_medium_accuracy(), 1),
        "high_accuracy": round(state.get_high_accuracy(), 1),
        "weak_topics": state.get_weak_topics(),
        "strong_topics": state.get_strong_topics(),
        "topic_stats": {k: v.model_dump() for k, v in state.topic_stats.items()},
    }


@router.get("/evaluation", dependencies=[Depends(require_benchmark_password)])
def get_evaluation():
    return load_report()


@router.post("/quiz/reset")
def reset_quiz(session_id: str = "default", filename: str = "", c: Container = Depends(get_container)):
    scope = _scope(session_id, filename)
    c.learner.reset(scope)
    return {"status": "reset", "session_id": session_id, "filename": filename}
