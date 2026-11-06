"""
Output leak check: does an answer reproduce or paraphrase the tutor's own instructions?

The check knows the REAL prompts. Each agent registers its system prompt with `protect()` where it defines it, so the
check cannot go stale when a prompt is edited and needs no hand-kept list of phrases. An answer is compared with them
in three ways, all of which ignore anything that is also in the learner's question or the retrieved document text (a
document that talks about prompts, or a question that quotes one, is not a leak):

  copied wording   - runs of five words that appear in a protected prompt (three distinct runs is a leak)
  internal names   - field and action names that exist only in the prompts (used_chunk_indices, need_more_evidence ...)
  paraphrase       - a sentence in which the assistant talks ABOUT its own instructions ("my instructions say...") AND
                     whose meaning matches one of the real rule prompts better than anything in the context. Both
                     are needed: similarity to a prompt alone cannot tell a leak from an ordinary "here is a summary of
                     the key ideas". Uses the same local multilingual sentence model as the injection check, so a leak
                     translated into another language is caught too. Only run on the final answer ("deep").
"""
import logging
import re

import numpy as np

from backend import config
from functools import lru_cache
from typing import List, Sequence, Set, Tuple

logger = logging.getLogger("tutor.guardrails")

SHINGLE_WORDS = 5
MIN_SHARED_SHINGLES = 3
MIN_INTERNAL_NAMES = 2
MIN_SENTENCE_WORDS = 6
SELF_DISCLOSURE_SIM = 0.55  # closeness to "I was told to..." style sentences
SELF_DISCLOSURE_MARGIN = 0.05  # ...and this much closer to them than to ordinary tutor sentences
RULE_SIM = 0.45  # closeness to a real rule prompt (the self-disclosure test is what keeps ordinary sentences out)
RULE_SIM_GRAMMAR_ONLY = 0.55  # stricter when the only sign of self-disclosure is the grammar rule
RULE_MARGIN = 0.10  # ...and this much closer to it than to anything in the question or retrieved text
MAX_CONTEXT_SENTENCES = 150

_PROTECTED: List[str] = []  # everything that must not be copied
_RULES: List[str] = []  # the subset that states the assistant's own rules and role (compared by meaning as well)
_WORD = re.compile(r"[^\W_]+")
_SENTENCE = re.compile(r"(?<=[.!?])\s+|[\n;:。！？]+")
_INTERNAL_NAME = re.compile(r"\b[a-z]+(?:_[a-z]+)+\b")
# English sentences only count as "talking about my own instructions" when they say so in the first person, or say that the
# assistant/system itself was told or required to do something. A third-person description of how a critic step works is
# ordinary explanation. Other languages have no such gate and rely on the sentence-meaning comparison alone.
_ENGLISH_WORDS = {"the", "is", "are", "that", "it", "with", "this", "of", "to", "and", "my", "i", "be", "as", "not", "or", "for", "was", "were", "an"}
_FIRST_PERSON = re.compile(
    r"\b(?:i|i'm|i've|i'll|i'd|my|me|myself|we|our)\b|"
    r"\b(?:assistant|tutor|system|model|ai|chatbot|bot|supervisor|critic|agent)\b[^.]{0,30}\b(?:was|were|is|are|has been|have been|been)\b[^.]{0,15}\b(?:told|instructed|programmed|configured|required|supposed|designed|prompted|set up)\b",
    re.I)


# The assistant (or "I") together with vocabulary of being configured, instructed or bound by rules.
_SELF_CONFIG = re.compile(
    r"\b(?:i|i'm|i've|i'd|my|me|assistant|tutor|system|supervisor|critic|agent|model)\b[^.]{0,40}\b(?:instructions?|instructed|rules?|guidelines?|"
    r"configured|configuration|set up|setup|programmed|told|required|supposed|designed|built|prompted|polic(?:y|ies)|constraints?|"
    r"restrictions?|checklist|procedure|wrote me|bound by)\b",
    re.I)


def _is_english(sentence: str) -> bool:
    return bool(set(_words(sentence)) & _ENGLISH_WORDS)


def _speaks_about_itself(sentence: str) -> bool:
    return bool(_FIRST_PERSON.search(sentence)) if _is_english(sentence) else True


def protect(*prompts: str, rules: bool = True) -> None:
    """
    Register prompt text that must never appear in an answer. Called by each agent for its own prompts.
    `rules=False` is for task templates and style hints ("Summarize the key ideas of..."): copying them word for word is
    still a leak, but they are not compared by meaning, because ordinary answers resemble them.
    """
    for prompt in prompts:
        prompt = (prompt or "").strip()
        if prompt and prompt not in _PROTECTED:
            _PROTECTED.append(prompt)
        if rules and prompt and prompt not in _RULES:
            _RULES.append(prompt)


def _words(text: str) -> List[str]:
    return _WORD.findall((text or "").lower())


