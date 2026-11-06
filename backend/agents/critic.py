"""
Critic Agent - checks a draft answer against the evidence.

The Critic reports structured findings (grounded / relevant / complete / unsupported claims /
missing information / contradictions). The pass / revise / retrieve-again / fallback DECISION is
then made by `decide()` in Python so the loop can never exceed its revision and retrieval budgets.
"""
from typing import Any, Dict, List, Optional, Tuple

from backend.agents.common import format_chunks, UNTRUSTED_EXCERPTS
from backend.agents.schemas import CriticEvaluation
from backend.budget import Budget, BudgetExceeded
from backend.services.llm_service import LLM
from backend.guardrails.leak import protect

CRITIC_SYSTEM = (
    "You are a strict reviewer of a tutor's answer. Judge it ONLY against the evidence excerpts. "
    "grounded: every factual claim is supported by the excerpts. relevant: it answers the learner's question. "
    "complete: it covers everything the excerpts say that the question needs. unsupported_claims: claims not "
    "found in the excerpts. contradictions: statements the excerpts contradict. missing_information: important "
    "points from the excerpts (or that the question needs) that are absent. recommended_action: finish if the "
    "answer is good; revise if it can be fixed using the existing excerpts; retrieve_again if the excerpts "
    "themselves lack something the question needs."
)
CRITIC_SYSTEM = f"{CRITIC_SYSTEM} {UNTRUSTED_EXCERPTS}"


class CriticAgent:
    name = "critic_agent"

    def __init__(self, llm: LLM):
        self.llm = llm

    def review(self, *, question: str, evidence: List[Dict[str, Any]], answer: str, budget: Budget) -> Tuple[Optional[CriticEvaluation], str]:
        prompt = f"Question: {question}\n\nEvidence excerpts:\n{format_chunks(evidence)}\n\nAnswer to review:\n{answer}"
        try:
            result = self.llm.structured(CriticEvaluation, prompt, CRITIC_SYSTEM, budget=budget, name="critic_agent.review")
        except BudgetExceeded:
            return None, "budget_exceeded"
        return result, "llm" if result is not None else "invalid_output"

    @staticmethod
    def decide(e: CriticEvaluation, budget: Budget) -> Tuple[str, str]:
        """Returns (action, reason); action in finish | revise | retrieve_again | fallback."""
        clean = e.grounded and e.relevant and not e.unsupported_claims and not e.contradictions
        if clean and e.complete:
            return "finish", "passed all checks"
        if budget.can_revise():
            if e.recommended_action == "retrieve_again" and e.missing_information and budget.can_retrieve():
                return "retrieve_again", "critic found information the evidence lacks"
            return "revise", "critic found fixable problems"
        # Out of revisions: accept a grounded, relevant answer that is merely incomplete; never ship an ungrounded one.
        if clean:
            return "finish", "revision budget exhausted; accepting a grounded but incomplete answer"
        return "fallback", "revision budget exhausted and the answer is not grounded"

    @staticmethod
    def feedback_text(e: CriticEvaluation) -> str:
        parts = []
        if e.unsupported_claims:
            parts.append(f"Unsupported claims (remove or support them): {e.unsupported_claims}")
        if e.contradictions:
            parts.append(f"Contradictions with the evidence: {e.contradictions}")
        if e.missing_information:
            parts.append(f"Missing information: {e.missing_information}")
        if not e.relevant:
            parts.append("The answer does not address the question.")
        return "\n".join(parts) or "Improve completeness and grounding."


# The leak check compares answers with these real prompts, so it cannot drift from them.
protect(CRITIC_SYSTEM)
