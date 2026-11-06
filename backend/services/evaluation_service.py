"""
Runs the two RAG arms over a verified dataset and aggregates real, measured metrics:

    baseline_rag : retrieve top-k -> one LLM call -> answer        (no decisions, no critic)
    agentic_rag  : the full LangGraph workflow (Supervisor, retrieval loop, evidence evaluator, tutor, critic)

Both arms see the same questions and the same document, so the comparison is like-for-like.
"""
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence

from backend import config
from backend.budget import Budget
from backend.evaluation import evaluators as ev
from backend.graph.workflow import run_request
from backend.guardrails.retrieval import get_grounding_fallback
from backend.services.llm_service import LLMError
from backend.services.retrieval_service import RetrievalService, Scope

BASELINE_SYSTEM = (
    "You are a friendly, patient AI tutor helping a learner understand a document. Use the provided context as "
    "your source of truth, but explain things properly like a tutor would. Stay strictly grounded in the context "
    "and don't invent facts that aren't supported by it. If the context truly doesn't cover the question at all, "
    "say so honestly."
)
FOLLOW_UP_MARKER = "\n\n**Check your understanding:**"

Embedder = Callable[[List[str]], List[Sequence[float]]]


def baseline_generate_answer(llm, question: str, chunks: List[str], feedback: str = "", budget: Optional[Budget] = None) -> str:
    if not chunks:
        return get_grounding_fallback()
    prompt = f"Context:\n{chr(10).join(chunks)}\n\nQuestion: {question}"
    if feedback:
        prompt += f"\n\nYour previous answer had a problem: {feedback}\nWrite a better answer that fixes this."
    return llm.text(prompt, BASELINE_SYSTEM, budget=budget or Budget(max_llm_calls=1), name="baseline_rag.generate")


def default_embedder() -> Embedder:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(config.EMBEDDING_MODEL_NAME)
    return lambda texts: [list(map(float, v)) for v in model.encode(texts)]


