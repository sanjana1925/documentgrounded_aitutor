"""
Retrieval Agent + Evidence Evaluator.

The Retrieval Agent decides HOW to look for evidence (which tool, which query), calls a
controlled tool, and observes the result. On attempts after the first it uses the evaluator's
findings (what is still missing) to choose a *different* strategy. It cannot repeat an attempt
it already made, cannot exceed the attempt budget, and cannot call tools outside its allowlist.
The Evidence Evaluator then judges relevance / sufficiency / coverage in structured form.
"""
from typing import Any, Dict, List, Optional, Tuple

from backend import config
from backend.agents.common import format_chunks, preview
from backend.agents.schemas import EvidenceEvaluation, RetrievalDecision
from backend.budget import Budget, BudgetExceeded
from backend.services.llm_service import LLM
from backend.services.quiz_service import normalize as norm_text
from backend.services.retrieval_service import Scope
from backend.tools.base import ToolContext, ToolRegistry
from backend.guardrails.leak import protect

RETRIEVAL_AGENT_TOOLS = [
    "get_document_metadata",
    "search_document",
    "search_topic",
    "search_similar_chunks",
    "get_neighbor_chunks",
    "search_by_metadata",
]

RETRIEVAL_SYSTEM = (
    "You are the retrieval agent of a document tutor. A previous search did not find enough evidence. "
    "Choose ONE different retrieval strategy for the next attempt, using only the tools listed. "
    "Use search_document with a rewritten query when the wording was the problem; search_topic with a short "
    "topic phrase when the question is broad; get_neighbor_chunks or search_similar_chunks with an "
    "anchor_chunk_index from the current evidence when a definition may continue in nearby text; "
    "search_by_metadata only when a page number is mentioned. Never repeat a query already tried."
)

EVALUATOR_SYSTEM = (
    "You judge retrieved document excerpts for a study question. relevant: do the excerpts address the "
    "question's topic? sufficient: is there enough information to answer the question fully and accurately "
    "from the excerpts alone? coverage: 0-1, the fraction of what the question needs that is present. "
    "missing_information: specific facts still missing (empty if none). recommended_action: use_evidence if "
    "sufficient; retrieve_again if related material likely exists elsewhere in the document; rewrite_query if "
    "the search wording seems wrong; answer_not_supported if the document does not appear to cover this. "
    "If not sufficient, give suggested_query - a better search query."
)


def _signature(strategy: str, args: Dict[str, Any]) -> str:
    key = args.get("query") or args.get("topic") or args.get("chunk_index") or args.get("page") or ""
    return f"{strategy}:{norm_text(str(key))}"


def _tool_args(decision: RetrievalDecision) -> Dict[str, Any]:
    s = decision.strategy
    if s == "search_document":
        return {"query": decision.query[:500]}
    if s == "search_topic":
        return {"topic": (decision.topic or decision.query)[:200]}
    if s in ("search_similar_chunks", "get_neighbor_chunks"):
        return {"chunk_index": decision.anchor_chunk_index}
    if s == "search_by_metadata":
        return {"page": decision.page}
    return {}


def merge_evidence(existing: List[Dict[str, Any]], new: List[Dict[str, Any]], cap: int = config.MAX_EVIDENCE_CHUNKS) -> List[Dict[str, Any]]:
    by_index = {c["chunk_index"]: c for c in existing}
    for c in new:
        by_index.setdefault(c["chunk_index"], c)
    ranked = sorted(by_index.values(), key=lambda c: c["distance"] if c.get("distance") is not None else 0.0)
    kept = ranked[:cap]
    return sorted(kept, key=lambda c: c["chunk_index"])


