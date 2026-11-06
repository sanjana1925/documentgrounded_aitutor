"""
Metric functions. Each is honest about what it measures:

  * retrieval recall/precision    - chunk-level, against the verified gold source chunk
  * answer_similarity             - cosine similarity of embeddings (MiniLM) to the reference answer
  * lexical_groundedness          - a HEURISTIC: share of the answer's content words found in the evidence
  * llm_judge_*                   - LLM-as-judge (faithfulness / relevancy); only computed when requested
  * workflow metrics              - counted from what the run actually did

Anything that was not run is None and is listed as "not evaluated" - never guessed.
"""
import math
import re
from typing import Any, Callable, Dict, List, Optional, Sequence

from pydantic import BaseModel, Field

from backend.budget import Budget
from backend.guardrails.retrieval import NOT_SUPPORTED_MESSAGE

_WORD = re.compile(r"[a-zA-Z][a-zA-Z\-']{3,}")
_STOP = {
    "that", "this", "with", "from", "have", "which", "their", "there", "these", "those", "were", "been", "will", "would",
    "about", "into", "than", "then", "them", "they", "your", "what", "when", "where", "while", "also", "such", "some",
    "each", "other", "more", "most", "only", "over", "very", "based", "document", "context", "text",
}


def content_words(text: str) -> List[str]:
    return [w.lower() for w in _WORD.findall(text or "") if w.lower() not in _STOP]


def retrieval_metrics(retrieved: Sequence[Dict[str, Any]], gold_chunk: int, expected_keywords: Sequence[str], k: int) -> Dict[str, float]:
    top = list(retrieved)[:k]
    kws = [w.lower() for w in expected_keywords]
    hit = any(c["chunk_index"] == gold_chunk for c in top)

    def relevant(c: Dict[str, Any]) -> bool:
        if c["chunk_index"] == gold_chunk:
            return True
        text = c["text"].lower()
        return bool(kws) and sum(1 for w in kws if w in text) / len(kws) >= 0.5

    joined = " ".join(c["text"].lower() for c in top)
    return {
        "recall_at_k": 1.0 if hit else 0.0,
        "precision_at_k": (sum(1 for c in top if relevant(c)) / len(top)) if top else 0.0,
        "keyword_coverage": (sum(1 for w in kws if w in joined) / len(kws)) if kws else 0.0,
    }


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def answer_similarity(embed: Callable[[List[str]], List[Sequence[float]]], answer: str, reference: str) -> Optional[float]:
    if not answer or not reference:
        return None
    a, r = embed([answer, reference])
    return cosine(a, r)


def lexical_groundedness(answer: str, evidence_texts: Sequence[str]) -> Optional[float]:
    """Heuristic only: fraction of the answer's content words that occur in the evidence."""
    words = set(content_words(answer))
    if not words:
        return None
    pool = set(content_words(" ".join(evidence_texts)))
    return len(words & pool) / len(words)


def abstained(answer: str) -> bool:
    return (answer or "").strip() == NOT_SUPPORTED_MESSAGE


class JudgeScore(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    rationale: str


JUDGE_SYSTEM = {
    "faithfulness": "Score 0-1 how well EVERY claim in the answer is supported by the evidence (1 = fully supported, 0 = unsupported or contradicted).",
    "answer_relevancy": "Score 0-1 how directly and completely the answer addresses the question (1 = fully, 0 = not at all).",
}


def llm_judge(llm, kind: str, question: str, answer: str, evidence_texts: Sequence[str]) -> Optional[float]:
    """LLM-as-judge score (labelled as such in reports). Returns None if the judge could not score."""
    prompt = f"Question: {question}\n\nEvidence:\n" + "\n---\n".join(evidence_texts) + f"\n\nAnswer:\n{answer}"
    try:
        result = llm.structured(JudgeScore, prompt, JUDGE_SYSTEM[kind], budget=Budget(max_llm_calls=2, max_tool_calls=0, max_seconds=60), name=f"eval.judge_{kind}")
    except Exception:  # noqa: BLE001
        return None
    return result.score if result else None


def workflow_metrics(trace: List[Dict[str, Any]], budget_snapshot: Dict[str, Any], gold_chunk: int, reply: str, stop_reason: Optional[str]) -> Dict[str, Any]:
    attempts = [e for e in trace if e.get("step") == "retrieval_agent" and "strategy" in e]
    first_hit = bool(attempts) and gold_chunk in attempts[0].get("chunks_returned", [])
    retries = max(0, len(attempts) - 1)
    return {
        "stop_reason": stop_reason,
        "completed": bool(reply) and stop_reason not in ("internal_error", "output_guardrail_failed"),
        "fell_back_to_safe_answer": abstained(reply) or bool(stop_reason),
        "tool_calls": budget_snapshot["tool_calls"],
        "llm_calls": budget_snapshot["llm_calls"],
        "retrieval_attempts": budget_snapshot["retrieval_attempts"],
        "revisions": budget_snapshot["revisions"],
        "retrieval_retries": retries,
        # A retry is "unnecessary" when the very first search already returned the gold chunk.
        "unnecessary_retrieval_retries": retries if first_hit else 0,
    }