class EvaluationService:
    def __init__(self, llm, retrieval: RetrievalService, graph, embed: Embedder, top_k: int = config.QA_TOP_K, judge_llm=None,
                 judge_relevancy: bool = False, judge_pause: float = 0.0):
        self.llm, self.retrieval, self.graph, self.embed, self.top_k = llm, retrieval, graph, embed, top_k
        # The model that scores faithfulness. Defaults to the answering model; a different one avoids self-judging.
        self.judge_llm = judge_llm or llm
        self.judge_relevancy = judge_relevancy  # answer relevancy is rarely used, so it is opt-in (one fewer call per answer)
        self.judge_pause = judge_pause  # seconds between judge calls, for models with low per-minute quotas

    # ---- arms -------------------------------------------------------------
    def run_baseline(self, scope: Scope, question: str) -> Dict[str, Any]:
        start = time.perf_counter()
        chunks = self.retrieval.search(scope, question, self.top_k)
        answer = baseline_generate_answer(self.llm, question, [c["text"] for c in chunks])
        return {
            "answer": answer,
            "first_attempt_chunks": chunks,
            "all_retrieved_indices": [c["chunk_index"] for c in chunks],
            "evidence_texts": [c["text"] for c in chunks],
            # The baseline's own evidence IS the standard top-k retrieval of the raw question.
            "shared_evidence_texts": [c["text"] for c in chunks],
            "latency": time.perf_counter() - start,
            "workflow": {"completed": bool(answer), "fell_back_to_safe_answer": ev.abstained(answer), "tool_calls": 1,
                         "llm_calls": 1 if chunks else 0, "retrieval_attempts": 1, "revisions": 0,
                         "retrieval_retries": 0, "unnecessary_retrieval_retries": 0, "stop_reason": None},
        }

    def run_agentic(self, scope: Scope, question: str, gold_chunk: int) -> Dict[str, Any]:
        start = time.perf_counter()
        final, budget = run_request(self.graph, message=question, session_id=scope.session_id, document_id=scope.document_id, budget=Budget())
        latency = time.perf_counter() - start
        trace = final.get("trace", [])
        attempts = [e for e in trace if e.get("step") == "retrieval_agent" and "strategy" in e]
        first_indices = attempts[0]["chunks_returned"] if attempts else []
        all_indices = sorted({i for e in attempts for i in e.get("chunks_returned", [])})
        reply = (final.get("reply") or "").split(FOLLOW_UP_MARKER)[0]
        return {
            "answer": reply,
            "first_attempt_chunks": self.retrieval.get_by_indices(scope, first_indices),
            "all_retrieved_indices": all_indices,
            "evidence_texts": [c["text"] for c in final.get("evidence", [])],
            # Arm-independent evidence: the same top-k search the baseline uses, so both arms can be judged on equal terms.
            "shared_evidence_texts": [c["text"] for c in self.retrieval.search(scope, question, self.top_k)],
            "latency": latency,
            "llm_error": final.get("llm_error"),
            "workflow": ev.workflow_metrics(trace, budget.snapshot(), gold_chunk, reply, final.get("stop_reason")),
        }

    # ---- scoring ----------------------------------------------------------
    def score(self, arm: str, item: Dict[str, Any], out: Dict[str, Any], judge: bool) -> Dict[str, Any]:
        gold = item["source_chunk"]
        keywords = item.get("expected_keywords", [])
        rm = ev.retrieval_metrics(out["first_attempt_chunks"], gold, keywords, self.top_k)
        abstain = ev.abstained(out["answer"])
        row = {
            "id": item["id"],
            "question": item["question"],
            "topic": item.get("topic", "General"),
            "difficulty": item.get("difficulty", "medium"),
            "arm": arm,
            "generated_answer": out["answer"],
            "reference_answer": item.get("reference_answer", ""),
            "abstained": abstain,
            "retrieval_recall_at_k": round(rm["recall_at_k"], 3),
            "retrieval_precision_at_k": round(rm["precision_at_k"], 3),
            "keyword_coverage": round(rm["keyword_coverage"], 3),
            "recall_over_all_retrieved": 1.0 if gold in out["all_retrieved_indices"] else 0.0,
            "answer_similarity": None,
            "groundedness_score": None,
            "faithfulness": None,
            "answer_relevancy": None,
            "groundedness_shared": None,
            "faithfulness_shared": None,
            "evidence_chunks": len(out["evidence_texts"]),
            "latency_seconds": round(out["latency"], 2),
            **out["workflow"],
        }
        if not abstain:
            sim = ev.answer_similarity(self.embed, out["answer"], item.get("reference_answer", ""))
            row["answer_similarity"] = round(sim, 3) if sim is not None else None
            g = ev.lexical_groundedness(out["answer"], out["evidence_texts"])
            row["groundedness_score"] = round(g, 3) if g is not None else None
            shared = out.get("shared_evidence_texts", out["evidence_texts"])
            gs = ev.lexical_groundedness(out["answer"], shared)
            row["groundedness_shared"] = round(gs, 3) if gs is not None else None
            if judge:
                if self.judge_pause:
                    time.sleep(self.judge_pause)
                f = ev.llm_judge(self.judge_llm, "faithfulness", item["question"], out["answer"], out["evidence_texts"])
                r = None
                if self.judge_relevancy:
                    if self.judge_pause:
                        time.sleep(self.judge_pause)
                    r = ev.llm_judge(self.judge_llm, "answer_relevancy", item["question"], out["answer"], out["evidence_texts"])
                # Same evidence as the baseline saw: reuse the score when it is literally the same text, else judge again.
                fs = f if shared == out["evidence_texts"] else ev.llm_judge(self.judge_llm, "faithfulness", item["question"], out["answer"], shared)
                row["faithfulness"] = round(f, 3) if f is not None else None
                row["faithfulness_shared"] = round(fs, 3) if fs is not None else None
                row["answer_relevancy"] = round(r, 3) if r is not None else None
        return row

    def _one(self, arm: str, scope: Scope, item: Dict[str, Any]) -> Dict[str, Any]:
        if arm == "baseline_rag":
            return self.run_baseline(scope, item["question"])
        out = self.run_agentic(scope, item["question"], item["source_chunk"])
        if out.get("llm_error"):  # the provider failed - this says nothing about answer quality
            raise LLMError(out["llm_error"]["status"], out["llm_error"]["detail"])
        if out["workflow"].get("stop_reason") == "time_budget_exceeded":
            # Almost always rate-limit waits eating the request's time allowance - infrastructure, not an answer.
            raise LLMError(504, "request ran out of its time budget (likely provider rate-limit waits)")
        return out

    def call_with_retry(self, arm: str, scope: Scope, item: Dict[str, Any], retries: int = 2, backoff: float = 15.0) -> Dict[str, Any]:
        """Runs one arm on one item, retrying provider failures with growing waits. Raises LLMError if they persist."""
        for attempt in range(retries + 1):
            try:
                return self._one(arm, scope, item)
            except LLMError:
                if attempt >= retries:
                    raise
                time.sleep(backoff * (attempt + 1))
        raise AssertionError("unreachable")

    def run(self, arm: str, scope: Scope, items: List[Dict[str, Any]], judge: bool = False, pause: float = 0.0,
            retries: int = 2, backoff: float = 15.0, on_row: Optional[Callable[[Dict[str, Any]], None]] = None) -> List[Dict[str, Any]]:
        """Provider failures (rate limits, outages) are retried with backoff. If they persist the row is marked
        `errored` and excluded from every metric - an outage must never be scored as the tutor abstaining."""
        rows = []
        for i, item in enumerate(items):
            if i and pause:
                time.sleep(pause)
            try:
                row = self.score(arm, item, self.call_with_retry(arm, scope, item, retries, backoff), judge)
            except LLMError as exc:
                row = {"id": item["id"], "question": item["question"], "arm": arm, "errored": True,
                       "error": f"{exc.status_code}: {exc.detail}"}
            rows.append(row)
            if on_row:
                on_row(row)
        return rows


