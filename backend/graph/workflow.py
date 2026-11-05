"""
The agentic workflow (LangGraph). ROUTING IS DECIDED HERE, IN PYTHON, from the current state and
the agents' structured observations - and every loop-back edge consumes a bounded budget:

  retrieval_agent -> evidence_evaluator -> retrieval_agent   consumes retrieval_attempts
  tutor_agent (need_more_evidence) -> retrieval_agent        consumes retrieval_attempts
  critic_agent (revise / retrieve_again) -> tutor_agent      consumes revisions
  tutor_agent (invalid draft) -> tutor_agent                 consumes revisions

Time is checked on every edge; LangGraph's recursion limit is only a last-resort backstop.
"""
from typing import Dict, List, Optional, Tuple

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from langsmith import traceable

from backend import config as cfg
from backend.agents.critic import CriticAgent
from backend.agents.guide import GuideAgent
from backend.agents.quiz import QuizAgent
from backend.agents.retrieval import EvidenceEvaluator, RetrievalAgent
from backend.agents.supervisor import _MODE_TO_INTENT, SupervisorAgent
from backend.agents.tutor import TutorAgent
from backend.budget import Budget
from backend.graph.nodes import WORKFLOW_OF_INTENT, build_nodes
from backend.graph.state import Deps, GraphState
from backend.observability.langsmith import mark_root, request_metadata
from backend.services.learner_state_service import LearnerStateService
from backend.services.llm_service import LLM
from backend.services.retrieval_service import RetrievalService
from backend.tools import build_registry


def build_deps(llm: LLM, retrieval: RetrievalService, learner: LearnerStateService) -> Deps:
    registry = build_registry(retrieval, lambda scope: learner.get(scope))
    return Deps(
        retrieval=retrieval,
        learner=learner,
        registry=registry,
        supervisor=SupervisorAgent(llm),
        retrieval_agent=RetrievalAgent(llm, registry),
        evaluator=EvidenceEvaluator(llm),
        tutor=TutorAgent(llm),
        critic=CriticAgent(llm),
        quiz=QuizAgent(llm, registry, learner),
        guide=GuideAgent(llm),
    )


def _budget(config: RunnableConfig) -> Budget:
    return config["configurable"]["budget"]


def _stopped(state: GraphState, config: RunnableConfig) -> bool:
    return bool(state.get("stop_reason")) or _budget(config).expired()


def route_after_supervisor(state: GraphState, config: RunnableConfig) -> str:
    if _stopped(state, config):
        return "safe_fallback"
    return {
        "retrieve": "retrieval_agent",
        "summarize": "guide_agent",
        "quiz": "quiz_agent",
    }.get(state["decision"]["next_action"], "respond_other")


def route_after_retrieval(state: GraphState, config: RunnableConfig) -> str:
    if _stopped(state, config):
        return "safe_fallback"
    if state.get("retrieval_exhausted"):
        e = state.get("last_eval") or {}
        return "tutor_agent" if e.get("relevant") and e.get("coverage", 0) >= cfg.MIN_COVERAGE_AT_LIMIT else "safe_fallback"
    return "evidence_evaluator"


def route_after_evidence(state: GraphState, config: RunnableConfig) -> str:
    if _stopped(state, config):
        return "safe_fallback"
    budget = _budget(config)
    e = state["last_eval"]
    action = e["recommended_action"]
    if action == "use_evidence":
        return "tutor_agent"
    if action in ("retrieve_again", "rewrite_query"):
        if budget.can_retrieve():
            return "retrieval_agent"
        # No attempts left: only answer from evidence that is clearly relevant and mostly covers the question.
        return "tutor_agent" if e["relevant"] and e["coverage"] >= cfg.MIN_COVERAGE_AT_LIMIT else "safe_fallback"
    # answer_not_supported: give retrieval one more chance before concluding the document doesn't cover it.
    if budget.retrieval_attempts < 2 and budget.can_retrieve():
        return "retrieval_agent"
    return "safe_fallback"


def route_after_tutor(state: GraphState, config: RunnableConfig) -> str:
    if _stopped(state, config):
        return "safe_fallback"
    status = state.get("draft_status")
    if status == "answer":
        return "critic_agent"
    if status == "need_more_evidence":
        return "retrieval_agent" if _budget(config).can_retrieve() else "safe_fallback"
    if status == "invalid":
        return "tutor_agent"
    return "safe_fallback"  # insufficient / failed / invalid_final


def route_after_critic(state: GraphState, config: RunnableConfig) -> str:
    if _stopped(state, config):
        return "safe_fallback"
    return {
        "finish": "output_guardrail",
        "revise": "tutor_agent",
        "retrieve_again": "retrieval_agent",
    }.get(state.get("critic_action", ""), "safe_fallback")


def route_after_guardrail(state: GraphState, config: RunnableConfig) -> str:
    return "safe_fallback" if state.get("stop_reason") else END


def route_after_terminal(state: GraphState, config: RunnableConfig) -> str:
    return "safe_fallback" if state.get("stop_reason") else END


def build_workflow(deps: Deps):
    nodes = build_nodes(deps)
    g = StateGraph(GraphState)
    for name, fn in nodes.items():
        g.add_node(name, fn)
    g.set_entry_point("supervisor_agent")
    g.add_conditional_edges("supervisor_agent", route_after_supervisor)
    g.add_conditional_edges("retrieval_agent", route_after_retrieval)
    g.add_conditional_edges("evidence_evaluator", route_after_evidence)
    g.add_conditional_edges("tutor_agent", route_after_tutor)
    g.add_conditional_edges("critic_agent", route_after_critic)
    g.add_conditional_edges("output_guardrail", route_after_guardrail)
    for terminal in ("guide_agent", "quiz_agent"):
        g.add_conditional_edges(terminal, route_after_terminal)
    g.add_edge("respond_other", END)
    g.add_edge("safe_fallback", END)
    return g.compile()


def run_request(
    graph,
    *,
    message: str,
    session_id: str,
    document_id: str,
    history: Optional[List[Dict[str, str]]] = None,
    conversation_summary: str = "",
    mode_override: str = "",
    quiz_pending: bool = False,
    budget: Optional[Budget] = None,
) -> Tuple[GraphState, Budget]:
    budget = budget or Budget()
    tags = ["ai-tutor-guide"]
    if mode_override:
        tags.append(f"workflow:{WORKFLOW_OF_INTENT[_MODE_TO_INTENT[mode_override]]}")
    metadata = request_metadata(session_id, document_id, mode_override=mode_override or "auto")
    run_config = {
        "run_name": "agent_workflow",
        "tags": tags,
        "metadata": metadata,
        "recursion_limit": cfg.GRAPH_RECURSION_LIMIT,
        "configurable": {"budget": budget},
    }
    initial: GraphState = {
        "message": message,
        "session_id": session_id,
        "document_id": document_id,
        "history": history or [],
        "conversation_summary": conversation_summary,
        "mode_override": mode_override,
        "quiz_pending": quiz_pending,
        "evidence": [],
        "tried": [],
        "generation_attempts": 0,
        "trace": [],
    }
    @traceable(name="agent_request", run_type="chain")
    def agent_request():
        mark_root()  # lets the Supervisor tag this root run with the intent it decides
        return graph.invoke(initial, config=run_config)

    final = agent_request(langsmith_extra={"tags": tags, "metadata": metadata})
    return final, budget
