"""
LangGraph nodes. Node KEYS are the agent names (supervisor_agent, retrieval_agent, ...). Nodes are thin:
each calls one agent, records a trace event, and returns a partial state update. All routing/limit decisions live in workflow.py.
"""
import functools
import logging
from typing import Any, Callable, Dict, List

from langchain_core.runnables import RunnableConfig

from backend.budget import Budget, BudgetExceeded
from backend.graph.state import Deps, GraphState
from backend.guardrails.output import validate_answer
from backend.guardrails.retrieval import get_grounding_fallback
from backend.services.llm_service import LLMError
from backend.services.retrieval_service import Scope
from backend.tools.base import ToolContext

logger = logging.getLogger("tutor.graph")

TIME_MESSAGE = "I ran out of time before I could verify an answer. Please try again, or ask a narrower question."
CLARIFY_DEFAULT = "Could you tell me a bit more about what you'd like to know about your document?"
REJECT_MESSAGE = "I can only help with questions about your uploaded document, and quizzes."
FINISH_MESSAGE = "I'm here whenever you want to ask about your document, or take a quiz."


def scope_of(state: GraphState) -> Scope:
    return Scope(state["session_id"], state["document_id"])


def budget_of(config: RunnableConfig) -> Budget:
    return config["configurable"]["budget"]


def guarded(name: str) -> Callable:
    """A failing agent becomes an observable, bounded outcome (safe fallback), never an unhandled crash."""

    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(state: GraphState, config: RunnableConfig) -> Dict[str, Any]:
            try:
                result = fn(state, config)
                return result
            except BudgetExceeded as exc:
                return {"stop_reason": exc.reason, "trace": [{"step": name, "error": exc.reason}]}
            except LLMError as exc:
                return {
                    "stop_reason": "llm_error",
                    "llm_error": {"status": exc.status_code, "detail": exc.detail},
                    "trace": [{"step": name, "error": f"llm_error:{exc.status_code}"}],
                }
            except Exception as exc:  # noqa: BLE001
                logger.exception("node %s failed", name)
                return {"stop_reason": "internal_error", "trace": [{"step": name, "error": type(exc).__name__}]}

        return wrapper

    return deco