def _mean(values: List[Optional[float]]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


def aggregate(all_rows: List[Dict[str, Any]], top_k: int = config.QA_TOP_K) -> Dict[str, Any]:
    rows = [r for r in all_rows if not r.get("errored")]
    n = len(rows)
    metrics = {
        "avg_retrieval_recall_at_k": _mean([r["retrieval_recall_at_k"] for r in rows]),
        "avg_retrieval_precision_at_k": _mean([r["retrieval_precision_at_k"] for r in rows]),
        "avg_keyword_coverage": _mean([r["keyword_coverage"] for r in rows]),
        "avg_answer_similarity": _mean([r["answer_similarity"] for r in rows]),
        "avg_groundedness_score": _mean([r["groundedness_score"] for r in rows]),
        "avg_faithfulness_llm_judge": _mean([r["faithfulness"] for r in rows]),
        "avg_answer_relevancy_llm_judge": _mean([r["answer_relevancy"] for r in rows]),
        "avg_groundedness_shared": _mean([r.get("groundedness_shared") for r in rows]),
        "avg_faithfulness_shared_llm_judge": _mean([r.get("faithfulness_shared") for r in rows]),
        "avg_evidence_chunks": _mean([r.get("evidence_chunks") for r in rows]),
        "avg_latency_seconds": _mean([r["latency_seconds"] for r in rows]),
        "avg_llm_calls": _mean([r["llm_calls"] for r in rows]),
        "avg_tool_calls": _mean([r["tool_calls"] for r in rows]),
        "avg_retrieval_attempts": _mean([r["retrieval_attempts"] for r in rows]),
        "avg_revisions": _mean([r["revisions"] for r in rows]),
        "completion_rate": _mean([1.0 if r["completed"] else 0.0 for r in rows]),
        "safe_fallback_rate": _mean([1.0 if r["fell_back_to_safe_answer"] else 0.0 for r in rows]),
        "total_unnecessary_retrieval_retries": sum(r["unnecessary_retrieval_retries"] for r in rows),
    }
    return {
        "num_questions": n,
        "num_errored_excluded": len(all_rows) - n,
        # Similarity / groundedness / faithfulness are averaged over answered questions only; this is that n.
        "num_answered": sum(1 for r in rows if not r["abstained"]),
        # Answers the judge actually scored. Lower than num_answered means some judge calls failed (rate limit, outage).
        "num_faithfulness_scored": sum(1 for r in rows if r.get("faithfulness") is not None),
        "top_k": top_k,
        **metrics,
        "not_evaluated": sorted(k for k, v in metrics.items() if v is None),
    }


COMPARED = [
    ("avg_retrieval_recall_at_k", True), ("avg_retrieval_precision_at_k", True), ("avg_answer_similarity", True),
    ("avg_groundedness_score", True), ("avg_groundedness_shared", True), ("avg_faithfulness_llm_judge", True),
    ("avg_faithfulness_shared_llm_judge", True), ("avg_answer_relevancy_llm_judge", True),
    ("completion_rate", True), ("safe_fallback_rate", False), ("avg_llm_calls", False), ("avg_tool_calls", False), ("avg_latency_seconds", False),
]


def compare(baseline: Dict[str, Any], agentic: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for key, higher_is_better in COMPARED:
        b, a = baseline.get(key), agentic.get(key)
        if b is None or a is None:
            out[key] = {"baseline": b, "agentic": a, "delta": None, "note": "not evaluated"}
            continue
        delta = round(a - b, 3)
        out[key] = {"baseline": b, "agentic": a, "delta": delta, "agentic_better": (delta > 0) == higher_is_better if delta else None}
    return out


def build_report(arms: Dict[str, List[Dict[str, Any]]], dataset_info: Dict[str, Any], top_k: int = config.QA_TOP_K) -> Dict[str, Any]:
    aggregates = {arm: aggregate(rows, top_k) for arm, rows in arms.items()}
    primary = "agentic_rag" if "agentic_rag" in arms else next(iter(arms))
    report: Dict[str, Any] = {
        "system_evaluation": aggregates[primary],
        "results": [r for r in arms[primary] if not r.get("errored")],
        "primary_arm": primary,
        "arms": {
            arm: {
                "system_evaluation": aggregates[arm],
                "results": [r for r in arms[arm] if not r.get("errored")],
                "errored": [{"id": r["id"], "error": r["error"]} for r in arms[arm] if r.get("errored")],
            }
            for arm in arms
        },
        "dataset": dataset_info,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "metric_notes": {
            "retrieval_recall_at_k": "1 if the verified gold source chunk is in the first search's top-k, else 0 (both arms use the same top-k)",
            "retrieval_precision_at_k": "share of top-k chunks that are the gold chunk or contain >=50% of the expected keywords",
            "answer_similarity": "cosine similarity of MiniLM embeddings between the answer and the reference answer",
            "groundedness_score": "HEURISTIC: share of the answer's content words that appear in the evidence (not an LLM judgement)",
            "groundedness_shared": "same heuristic, but scored against the standard top-k retrieval of the raw question for BOTH arms, so the arms are compared on equal evidence",
            "faithfulness_shared_llm_judge": "LLM-judge faithfulness against that same shared evidence (--judge only)",
            "avg_evidence_chunks": "how many chunks the arm's generator was given on average (the agentic arm can gather more than the baseline)",
            "num_answered": "questions answered rather than declined; similarity, groundedness and faithfulness are averaged over these only",
            "faithfulness_llm_judge / answer_relevancy_llm_judge": "LLM-as-judge scores, only present when the run used --judge",
        },
    }
    if "baseline_rag" in arms and "agentic_rag" in arms:
        report["comparison"] = compare(aggregates["baseline_rag"], aggregates["agentic_rag"])
    return report
