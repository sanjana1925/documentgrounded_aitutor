"""
LangSmith integration.

Design:
  * LangGraph node keys are the agent names (supervisor_agent, retrieval_agent, ...), so
    LangGraph's own tracing gives every agent a meaningfully named run.
  * Tools and LLM calls are wrapped with `traced(...)` and nest under the node that made them.
  * Tags / metadata are passed at graph-invoke time (inherited by every child run) and
    extended per step with `annotate(...)`.
  * Nothing here can raise into the request path: tracing failures must never break answers.
"""
import hashlib
import logging
import os
from contextvars import ContextVar
from typing import Any, Callable, Dict, Iterable, Optional

from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

logger = logging.getLogger("tutor.observability")

DEFAULT_PROJECT = "ai-tutor-guide"
_SENSITIVE_FRAGMENTS = ("key", "secret", "token", "password", "authorization", "cookie", "credential")
_MAX_VALUE_LEN = 200


def _truthy(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def configure_tracing() -> Dict[str, Any]:
    """
    Normalise LangSmith env vars (current LANGSMITH_* names, with the older LANGCHAIN_* names
    accepted as a fallback) and return a secret-free status dict.
    """
    if _truthy(os.environ.get("TUTOR_DISABLE_TRACING")):  # explicit off switch
        os.environ["LANGSMITH_TRACING"] = "false"
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        return {"enabled": False, "project": None}

    if os.environ.get("LANGSMITH_TRACING") is None and os.environ.get("LANGCHAIN_TRACING_V2") is not None:
        os.environ["LANGSMITH_TRACING"] = os.environ["LANGCHAIN_TRACING_V2"]
    if not os.environ.get("LANGSMITH_API_KEY") and os.environ.get("LANGCHAIN_API_KEY"):
        os.environ["LANGSMITH_API_KEY"] = os.environ["LANGCHAIN_API_KEY"]

    requested = _truthy(os.environ.get("LANGSMITH_TRACING"))
    has_key = bool(os.environ.get("LANGSMITH_API_KEY"))

    if requested and not has_key:
        logger.warning("LANGSMITH_TRACING is on but LANGSMITH_API_KEY is not set; tracing disabled.")
        os.environ["LANGSMITH_TRACING"] = "false"
        requested = False

    if requested and not os.environ.get("LANGSMITH_PROJECT"):
        os.environ["LANGSMITH_PROJECT"] = os.environ.get("LANGCHAIN_PROJECT") or DEFAULT_PROJECT

    return {
        "enabled": requested,
        "project": os.environ.get("LANGSMITH_PROJECT") if requested else None,
    }


def tracing_enabled() -> bool:
    return _truthy(os.environ.get("LANGSMITH_TRACING")) or _truthy(os.environ.get("LANGCHAIN_TRACING_V2"))


def hash_id(value: str) -> str:
    """Stable, non-reversible short id. Session ids double as data-access keys, so raw values are not sent."""
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()[:12]


def sanitize_metadata(metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    clean: Dict[str, Any] = {}
    for key, value in (metadata or {}).items():
        if any(fragment in str(key).lower() for fragment in _SENSITIVE_FRAGMENTS):
            continue
        if isinstance(value, (bool, int, float)) or value is None:
            clean[key] = value
        else:
            clean[key] = str(value)[:_MAX_VALUE_LEN]
    return clean


def request_metadata(session_id: str, document_id: str, **extra: Any) -> Dict[str, Any]:
    return sanitize_metadata({"session_id": hash_id(session_id), "document_id": document_id, **extra})


def traced(name: str, run_type: str = "chain", tags: Optional[Iterable[str]] = None) -> Callable:
    """Decorator giving a function an explicit, meaningful LangSmith run name."""
    return traceable(name=name, run_type=run_type, tags=list(tags or []))


def annotate(metadata: Optional[Dict[str, Any]] = None, tags: Optional[Iterable[str]] = None) -> None:
    """Attach metadata/tags to the current run, if any. Never raises."""
    try:
        run = get_current_run_tree()
        if run is None:
            return
        if metadata:
            run.add_metadata(sanitize_metadata(metadata))
        if tags:
            run.add_tags(list(tags))
    except Exception:  # noqa: BLE001 - observability must not break requests
        logger.debug("annotate failed", exc_info=True)


_ROOT_RUN: ContextVar = ContextVar("tutor_root_run", default=None)


def mark_root() -> None:
    """Remember the current run as the request's root so later steps can annotate it."""
    try:
        _ROOT_RUN.set(get_current_run_tree())
    except Exception:  # noqa: BLE001
        logger.debug("mark_root failed", exc_info=True)


def annotate_root(metadata: Optional[Dict[str, Any]] = None, tags: Optional[Iterable[str]] = None) -> None:
    """Attach metadata/tags to the ROOT run of the current trace (e.g. the intent the Supervisor just chose)."""
    try:
        run = _ROOT_RUN.get()
        if run is None:
            return
        if metadata:
            run.add_metadata(sanitize_metadata(metadata))
        if tags:
            new_tags = [t for t in tags if t not in (getattr(run, "tags", None) or [])]
            if new_tags:
                run.add_tags(new_tags)
    except Exception:  # noqa: BLE001
        logger.debug("annotate_root failed", exc_info=True)
