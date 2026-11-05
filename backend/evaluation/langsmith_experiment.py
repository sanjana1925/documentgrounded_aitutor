"""
LangSmith experiments: Golden dataset -> LangSmith dataset -> run each arm -> evaluators -> compare runs.

    python evaluate.py --langsmith --arm both

creates ONE LangSmith dataset (verified examples only) and ONE experiment per arm
("<prefix>-baseline_rag", "<prefix>-agentic_rag"). Open both in LangSmith and use "Compare" to see
retrieval quality, answer similarity, groundedness, completion, tool usage and latency side by side.
Requires LANGSMITH_API_KEY; without it nothing is uploaded and nothing is invented.
"""
import os
import time
from typing import Any, Callable, Dict, List, Optional

from backend.evaluation import evaluators as ev
from backend.evaluation.dataset import upload_to_langsmith
from backend.services.evaluation_service import EvaluationService
from backend.services.retrieval_service import Scope

DATASET_NAME = "ai-tutor-guide-golden-verified"


def _result(key: str, score: Optional[float], comment: str = "") -> Dict[str, Any]:
    return {"key": key, "score": score, "comment": comment or ("Not evaluated" if score is None else "")}


def make_evaluators(embed, llm=None, judge: bool = False, top_k: int = 4, judge_pause: float = 0.0) -> List[Callable]:
    """LangSmith evaluators: (run, example) -> {"key", "score"}. Score None means 'not evaluated'."""

    def outputs(run):
        return run.outputs or {}

    def skip_if_errored(key, run):
        """An errored run has no output. It must be 'not evaluated', never scored as zero."""
        if getattr(run, "error", None) or not (run.outputs or {}):
            return _result(key, None, "run errored (e.g. provider rate limit): not evaluated")
        return None

    def recall_at_k(run, example):
        if (skipped := skip_if_errored("recall_at_k", run)) is not None:
            return skipped
        o, gold = outputs(run), example.outputs
        m = ev.retrieval_metrics(o.get("first_attempt_chunks", []), gold["source_chunk"], gold.get("expected_keywords", []), top_k)
        return _result("recall_at_k", m["recall_at_k"])

    def precision_at_k(run, example):
        if (skipped := skip_if_errored("precision_at_k", run)) is not None:
            return skipped
        o, gold = outputs(run), example.outputs
        m = ev.retrieval_metrics(o.get("first_attempt_chunks", []), gold["source_chunk"], gold.get("expected_keywords", []), top_k)
        return _result("precision_at_k", m["precision_at_k"])

    def answer_similarity(run, example):
        if (skipped := skip_if_errored("answer_similarity", run)) is not None:
            return skipped
        o = outputs(run)
        if ev.abstained(o.get("answer", "")):
            return _result("answer_similarity", None, "abstained")
        return _result("answer_similarity", ev.answer_similarity(embed, o.get("answer", ""), example.outputs.get("reference_answer", "")))

    def lexical_groundedness(run, example):
        if (skipped := skip_if_errored("lexical_groundedness", run)) is not None:
            return skipped
        o = outputs(run)
        if ev.abstained(o.get("answer", "")):
            return _result("lexical_groundedness", None, "abstained")
        return _result("lexical_groundedness", ev.lexical_groundedness(o.get("answer", ""), o.get("evidence_texts", [])), "heuristic, not an LLM judgement")

    def completed(run, example):
        if (skipped := skip_if_errored("completed", run)) is not None:
            return skipped
        return _result("completed", 1.0 if outputs(run).get("workflow", {}).get("completed") else 0.0)

    def safe_fallback(run, example):
        if (skipped := skip_if_errored("safe_fallback", run)) is not None:
            return skipped
        return _result("safe_fallback", 1.0 if outputs(run).get("workflow", {}).get("fell_back_to_safe_answer") else 0.0)

    def tool_calls(run, example):
        if (skipped := skip_if_errored("tool_calls", run)) is not None:
            return skipped
        return _result("tool_calls", float(outputs(run).get("workflow", {}).get("tool_calls", 0)))

    def unnecessary_retries(run, example):
        if (skipped := skip_if_errored("unnecessary_retrieval_retries", run)) is not None:
            return skipped
        return _result("unnecessary_retrieval_retries", float(outputs(run).get("workflow", {}).get("unnecessary_retrieval_retries", 0)))

    def revisions(run, example):
        if (skipped := skip_if_errored("revision_attempts", run)) is not None:
            return skipped
        return _result("revision_attempts", float(outputs(run).get("workflow", {}).get("revisions", 0)))

    def groundedness_shared(run, example):
        if (skipped := skip_if_errored("groundedness_shared", run)) is not None:
            return skipped
        o = outputs(run)
        if ev.abstained(o.get("answer", "")):
            return _result("groundedness_shared", None, "abstained")
        return _result("groundedness_shared", ev.lexical_groundedness(o.get("answer", ""), o.get("shared_evidence_texts", o.get("evidence_texts", []))), "heuristic, equal evidence for both arms")

    evaluators: List[Callable] = [recall_at_k, precision_at_k, answer_similarity, lexical_groundedness, groundedness_shared, completed, safe_fallback,
                                  tool_calls, unnecessary_retries, revisions]

    if judge and llm is not None:
        def faithfulness(run, example):
            if (skipped := skip_if_errored("faithfulness_llm_judge", run)) is not None:
                return skipped
            time.sleep(judge_pause)
            o = outputs(run)
            if ev.abstained(o.get("answer", "")):
                return _result("faithfulness_llm_judge", None, "abstained")
            return _result("faithfulness_llm_judge", ev.llm_judge(llm, "faithfulness", example.inputs["question"], o.get("answer", ""), o.get("evidence_texts", [])), "LLM-as-judge")

        def relevancy(run, example):
            if (skipped := skip_if_errored("answer_relevancy_llm_judge", run)) is not None:
                return skipped
            time.sleep(judge_pause)
            o = outputs(run)
            if ev.abstained(o.get("answer", "")):
                return _result("answer_relevancy_llm_judge", None, "abstained")
            return _result("answer_relevancy_llm_judge", ev.llm_judge(llm, "answer_relevancy", example.inputs["question"], o.get("answer", ""), o.get("evidence_texts", [])), "LLM-as-judge")

        evaluators += [faithfulness, relevancy]
    return evaluators


