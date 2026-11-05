"""
Quiz Agent.

LLM decides: the question, options, topic, explanation, a suggested difficulty, and the source quote.
Python decides: everything else - the phase/difficulty, whether the learner's reply is an answer,
scoring, progression, accuracy, duplicate prevention, schema and grounding validation, retries,
persistence, and what the browser may see.
"""
from typing import Any, Dict, List, Optional

from backend import config
from backend.agents.schemas import QuizQuestion
from backend.budget import Budget, BudgetExceeded
from backend.services import quiz_service
from backend.services.learner_state_service import LearnerStateService
from backend.services.llm_service import LLM
from backend.services.retrieval_service import Scope
from backend.tools.base import ToolContext, ToolRegistry
from backend.domain.quiz_engine import build_quiz_prompt

QUIZ_SYSTEM = "You are a quiz generation engine for a document-grounded tutor. Produce exactly one multiple-choice question."

QUIZ_TOOLS = ["sample_document_excerpts", "get_quiz_history"]


class QuizAgent:
    name = "quiz_agent"

    def __init__(self, llm: LLM, registry: ToolRegistry, learner: LearnerStateService):
        self.llm = llm
        self.registry = registry.subset(QUIZ_TOOLS)
        self.learner = learner

    def _generate(self, scope: Scope, state, budget: Budget, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        ctx = ToolContext(scope=scope, budget=budget)
        rejected = ""
        attempts: List[Dict[str, Any]] = []
        event["attempts"] = attempts
        for attempt in range(1, config.QUIZ_MAX_GENERATION_ATTEMPTS + 1):
            sample = self.registry.run("sample_document_excerpts", ctx, {"n": 3})
            if not sample.ok:
                attempts.append({"attempt": attempt, "accepted": False, "reason": sample.error})
                break
            excerpts = [c["text"] for c in sample.chunks]
            prompt = build_quiz_prompt(state.current_phase, "\n\n".join(excerpts), state.get_weak_topics(), state.asked_questions)
            prompt += (
                "\n\nAlso include `source_quote`: a short verbatim quote (at least 15 characters) copied exactly from "
                "the excerpts above that supports the correct answer. The four options must be distinct."
            )
            if rejected:
                prompt += f"\n\nYour previous attempt was rejected: {rejected}. Write a different question."
            try:
                generated: Optional[QuizQuestion] = self.llm.structured(QuizQuestion, prompt, QUIZ_SYSTEM, budget=budget, name="quiz_agent.generate_question")
            except BudgetExceeded as exc:
                attempts.append({"attempt": attempt, "accepted": False, "reason": exc.reason})
                break
            ok, reason, valid = quiz_service.validate_generated_question(
                generated.model_dump() if generated else None, state.current_phase, state.asked_questions, excerpts
            )
            attempts.append({"attempt": attempt, "accepted": ok, "reason": reason, "suggested_difficulty": generated.difficulty if generated else None})
            if ok:
                return valid
            rejected = reason
        return None

    @staticmethod
    def _complete_result(state, reply_parts: List[str], event: Dict[str, Any]) -> Dict[str, Any]:
        acc = state.get_overall_accuracy()
        reply_parts = [*reply_parts, (
            f"🏁 **Quiz complete.** Final score: **{state.total_correct}/{state.total_attempted}** ({acc:.1f}%). "
            f"You need 70% to unlock the next phase. Reset the quiz to try again."
        )]
        return {
            "reply": "\n\n".join(reply_parts),
            "score": state.total_correct,
            "total": state.total_attempted,
            "quiz_details": {
                "current_phase": state.current_phase,
                "question_dict": None,
                "quiz_complete": True,
                "overall_accuracy": acc,
                "weak_topics": state.get_weak_topics(),
            },
            "event": event,
        }

    def take_turn(self, *, scope: Scope, message: str, budget: Budget) -> Dict[str, Any]:
        event: Dict[str, Any] = {"step": "quiz_agent"}
        with self.learner.locked(scope):
            state = self.learner.get(scope)
            reply_parts: List[str] = []
            evaluation = None

            pending = state.current_question
            answer_recognized = bool(pending) and (
                quiz_service.parse_selection(message) != -1
                or any(o.lower() in message.lower() for o in pending.get("options", []))
            )

            if state.quiz_complete and not pending:
                # Already finished (e.g. the page was reloaded): show the result again, never a 16th question.
                event["action"] = "quiz_complete"
                return self._complete_result(state, [], event)

            if pending and not answer_recognized:
                # Not an answer (e.g. the page was reloaded): re-present the pending question, don't grade or regenerate.
                event["action"] = "re_present_pending_question"
                question = pending
            else:
                if pending:
                    evaluation, _, parts = quiz_service.score_pending_answer(state, message)
                    reply_parts.extend(parts)
                    event["graded"] = evaluation.model_dump()
                if state.quiz_complete:
                    self.learner.save(state)
                    event["action"] = "quiz_complete"
                    return self._complete_result(state, reply_parts, event)
                event["action"] = "generate_question"
                event["phase"] = state.current_phase
                event["weak_topics_targeted"] = state.get_weak_topics()
                question = self._generate(scope, state, budget, event)
                if question is None:
                    question = quiz_service.fallback_question(scope.document_id, state.current_phase)
                    event["fallback_used"] = True
                state.current_question = question
                self.learner.save(state)

            reply_parts.append(quiz_service.format_question_block(state, question))
            event["difficulty"] = question["difficulty"]
            return {
                "reply": "\n\n".join(reply_parts),
                "score": state.total_correct,
                "total": state.total_attempted,
                "quiz_details": {
                    "current_phase": state.current_phase,
                    "question_dict": quiz_service.public_question(question),
                    "overall_accuracy": state.get_overall_accuracy(),
                    "weak_topics": state.get_weak_topics(),
                },
                "event": event,
            }
