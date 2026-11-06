"""
Builds a golden dataset from a document that is ACTUALLY indexed, so every example can be verified.

For evenly spaced chunks the LLM drafts one question + reference answer + keywords that the chunk alone can
answer. Python then verifies each draft (keywords really appear in the chunk, the reference answer is
supported by the chunk, no duplicate questions) and drops anything that fails. The result is LLM-DRAFTED and
programmatically verified - it is marked `needs_human_review` because a person should still read it.

    python -m backend.evaluation.build_golden --session <session_id> --document chem.pdf --n 10 --out golden_dataset_chem.json
"""
import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from backend.budget import Budget
from backend.evaluation.dataset import verify_item
from backend.evaluation.evaluators import content_words
from backend.services.quiz_service import similarity
from backend.services.retrieval_service import RetrievalService, Scope

DIFFICULTY_SHARE = (("simple", 0.40), ("medium", 0.35), ("high", 0.25))
MIN_ANSWER_SUPPORT = 0.6

GOLDEN_SYSTEM = (
    "You write evaluation questions for a document-grounded tutor. Using ONLY the passage given, write one question "
    "that the passage alone can answer, a short reference answer (1-3 sentences) copied or closely paraphrased from "
    "the passage, 3-5 expected_keywords that appear verbatim in the passage, and a short topic label. Difficulty "
    "guide: simple = direct recall of a stated fact; medium = a conceptual relationship or explanation; high = "
    "applying the idea to reason through a case described by the passage."
)


class GoldenDraft(BaseModel):
    question: str
    reference_answer: str
    expected_keywords: List[str] = Field(min_length=3)
    topic: str


def difficulty_plan(n: int) -> List[str]:
    """Largest-remainder split of n questions by DIFFICULTY_SHARE (ties go to the harder tier): 10 -> 4/3/3."""
    exact = [n * share for _, share in DIFFICULTY_SHARE]
    counts = [int(x) for x in exact]
    order = sorted(range(len(exact)), key=lambda i: (exact[i] - counts[i], i), reverse=True)
    for i in order[: n - sum(counts)]:
        counts[i] += 1
    plan: List[str] = []
    for (name, _), count in zip(DIFFICULTY_SHARE, counts):
        plan += [name] * count
    return plan


def pick_chunks(chunks: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
    usable = [c for c in chunks if len(c["text"]) >= 200]
    if len(usable) <= n:
        return usable
    step = len(usable) / n
    return [usable[int(i * step)] for i in range(n)]


def build(llm, retrieval: RetrievalService, scope: Scope, n: int = 10) -> Dict[str, Any]:
    all_chunks, _ = retrieval.get_records(scope)
    picked = pick_chunks(all_chunks, n)
    plan = difficulty_plan(len(picked))
    items: List[Dict[str, Any]] = []
    dropped: List[Dict[str, Any]] = []
    for chunk, difficulty in zip(picked, plan):
        prompt = f"Difficulty to write: {difficulty}\n\nPassage:\n{chunk['text']}"
        draft = llm.structured(GoldenDraft, prompt, GOLDEN_SYSTEM, budget=Budget(max_llm_calls=2, max_tool_calls=0, max_seconds=40), name="build_golden.draft")
        if draft is None:
            dropped.append({"source_chunk": chunk["chunk_index"], "reason": "model returned no valid draft"})
            continue
        item = {
            "id": len(items) + 1,
            "question": draft.question.strip(),
            "reference_answer": draft.reference_answer.strip(),
            "expected_keywords": [k.strip() for k in draft.expected_keywords],
            "source_document": scope.document_id,
            "source_page": chunk["page"],
            "source_chunk": chunk["chunk_index"],
            "topic": draft.topic.strip(),
            "difficulty": difficulty,
            "origin": "llm_drafted_from_chunk",
            "review_status": "needs_human_review",
        }
        reasons = list(verify_item(retrieval, scope, item)["reasons"])
        words = set(content_words(item["reference_answer"]))
        support = len(words & set(content_words(chunk["text"]))) / len(words) if words else 0.0
        if support < MIN_ANSWER_SUPPORT:
            reasons.append(f"reference answer only {support:.0%} supported by the chunk")
        if any(similarity(item["question"], other["question"]) >= 0.85 for other in items):
            reasons.append("duplicate of another question")
        if reasons:
            dropped.append({"source_chunk": chunk["chunk_index"], "reason": "; ".join(reasons)})
            continue
        items.append(item)
    return {"items": items, "dropped": dropped}


def main() -> None:
    from backend.container import get_container  # imported lazily: builds the real services

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True)
    parser.add_argument("--document", required=True)
    parser.add_argument("--n", type=int, default=10)
    parser.add_argument("--out", default="golden_dataset_generated.json")
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv(override=True)
    container = get_container()
    result = build(container.llm, container.retrieval, Scope(args.session, args.document), args.n)
    Path(args.out).write_text(json.dumps(result["items"], indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(result['items'])} verified items to {args.out}; dropped {len(result['dropped'])}.")
    for d in result["dropped"]:
        print("  dropped:", d)


if __name__ == "__main__":
    main()