def build_nodes(deps: Deps) -> Dict[str, Callable]:
    @guarded("supervisor_agent")
    def supervisor_agent(state: GraphState, config: RunnableConfig) -> Dict[str, Any]:
        budget = budget_of(config)
        decision, source = deps.supervisor.decide(
            message=state["message"],
            history=state.get("history", []),
            mode_override=state.get("mode_override", ""),
            quiz_pending=state.get("quiz_pending", False),
            budget=budget,
            summary=state.get("conversation_summary", ""),
        )
        return {
            "decision": decision.model_dump(),
            "standalone_query": decision.standalone_query[:1000],
            "mode": decision.intent,
            "trace": [{"step": "supervisor_agent", "source": source, **decision.model_dump()}],
        }

    @guarded("retrieval_agent")
    def retrieval_agent(state: GraphState, config: RunnableConfig) -> Dict[str, Any]:
        budget = budget_of(config)
        return deps.retrieval_agent.step(
            scope=scope_of(state),
            budget=budget,
            question=state["standalone_query"],
            evidence=state.get("evidence", []),
            tried=state.get("tried", []),
            last_eval=state.get("last_eval"),
        )

    @guarded("evidence_evaluator")
    def evidence_evaluator(state: GraphState, config: RunnableConfig) -> Dict[str, Any]:
        budget = budget_of(config)
        evaluation, source = deps.evaluator.evaluate(question=state["standalone_query"], evidence=state.get("evidence", []), budget=budget)
        return {
            "last_eval": evaluation.model_dump(),
            "trace": [{"step": "evidence_evaluator", "source": source, **evaluation.model_dump()}],
        }

    @guarded("tutor_agent")
    def tutor_agent(state: GraphState, config: RunnableConfig) -> Dict[str, Any]:
        budget = budget_of(config)
        decision = state.get("decision", {})
        evidence = state.get("evidence", [])
        out = deps.tutor.write(
            question=state["standalone_query"],
            style=decision.get("response_style", "normal"),
            goal=decision.get("goal", "explain_concept"),
            history=state.get("history", []),
            evidence=evidence,
            feedback=state.get("critic_feedback", ""),
            previous_answer=(state.get("draft") or {}).get("answer", ""),
            budget=budget,
            summary=state.get("conversation_summary", ""),
        )
        attempts = state.get("generation_attempts", 0) + 1
        if out is None:
            reason = "llm_call_budget_exceeded" if budget.llm_calls >= budget.max_llm_calls else "tutor_invalid_output"
            return {
                "draft_status": "failed",
                "generation_attempts": attempts,
                "stop_reason": reason,
                "trace": [{"step": "tutor_agent", "status": "failed", "reason": reason}],
            }

        ok, reason = deps.tutor.validate(out, evidence)
        update: Dict[str, Any] = {"draft": out.model_dump(), "generation_attempts": attempts}
        if out.action == "need_more_evidence":
            update["draft_status"] = "need_more_evidence"
            update["last_eval"] = {**(state.get("last_eval") or {}), "missing_information": out.missing_information, "suggested_query": ""}
        elif out.action == "insufficient_evidence":
            update["draft_status"] = "insufficient"
        elif ok:
            update["draft_status"] = "answer"
            update["critic_feedback"] = ""
        else:
            update["critic_feedback"] = reason
            if budget.can_revise():
                budget.revisions += 1
                update["draft_status"] = "invalid"  # a retry has been granted (and charged)
            else:
                update["draft_status"] = "invalid_final"
        update["trace"] = [
            {"step": "tutor_agent", "action": out.action, "status": update["draft_status"], "validation": reason or "ok",
             "style": out.style_used, "used_chunks": out.used_chunk_indices, "revision": budget.revisions}
        ]
        return update

    @guarded("critic_agent")
    def critic_agent(state: GraphState, config: RunnableConfig) -> Dict[str, Any]:
        budget = budget_of(config)
        draft = state["draft"]
        review, source = deps.critic.review(question=state["standalone_query"], evidence=state.get("evidence", []), answer=draft["answer"], budget=budget)
        if review is None:
            # The critic could not run (budget/invalid output). The tutor already cited real chunks and the
            # evidence evaluator approved the evidence, so the draft is accepted - and recorded in the trace events.
            return {"critic_action": "finish", "trace": [{"step": "critic_agent", "source": source, "action": "finish", "reason": "critic unavailable"}]}
        action, reason = deps.critic.decide(review, budget)
        update: Dict[str, Any] = {"critic": review.model_dump(), "critic_action": action}
        if action in ("revise", "retrieve_again"):
            budget.revisions += 1
            update["critic_feedback"] = deps.critic.feedback_text(review)
            if action == "retrieve_again":
                update["last_eval"] = {**(state.get("last_eval") or {}), "missing_information": review.missing_information, "suggested_query": ""}
        update["trace"] = [{"step": "critic_agent", "source": source, "action": action, "reason": reason, **review.model_dump()}]
        return update

    @guarded("output_guardrail")
    def output_guardrail(state: GraphState, config: RunnableConfig) -> Dict[str, Any]:
        draft = state["draft"]
        evidence = state.get("evidence", [])
        allowed = [c["text"] for c in evidence] + [state.get("standalone_query", ""), state.get("message", "")]
        ok, reason = validate_answer(draft["answer"], [c["chunk_index"] for c in evidence], draft.get("used_chunk_indices", []), allowed, deep=True)
        if not ok:
            return {"stop_reason": "output_guardrail_failed", "trace": [{"step": "output_guardrail", "passed": False, "reason": reason}]}
        cited = set(draft.get("used_chunk_indices", []))
        used = [c for c in evidence if c["chunk_index"] in cited] or evidence
        reply = draft["answer"]
        if draft.get("follow_up_question"):
            reply += f"\n\n**Check your understanding:** {draft['follow_up_question']}"
        return {
            "reply": reply,
            "retrieved_chunks": [c["text"] for c in used],
            "source_chunk_ids": [c["chunk_index"] for c in used],
            "trace": [{"step": "output_guardrail", "passed": True}],
        }

    @guarded("guide_agent")
    def guide_agent(state: GraphState, config: RunnableConfig) -> Dict[str, Any]:
        budget = budget_of(config)
        chunks = deps.retrieval.get_texts(scope_of(state))
        if not chunks:
            return {"stop_reason": "document_not_indexed", "trace": [{"step": "guide_agent", "error": "document_not_indexed"}]}
        text, event = deps.guide.synthesize(mode=state["decision"]["intent"], chunks=chunks, budget=budget)
        return {"reply": text, "trace": [event]}

    @guarded("quiz_agent")
    def quiz_agent(state: GraphState, config: RunnableConfig) -> Dict[str, Any]:
        budget = budget_of(config)
        learner = deps.learner.get(scope_of(state))
        result = deps.quiz.take_turn(scope=scope_of(state), message=state["message"], budget=budget)
        return {
            "reply": result["reply"],
            "quiz_details": result["quiz_details"],
            "quiz_score": result["score"],
            "quiz_total": result["total"],
            "trace": [result["event"]],
        }

    def respond_other(state: GraphState, config: RunnableConfig) -> Dict[str, Any]:
        d = state.get("decision", {})
        action = d.get("next_action")
        if action == "reject":
            reply = REJECT_MESSAGE
        elif action == "finish":
            reply = FINISH_MESSAGE
        else:
            reply = d.get("clarifying_question") or CLARIFY_DEFAULT
        return {"reply": reply, "trace": [{"step": "respond_other", "action": action}]}

    def safe_fallback(state: GraphState, config: RunnableConfig) -> Dict[str, Any]:
        budget = budget_of(config)
        reason = state.get("stop_reason") or ("time_budget_exceeded" if budget.expired() else "evidence_not_supported")
        time_related = reason in ("time_budget_exceeded", "llm_call_budget_exceeded", "tool_call_budget_exceeded")
        return {
            "reply": TIME_MESSAGE if time_related else get_grounding_fallback(),
            "retrieved_chunks": [],
            "stop_reason": reason,
            "trace": [{"step": "safe_fallback", "reason": reason}],
        }

    return {
        "supervisor_agent": supervisor_agent,
        "retrieval_agent": retrieval_agent,
        "evidence_evaluator": evidence_evaluator,
        "tutor_agent": tutor_agent,
        "critic_agent": critic_agent,
        "output_guardrail": output_guardrail,
        "guide_agent": guide_agent,
        "quiz_agent": quiz_agent,
        "respond_other": respond_other,
        "safe_fallback": safe_fallback,
    }