def _shingles(words: List[str]) -> Set[str]:
    return {" ".join(words[i : i + SHINGLE_WORDS]) for i in range(len(words) - SHINGLE_WORDS + 1)}


_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")


def _sentences(text: str) -> List[str]:
    """Sentences long enough to be worth comparing. Chinese, Japanese and Korean have no spaces, so length stands in for words."""
    keep = lambda s: len(_words(s)) >= MIN_SENTENCE_WORDS or (bool(_CJK.search(s)) and len(s) >= 10)  # noqa: E731
    return [s.strip() for s in _SENTENCE.split(text or "") if keep(s)]


@lru_cache(maxsize=8)
def _protected_index(prompts: Tuple[str, ...], rules: Tuple[str, ...]):
    """Shingles and internal names of every registered prompt, sentences of the rule prompts (rebuilt when one is added)."""
    shingles: Set[str] = set()
    names: Set[str] = set()
    for prompt in prompts:
        shingles |= _shingles(_words(prompt))
        names |= set(_INTERNAL_NAME.findall(prompt))
    return shingles, names, [sentence for prompt in rules for sentence in _sentences(prompt)]


@lru_cache(maxsize=4)
def _vectors(sentences: Tuple[str, ...]):
    from backend.guardrails.injection import _embedder

    return _embedder().encode(list(sentences), normalize_embeddings=True, show_progress_bar=False, batch_size=64)


def _copied_or_named(answer: str, context: Sequence[str]) -> Tuple[bool, str]:
    shingles, names, _ = _protected_index(tuple(_PROTECTED), tuple(_RULES))
    context_words = _words(" ".join(context))
    context_shingles = _shingles(context_words)
    shared = (_shingles(_words(answer)) & shingles) - context_shingles
    if len(shared) >= MIN_SHARED_SHINGLES:
        return True, "copied wording"
    lowered = " ".join(context).lower()
    used = {n for n in names if n in answer and n not in lowered}
    if len(used) >= MIN_INTERNAL_NAMES:
        return True, "internal names"
    return False, ""


def _paraphrased(answer: str, context: Sequence[str]) -> bool:
    try:
        _, _, rule_sentences = _protected_index(tuple(_PROTECTED), tuple(_RULES))
        mine = _sentences(answer)
        if not mine or not rule_sentences:
            return False
        theirs = [s for text in context for s in _sentences(text)][:MAX_CONTEXT_SENTENCES]
        from backend.guardrails.injection import _embedder
        from backend.guardrails.leak_exemplars import NORMAL_ANSWERS, SELF_DISCLOSURE

        vectors = _embedder().encode(mine + theirs, normalize_embeddings=True, show_progress_bar=False, batch_size=64)
        a, c = vectors[: len(mine)], vectors[len(mine) :]
        about_itself = (a @ _vectors(tuple(SELF_DISCLOSURE)).T).max(axis=1)
        ordinary = (a @ _vectors(tuple(NORMAL_ANSWERS)).T).max(axis=1)
        to_rules = (a @ _vectors(tuple(rule_sentences)).T).max(axis=1)
        to_context = (a @ c.T).max(axis=1) if len(c) else to_rules * 0.0
        grammar_ok = np.array([_speaks_about_itself(x) for x in mine])
        by_meaning = (about_itself >= SELF_DISCLOSURE_SIM) & (about_itself - ordinary >= SELF_DISCLOSURE_MARGIN) & grammar_ok
        by_grammar = np.array([_is_english(x) and bool(_SELF_CONFIG.search(x)) for x in mine])
        beats_context = to_rules - to_context >= RULE_MARGIN
        leak_by_meaning = by_meaning & (to_rules >= RULE_SIM) & beats_context
        leak_by_grammar = by_grammar & (to_rules >= RULE_SIM_GRAMMAR_ONLY) & beats_context
        hits = leak_by_meaning | leak_by_grammar
        count = int(hits.sum())
        strong = bool((hits & (about_itself >= config.LEAK_STRONG_SELF_SIM) & (to_rules >= config.LEAK_STRONG_RULE_SIM)).any())
        if count and count < config.LEAK_PARAPHRASE_MIN_SENTENCES and not strong:
            logger.info("one borderline sentence resembles the assistant's rules; not blocking (needs %d)", config.LEAK_PARAPHRASE_MIN_SENTENCES)
            return False
        return count > 0
    except Exception:  # noqa: BLE001 - a failing model must not break answering
        logger.warning("semantic leak check unavailable", exc_info=True)
        return False


def check_leak(answer: str, context: Sequence[str] = (), deep: bool = False) -> Tuple[bool, str]:
    """
    (leaks, how). `context` is what the answer is allowed to repeat: the question and the retrieved document text.
    `deep` adds the paraphrase check, which embeds sentences; the cheap checks run on every call.
    """
    if not _PROTECTED or not (answer or "").strip():
        return False, ""
    hit, how = _copied_or_named(answer, context)
    if hit:
        return True, how
    if deep and _paraphrased(answer, context):
        return True, "paraphrase"
    return False, ""
