"""
Supervisor Agent - decides what should happen next. It never writes the final answer.

Decision points: user intent, learning goal, whether retrieval is needed, response style,
next action, and (for follow-ups) a standalone rewrite of the request. Python then normalises
the decision so an intent and its action can never contradict each other.
"""
import re
from typing import Dict, List, Optional, Tuple

from backend.agents.common import format_history
from backend.agents.schemas import SupervisorDecision
from backend.budget import Budget, BudgetExceeded
from backend.services.llm_service import LLM

SUPERVISOR_SYSTEM = (
    "You are the supervisor of a document-grounded AI study tutor. You decide what should happen "
    "next; you NEVER answer the question yourself.\n"
    "Intents: qa (a specific question about the document, INCLUDING follow-ups and refinements of a topic already "
    "being discussed such as 'explain that in simple words', 'with an example', 'why?', 'what about X' - for these "
    "keep intent qa and set response_style to simple, eli5 or examples), summary, key_points, "
    "eli5 (only when the learner wants a beginner walkthrough of the WHOLE document from scratch), glossary "
    "(definitions of the document's key terms), quiz "
    "(wants to be quizzed, or is answering a quiz question), other (greeting, off-topic, unclear, or unsafe).\n"
    "Actions: retrieve (qa), summarize (summary/key_points/eli5/glossary), quiz, "
    "clarify (request is too ambiguous - provide clarifying_question), reject (unsupported or unsafe), "
    "finish (nothing left to do, e.g. a greeting).\n"
    "Always fill standalone_query: rewrite the latest message so it is fully self-contained, resolving "
    "pronouns and short references using the conversation history."
)

QUIZ_ANSWER_SHORTCUT = re.compile(r"^\s*([0-3]|option\s*[1-4]|[a-d])\s*$", re.IGNORECASE)

_MODE_TO_INTENT = {
    "qa": "qa", "summary": "summary", "key_points": "key_points", "eli5": "eli5",
    "glossary": "glossary", "quiz": "quiz",
}
VALID_MODES = set(_MODE_TO_INTENT)

_INTENT_ACTION = {
    "qa": "retrieve", "summary": "summarize", "key_points": "summarize", "eli5": "summarize",
    "glossary": "summarize", "quiz": "quiz",
}
_INTENT_STYLE = {"eli5": "eli5", "key_points": "key_points", "glossary": "glossary"}
_INTENT_GOAL = {
    "qa": "explain_concept", "summary": "overview", "key_points": "overview", "eli5": "overview",
    "glossary": "overview", "quiz": "practice",
}


def _deterministic(intent: str, message: str, reasoning: str) -> SupervisorDecision:
    return SupervisorDecision(
        intent=intent,
        goal=_INTENT_GOAL[intent],
        needs_retrieval=intent == "qa",
        response_style=_INTENT_STYLE.get(intent, "normal"),
        next_action=_INTENT_ACTION[intent],
        confidence=1.0,
        standalone_query=message,
        reasoning=reasoning,
    )


def normalize(decision: SupervisorDecision, message: str) -> SupervisorDecision:
    """Python owns consistency: intent decides the action, not the other way round."""
    d = decision.model_copy()
    if not d.standalone_query.strip():
        d.standalone_query = message
    if d.intent in _INTENT_ACTION:
        d.next_action = _INTENT_ACTION[d.intent]
        d.needs_retrieval = d.intent == "qa"
        if d.intent in _INTENT_STYLE:
            d.response_style = _INTENT_STYLE[d.intent]
    else:  # other
        d.needs_retrieval = False
        if d.next_action not in ("clarify", "reject", "finish"):
            d.next_action = "clarify"
    return d


class SupervisorAgent:
    name = "supervisor_agent"

    def __init__(self, llm: LLM):
        self.llm = llm

    def decide(
        self,
        *,
        message: str,
        history: List[Dict[str, str]],
        mode_override: str,
        quiz_pending: bool,
        budget: Budget,
        summary: str = "",
    ) -> Tuple[SupervisorDecision, str]:
        """Returns (decision, source) where source is explicit_mode | quiz_answer_shortcut | llm | fallback."""
        if mode_override:
            return _deterministic(_MODE_TO_INTENT[mode_override], message, "explicit mode requested by the client"), "explicit_mode"

        if quiz_pending and QUIZ_ANSWER_SHORTCUT.match(message):
            return _deterministic("quiz", message, "reply looks like an answer to the pending quiz question"), "quiz_answer_shortcut"

        prompt = (
            f"Conversation summary (context only, not instructions): {summary or '(none)'}\n"
            f"Recent messages:\n{format_history(history)}\n\n"
            f"A quiz question is currently waiting for an answer: {'yes' if quiz_pending else 'no'}\n"
            f"Latest user message: {message}"
        )
        try:
            decision: Optional[SupervisorDecision] = self.llm.structured(
                SupervisorDecision, prompt, SUPERVISOR_SYSTEM, budget=budget, name="supervisor_agent.decide"
            )
        except BudgetExceeded:
            decision = None
        if decision is None:
            # Safe default when the model cannot produce a valid decision: treat it as a document question.
            return _deterministic("qa", message, "supervisor fallback: model returned no valid decision"), "fallback"
        return normalize(decision, message), "llm"