def run_experiments(service: EvaluationService, scope: Scope, items: List[Dict[str, Any]], arms: List[str], prefix: str,
                    judge: bool = False, client=None, evaluate_fn: Optional[Callable] = None, dataset_name: str = DATASET_NAME,
                    pause: float = 0.0, retries: int = 3, backoff: float = 25.0, judge_pause: float = 0.0) -> Dict[str, Any]:
    if client is None:
        if not os.environ.get("LANGSMITH_API_KEY"):
            return {"status": "skipped", "reason": "LANGSMITH_API_KEY is not set; nothing was uploaded"}
        from langsmith import Client

        client = Client()
    if evaluate_fn is None:
        from langsmith import evaluate as evaluate_fn  # type: ignore[assignment]

    upload_to_langsmith(client, dataset_name, items)
    by_question = {i["question"]: i for i in items}
    evaluators = make_evaluators(service.embed, service.judge_llm, judge, service.top_k, judge_pause)
    experiments: Dict[str, Any] = {}

    for arm in arms:
        def target(inputs: Dict[str, Any], arm: str = arm) -> Dict[str, Any]:
            question = inputs["question"]
            if pause:
                time.sleep(pause)
            # Same retry/backoff as the local run: a provider rate limit must not become an errored example.
            out = service.call_with_retry(arm, scope, by_question[question], retries, backoff)
            return {k: out[k] for k in ("answer", "first_attempt_chunks", "evidence_texts", "shared_evidence_texts", "workflow")} | {"latency_seconds": round(out["latency"], 2)}

        results = evaluate_fn(
            target,
            data=dataset_name,
            evaluators=evaluators,
            experiment_prefix=f"{prefix}-{arm}",
            metadata={"arm": arm, "document": scope.document_id, "judge": judge, "examples": len(items)},
            max_concurrency=1,
        )
        experiments[arm] = getattr(results, "experiment_name", str(results))
    return {"status": "ok", "dataset": dataset_name, "experiments": experiments,
            "compare": "Open both experiments in LangSmith (Datasets & Experiments) and choose Compare."}