class RetrievalAgent:
    name = "retrieval_agent"

    def __init__(self, llm: LLM, registry: ToolRegistry):
        self.llm = llm
        self.registry = registry.subset(RETRIEVAL_AGENT_TOOLS)  # allowlist

    # ---- decision logic -------------------------------------------------
    def _candidates(self, question: str, evidence: List[Dict[str, Any]], last_eval: Optional[Dict[str, Any]]) -> List[RetrievalDecision]:
        missing = " ".join((last_eval or {}).get("missing_information", [])[:2])
        suggested = (last_eval or {}).get("suggested_query", "")
        cands = [
            RetrievalDecision(strategy="search_document", query=suggested or question, reasoning="evaluator's suggested query"),
            RetrievalDecision(strategy="search_topic", query=missing or question, topic=missing or question, reasoning="broaden to the missing topic"),
        ]
        if evidence:
            cands.append(
                RetrievalDecision(strategy="get_neighbor_chunks", query=question, anchor_chunk_index=evidence[0]["chunk_index"], reasoning="expand around the best chunk")
            )
        cands.append(RetrievalDecision(strategy="search_document", query=f"{question} definition explanation", reasoning="reword the question"))
        return cands

    def _valid(self, d: RetrievalDecision, evidence: List[Dict[str, Any]], tried: set) -> bool:
        if d.strategy not in self.registry.names():
            return False
        anchors = {c["chunk_index"] for c in evidence}
        if d.strategy in ("search_document",) and not d.query.strip():
            return False
        if d.strategy in ("search_similar_chunks", "get_neighbor_chunks") and d.anchor_chunk_index not in anchors:
            return False
        if d.strategy == "search_by_metadata" and d.page < 1:
            return False
        return _signature(d.strategy, _tool_args(d)) not in tried

    def choose_next(
        self, *, question: str, evidence: List[Dict[str, Any]], tried: List[Dict[str, str]], last_eval: Optional[Dict[str, Any]], budget: Budget
    ) -> Tuple[Optional[RetrievalDecision], str]:
        tried_sigs = {t["signature"] for t in tried}
        prompt = (
            f"Question: {question}\n\n"
            f"Already tried: {[t['signature'] for t in tried]}\n"
            f"Evaluator says missing: {(last_eval or {}).get('missing_information', [])}\n"
            f"Evaluator suggested query: {(last_eval or {}).get('suggested_query', '')}\n"
            f"Current evidence: {[{'chunk_index': c['chunk_index'], 'page': c.get('page'), 'preview': preview(c['text'])} for c in evidence]}\n\n"
            f"Available tools:\n{self.registry.describe()}"
        )
        try:
            proposed = self.llm.structured(RetrievalDecision, prompt, RETRIEVAL_SYSTEM, budget=budget, name="retrieval_agent.choose_strategy")
        except BudgetExceeded:
            proposed = None
        if proposed is not None and self._valid(proposed, evidence, tried_sigs):
            return proposed, "llm"
        for cand in self._candidates(question, evidence, last_eval):
            if self._valid(cand, evidence, tried_sigs):
                return cand, "deterministic_fallback"
        return None, "exhausted"

    # ---- one agent step ---------------------------------------------------
    def step(
        self, *, scope: Scope, budget: Budget, question: str, evidence: List[Dict[str, Any]], tried: List[Dict[str, str]], last_eval: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        ctx = ToolContext(scope=scope, budget=budget)
        attempt = budget.retrieval_attempts + 1
        event: Dict[str, Any] = {"step": "retrieval_agent", "attempt": attempt}

        if not tried:
            meta = self.registry.run("get_document_metadata", ctx, {})
            event["document"] = meta.data if meta.ok else {"error": meta.error}
            if meta.ok and not meta.data.get("indexed"):
                event["outcome"] = "document_not_indexed"
                return {"stop_reason": "document_not_indexed", "trace": [event]}
            decision = RetrievalDecision(strategy="search_document", query=question, reasoning="default first strategy: search the document with the standalone question")
            source = "default_strategy"
        else:
            decision, source = self.choose_next(question=question, evidence=evidence, tried=tried, last_eval=last_eval, budget=budget)
            if decision is None:
                event["outcome"] = "no_new_strategy"
                return {"retrieval_exhausted": True, "trace": [event]}

        args = _tool_args(decision)
        budget.retrieval_attempts += 1
        result = self.registry.run(decision.strategy, ctx, args)

        merged = merge_evidence(evidence, result.chunks) if result.ok else evidence
        event.update(
            {
                "strategy": decision.strategy,
                "args": args,
                "strategy_source": source,
                "reasoning": decision.reasoning,
                "tool_ok": result.ok,
                "tool_error": result.error,
                "chunks_returned": [c["chunk_index"] for c in result.chunks],
                "evidence_size": len(merged),
            }
        )
        update: Dict[str, Any] = {
            "evidence": merged,
            "tried": tried + [{"strategy": decision.strategy, "signature": _signature(decision.strategy, args)}],
            "search_query": args.get("query") or args.get("topic") or question,
            "trace": [event],
        }
        if not result.ok and result.error in ("time_budget_exceeded", "tool_call_budget_exceeded"):
            update["stop_reason"] = result.error
        return update


class EvidenceEvaluator:
    name = "evidence_evaluator"

    def __init__(self, llm: LLM):
        self.llm = llm

    def evaluate(self, *, question: str, evidence: List[Dict[str, Any]], budget: Budget) -> Tuple[EvidenceEvaluation, str]:
        if not evidence:
            # Nothing to judge - no LLM call needed.
            return (
                EvidenceEvaluation(
                    relevant=False, sufficient=False, coverage=0.0,
                    missing_information=["any passage about the question"],
                    recommended_action="rewrite_query", suggested_query="",
                ),
                "deterministic_no_evidence",
            )
        prompt = f"Question: {question}\n\nRetrieved excerpts:\n{format_chunks(evidence)}"
        try:
            result = self.llm.structured(EvidenceEvaluation, prompt, EVALUATOR_SYSTEM, budget=budget, name="evidence_evaluator.evaluate")
        except BudgetExceeded:
            result = None
        if result is None:
            # A failed evaluator must not block a grounded answer: the tutor cites chunks and the critic re-checks.
            return (
                EvidenceEvaluation(relevant=True, sufficient=True, coverage=0.5, missing_information=[], recommended_action="use_evidence"),
                "evaluator_unavailable",
            )
        return self._normalize(result), "llm"

    @staticmethod
    def _normalize(e: EvidenceEvaluation) -> EvidenceEvaluation:
        e = e.model_copy()
        if e.sufficient and e.relevant:
            e.recommended_action = "use_evidence"
        elif e.recommended_action == "use_evidence":
            e.recommended_action = "retrieve_again" if e.relevant else "rewrite_query"
        return e


# The leak check compares answers with these real prompts, so it cannot drift from them.
protect(RETRIEVAL_SYSTEM, EVALUATOR_SYSTEM)
