"""
Guide Agent - whole-document study modes (summary, key points, ELI5, glossary).

Decision: single-pass vs. parallel map-reduce, based on document size and the remaining LLM budget.
Validation: the synthesized text must be non-trivial; one retry, then a safe fallback message.
"""
import concurrent.futures
import contextvars
from typing import Any, Dict, List, Tuple

from backend import config
from backend.agents.common import UNTRUSTED_EXCERPTS
from backend.guardrails.leak import check_leak, protect
from backend.budget import Budget, BudgetExceeded
from backend.services.llm_service import LLM

GUIDE_SYSTEM = (
    "You are a friendly, patient AI tutor helping a learner understand a document section by section. "
    "Be clear, accurate, and stick strictly to the given material."
)
GUIDE_SYSTEM = f"{GUIDE_SYSTEM} {UNTRUSTED_EXCERPTS}"

PROMPTS = {
    "summary": {
        "map": "Summarize the key ideas of this document excerpt in 3-5 sentences:\n\n{text}",
        "reduce": "These are summaries of consecutive sections of the same document. Combine them into one cohesive, well-organized summary (6-10 sentences):\n\n{text}",
    },
    "key_points": {
        "map": "List the most important key points from this document excerpt as concise bullets:\n\n{text}",
        "reduce": "These are key-point bullet lists from consecutive sections of the same document. Merge them into one deduplicated, well-organized bullet list:\n\n{text}",
    },
    "eli5": {
        "map": "Explain the main ideas of this document excerpt in very simple terms, as if teaching a curious beginner. Use short sentences and everyday analogies:\n\n{text}",
        "reduce": "These are simple, beginner-friendly explanations of consecutive sections of the same document. Combine them into one friendly, easy-to-follow explanation of the whole document:\n\n{text}",
    },
    "glossary": {
        "map": "Extract important technical terms or concepts from this document excerpt and give each a one-sentence definition:\n\n{text}",
        "reduce": "These are term/definition lists from consecutive sections of the same document. Merge them into one deduplicated glossary, sorted alphabetically:\n\n{text}",
    },
}

FALLBACK_TEXT = "I wasn't able to generate a reliable response for this document. Please try again."


def group_chunks(chunks: List[str], max_chars: int = 400_000) -> List[str]:
    groups: List[str] = []
    current: List[str] = []
    size = 0
    for chunk in chunks:
        if current and size + len(chunk) > max_chars:
            groups.append("\n\n".join(current))
            current, size = [], 0
        current.append(chunk)
        size += len(chunk)
    if current:
        groups.append("\n\n".join(current))
    return groups


class GuideAgent:
    name = "guide_agent"
    max_attempts = 2

    def __init__(self, llm: LLM, max_workers: int = 5):
        self.llm = llm
        self.max_workers = max_workers

    def _plan_groups(self, chunks: List[str], budget: Budget) -> List[str]:
        groups = group_chunks(chunks)
        # Each group costs one LLM call plus one reduce call: keep the total inside the request budget.
        cap = max(1, min(config.GUIDE_MAX_GROUPS, budget.max_llm_calls - budget.llm_calls - 1))
        if len(groups) > cap:
            total = sum(len(c) for c in chunks)
            groups = group_chunks(chunks, max_chars=total // cap + 1)[:cap]
        return groups

    def _run(self, mode: str, groups: List[str], budget: Budget) -> str:
        prompts = PROMPTS[mode]
        if len(groups) == 1:
            return self.llm.text(prompts["map"].format(text=groups[0]), GUIDE_SYSTEM, budget=budget, name="guide_agent.summarize")

        def map_one(group: str) -> str:
            return self.llm.text(prompts["map"].format(text=group), GUIDE_SYSTEM, budget=budget, name="guide_agent.map")

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(self.max_workers, len(groups))) as pool:
            futures = [pool.submit(contextvars.copy_context().run, map_one, g) for g in groups]  # worker threads keep the caller's context variables
            partials = [f.result() for f in futures]
        combined = "\n\n---\n\n".join(partials)
        return self.llm.text(prompts["reduce"].format(text=combined), GUIDE_SYSTEM, budget=budget, name="guide_agent.reduce")

    def synthesize(self, *, mode: str, chunks: List[str], budget: Budget) -> Tuple[str, Dict[str, Any]]:
        event: Dict[str, Any] = {"step": "guide_agent", "mode": mode, "chunks": len(chunks)}
        groups = self._plan_groups(chunks, budget)
        event["strategy"] = "single_pass" if len(groups) == 1 else "parallel_map_reduce"
        event["groups"] = len(groups)
        for attempt in range(1, self.max_attempts + 1):
            try:
                text = self._run(mode, groups, budget)
            except BudgetExceeded as exc:
                event["stopped"] = exc.reason
                break
            leaked, how = check_leak(text, chunks) if text else (False, "")
            if text and len(text.strip()) >= 20 and not leaked:
                event["attempts"] = attempt
                return text, event
            event["rejected_attempt"] = attempt
            if leaked:
                event["rejected_because"] = f"exposes internal instructions ({how})"
        event["fallback_used"] = True
        return FALLBACK_TEXT, event


# The leak check compares answers with these real prompts, so it cannot drift from them.
protect(GUIDE_SYSTEM)
protect(*(text for mode in PROMPTS.values() for text in mode.values()), rules=False)
