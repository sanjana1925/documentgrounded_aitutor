"""
Prompt-injection analysis in three layers. Used on learners' messages and on the text of uploaded documents.

  structural  - what the text is made of: chat-template tokens, role labels, fake delimiters, hidden or look-alike
                characters, encoded payloads, spaced-out or leet-speak obfuscation, data-leaking markdown links
  syntactic   - how the sentences are built: an imperative (or "you must / can you ...") that is aimed at the AI
                AND whose object is the AI's own rules, prompt, safety or role. A bare imperative such as
                "Explain this" or a question ABOUT injection is not suspicious, so study questions pass
  semantic    - what the text means: embedding similarity (a local sentence model, no API call) between each
                sentence and a library of known attack phrasings, in several languages

Rules are graded. Only constructions that are unambiguous block on their own (score 1.0); ambiguous ones score 0.5
and need a second signal from another layer, because phrases like "ignore the previous question" or "act as my
study buddy" are normal in a study tool. Reasons are short codes, never the text itself. A failing semantic model
never blocks chat: the other two layers keep working.
"""
import base64
import binascii
import logging
import re
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from backend import config
from backend.guardrails.injection_exemplars import ATTACKS, BENIGN

logger = logging.getLogger("tutor.guardrails")

MIN_ANALYSED_CHARS = 12
MAX_SENTENCES = 60
STRONG = 1.0  # a layer score at or above this blocks on its own
MEDIUM = 0.5  # needs corroboration from another layer


# --------------------------------------------------------------------------------------------- lexicons
# Verbs that cancel or replace instructions. "Strong" ones mean that even without a noun ("disregard the above").
OVERRIDE_STRONG_VERBS = {
    "ignore", "disregard", "forget", "override", "overrule", "supersede", "neglect", "overlook", "dismiss",
    "discard", "abandon", "bypass", "circumvent",
}
OVERRIDE_WEAK_VERBS = {
    "skip", "cancel", "erase", "drop", "stop", "violate", "break", "wipe", "clear", "reset", "delete", "remove",
    "revoke", "void", "scrap", "purge", "nullify", "negate", "replace", "withdraw", "rescind", "suspend", "set",
}
INSTRUCTION_NOUNS = {
    "instructions", "instruction", "rules", "rule", "prompt", "prompts", "guidelines", "guideline", "directives",
    "directive", "constraints", "restrictions", "safeguards", "guardrails", "policies", "policy", "training",
    "programming", "safety", "limitations", "commands", "orders", "told", "directions", "configuration", "settings", "setup",
}
# Words that point at the AI's own earlier rules rather than at some ordinary list of instructions.
OVERRIDE_POINTERS = {
    "your", "yours", "you", "previous", "earlier", "prior", "initial", "original", "preceding", "all", "any", "every",
    "system", "given", "told", "above", "these", "those", "everything",
}
CONTEXT_OBJECTS = {"context", "document", "excerpts", "excerpt", "passage", "passages", "material", "sources", "text"}
ANAPHORA = {"above", "previous", "prior", "earlier", "preceding", "everything", "given"}

EXFIL_VERBS = {
    "reveal", "show", "print", "display", "repeat", "output", "leak", "dump", "tell", "say", "write", "give",
    "expose", "recite", "echo", "return", "provide", "copy", "paste", "quote", "disclose", "share", "list",
}
# Objects that are the AI's own rules are enough with a pointing word; ordinary text needs a stronger one.
EXFIL_TIER1 = {"prompt", "prompts", "instructions", "instruction", "rules", "guidelines", "directives", "configuration", "config", "programming", "setup"}
EXFIL_TIER2 = {"message", "messages", "text", "conversation", "context", "everything"}
EXFIL_POINTERS = {"your", "yours", "you", "exact", "above", "previous", "initial", "original", "hidden", "secret", "system", "developer", "verbatim", "exactly", "preceding", "prior", "beginning", "confidential"}
EXFIL_TIER2_POINTERS = {"system", "hidden", "secret", "initial", "original", "developer", "confidential", "verbatim", "beginning", "exactly"}

BYPASS_VERBS = {"bypass", "disable", "deactivate", "circumvent", "override", "remove", "lift", "turn", "switch", "violate"}
BYPASS_OBJECTS = {"safety", "filter", "filters", "guardrail", "guardrails", "restriction", "restrictions", "policy", "policies", "censorship", "moderation", "ethics", "ethical", "limits", "limitations", "alignment", "safeguards", "rules"}
AI_QUALIFIERS = {"your", "yours", "you", "model", "ai", "assistant", "chatbot", "llm", "moral", "ethical", "ethics"}

SEND_VERBS = {"send", "post", "upload", "email", "mail", "forward", "transmit", "exfiltrate", "leak", "submit", "append", "attach"}
SEND_OBJECTS = {"prompt", "instructions", "conversation", "history", "document", "data", "secrets", "secret", "key", "keys", "password", "passwords", "credentials", "information", "details", "contents", "context", "messages"}

# Words that may sit directly in front of a verb that is addressed to the AI.
LEAD_WORDS = {
    "please", "kindly", "now", "then", "and", "also", "just", "first", "next", "finally", "so", "instead", "but",
    "you", "must", "should", "shall", "will", "can", "could", "would", "always", "never", "immediately", "simply",
    "ok", "okay", "hey", "hi", "hello", ",",
}
CONDITIONAL_WORDS = {"if", "when", "unless", "whether", "how", "what", "why", "after", "before", "once", "while", "because", "that", "where", "which"}
QUESTION_STARTERS = {"what", "why", "how", "when", "where", "who", "which", "does", "do", "did", "is", "are", "was", "were", "has", "have", "should"}
SUBJECT_PRONOUNS = {"i", "we", "they", "he", "she", "it", "people", "users", "students", "someone", "one"}

_FORMAT_CHARS = {"​", "‌", "‍", "⁠", "﻿", "­", "‎", "‏"}
_HOMOGLYPH_MAP = {
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y", "і": "i", "ѕ": "s", "ј": "j", "һ": "h",
    "ԁ": "d", "ɡ": "g", "ν": "v", "ο": "o", "ρ": "p", "α": "a", "ε": "e", "ι": "i", "τ": "t", "κ": "k", "μ": "m",
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T", "Х": "X",
}
_HOMOGLYPHS = str.maketrans(_HOMOGLYPH_MAP)
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|[;\n\r。！？]+|[.!?]+$")
_WORD = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?|\d+|,")
_TEMPLATE_TOKENS = re.compile(r"<\|[a-z_ ]{2,30}\|>|\[/?INST\]|<<\s*/?SYS\s*>>|<\s*/?(?:system|assistant)\s*>|###\s*(?:system|instruction)", re.I)
_ROLE_LABEL = re.compile(r"^\s*(?:system|developer|assistant|admin|administrator)\s*:|\[(?:system|assistant|developer|admin)\]", re.I | re.M)
_HIDDEN_MARKUP = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0|<!--.{0,300}?-->", re.I | re.S)
_FAKE_DELIMITER = re.compile(
    r"</?\s*(?:context|document|excerpts?|instructions?|rules|prompt)\s*>|\bend\s+of\s+(?:the\s+)?(?:document|context|excerpts?|instructions?|prompt)\b[\s.:\-]*(?:begin|new|now|system|instructions?|ignore)|"
    r"-{3,}\s*(?:begin|end)\b[^-\n]{0,40}(?:system|instructions?|prompt)", re.I)
_MD_EXFIL = re.compile(r"!\[[^\]]*\]\(\s*https?://[^)\s]*[?&][^)\s]*\)", re.I)
_MD_EXFIL_HINT = re.compile(r"[{\[<]|summary|prompt|secret|conversation|history|context|\bdata\b|\bapi[_-]?key", re.I)
_BASE64_RUN = re.compile(r"[A-Za-z0-9+/]{32,}={0,2}")
_SPACED_LETTERS = re.compile(r"(?:\b\w\b[\s.\-_*]+){5,}\b\w\b")
_URL_OR_EMAIL = re.compile(r"https?://|www\.|[\w.+-]+@[\w-]+\.[\w.]+|\b[a-z0-9-]+\.(?:com|net|org|io|xyz|ru|cn)\b", re.I)
_SQUASH_PHRASES = (
    "ignoreprevious", "ignoreall", "ignoreyour", "ignoretheabove", "ignoreinstructions", "disregardprevious", "disregardall",
    "disregardthe", "forgeteverything", "forgetyour", "systemprompt", "jailbreak", "developermode", "revealyour",
    "youarenow", "overrideyour", "bypassyour", "newinstructions",
)
_ROLE_REASSIGN = re.compile(
    r"\byou(?:'re| are) (?:now|no longer) (?:an? |the |my |in |free\b|unrestricted|unfiltered|bound|restricted|limited|dan\b|called|named)|"
    r"\byou will now (?:act|behave|respond|ignore|follow|obey|become|answer|play|be (?:an?|my|the)\b)|"
    r"\bfrom now on\b[^.]{0,40}\byou\b(?:\s+\w+){0,2}\s+(?:will|must|should|are|can|shall|only|always|never|ignore|act|respond|answer)\b|"
    r"\byour (?:new|real|true|actual) (?:role|task|job|purpose|instructions?|identity)\b|\bnew instructions?\s*(?:follow(?:s|ing)?|below|are|here)?\s*[:\-]")
_EXTRACT_PHRASE = re.compile(r"\b(?:text|contents?|wording|copy|version)\s+of\s+(?:your|the)\s+(?:system|initial|original|hidden)\s+(?:message|prompt|instructions)\b")
_NEW_RULE = re.compile(r"\bnew (?:policy|rules?|mode|directive)s?\s*:|\b(?:previous|prior|earlier|old) (?:policy|rules?|instructions?|guidelines?) (?:is|are|was|were) (?:now )?(?:revoked|cancell?ed|void|obsolete|replaced)\b")
_UNCONDITIONAL = re.compile(r"\b(?:grant|comply with|fulfil+|answer|accept) (?:all|every|any) (?:requests?|questions?|commands?)\b|\bdo (?:anything|whatever) (?:the user|i|they) (?:say|says|ask|asks|want|wants)\b")
_ROLE_PLAY = re.compile(r"\b(?:pretend (?:to be|you are|that you)|act as|behave as|role-?play as|assume the role|take on the persona|simulate being)\b")
_JAILBREAK_WORDS = re.compile(r"\b(?:jailbreak(?:ed)?|dan mode|developer mode|god mode|unrestricted mode|no (?:restrictions|filters|rules|limits)|without (?:any )?(?:restrictions|filters|limits|censorship))\b")
_AUTHORITY = re.compile(r"\b(?:system override|admin(?:istrator)? (?:mode|override|command|instruction)|this (?:message|instruction) (?:comes|is) from (?:your|the) (?:creator|developer|administrator|system))\b")
_FORCED_OUTPUT = re.compile(r"\b(?:say|output|print|respond with|reply with|answer with|write)\b[^.]{0,15}\b(?:exactly|only|verbatim|the following)\b|\b(?:simply|just|only) (?:write|say|type|print|output)\b")
_ASK_OWN_PROMPT = re.compile(r"\bwhat (?:is|are|were) your (?:system |initial |original |hidden )?(?:prompt|instructions|rules|guidelines)\b")
_CONCEAL = re.compile(r"\bdo not (?:tell|inform|mention|reveal|say)\b[^.]{0,25}\b(?:user|anyone|this|that)\b")
# --- the AI's own rule set, referred to from the second person, plus an operation applied to it ---
_RULE_NOUNS = (
    r"instructions?|rules?|guidelines?|restrictions?|limitations?|constraints?|filters?|safeguards?|guardrails?|polic(?:y|ies)|"
    r"programming|set-?up|configuration|briefing|directives?|prompt|training|boundaries|censorship|safety (?:rules|settings|checks?|measures)|"
    r"instruction sheet|system (?:message|text|prompt)|initial (?:message|text)"
)
_OWN_RULES = re.compile(
    rf"\byour(?: (?:own|original|initial|earlier|previous|internal|hidden|secret|system|safety|content|opening|default))*(?: \w+)?? (?:{_RULE_NOUNS})\b|"
    rf"\b(?:{_RULE_NOUNS})\b[^.]{{0,40}}\byou (?:were|are|have been|had been|got) (?:given|told|instructed|programmed|trained|configured)\b|"
    rf"\b(?:{_RULE_NOUNS})\b[^.]{{0,30}}\byou (?:operate|work|run|function) (?:under|by|with)\b|"
    rf"\b(?:{_RULE_NOUNS})\b[^.]{{0,30}}\byou (?:must|should|have to|need to) (?:obey|follow|respect)\b|"
    rf"\b(?:{_RULE_NOUNS})\b[^.]{{0,30}}\byour (?:developers?|creators?|makers?|operators?|programmers?|owners?|company|engineers?)\b|"
    rf"\b(?:developers?|creators?|makers?|company|operators?|programmers?|owners?)\b[^.]{{0,25}}\b(?:told|gave|set|placed|imposed|wrote|instructed)\b[^.]{{0,15}}\byou\b")
_DISMISS = re.compile(
    r"\b(?:ignor\w+|disregard\w*|forget\w*|drop(?:ped)?|cancel\w*|suspend\w*|lift(?:ed)?|remov(?:e|ed)|disabl(?:e|ed)|(?:switch|turn)(?:ed)? off|"
    r"bypass\w*|overrid\w+|overrul\w+|abandon\w*|discard\w*|scrap\w*|void|revok\w+|replac(?:e|ed)|neglect\w*|circumvent\w*|relax\w*|waiv\w+|"
    r"unlock\w*|expired?|optional|cease|(?:no longer|not|n't) (?:apply|applies|binding|valid|matter)|set (?:it|them|that|this) aside|free(?:d)? from|"
    r"without (?:the |any )?)\b")
_EXPOSE = re.compile(r"\b(?:reveal\w*|show|print|quote|repeat|reproduce|recite|copy|paste|dump|leak|disclose|output|list|translate|display|expose|extract|summari[sz]e|describe|tell|give|provide|write out|begin (?:your|the) (?:next )?(?:answer|reply|response) with)\b")
_SECRECY = re.compile(r"\b(?:hidden|secret|initial|original|system|internal|confidential|verbatim|exact(?:ly)?|full|complete|word for word|entire|opening|first)\b")
_UNRESTRICTED_PERSONA = re.compile(
    r"\b(?:persona|character|version of yourself|mode|role)\b[^.]{0,40}\b(?:no|zero|without|never|free of)\b[^.]{0,15}\b(?:limit\w*|rule\w*|restriction\w*|filter\w*|guideline\w*|constraint\w*|refus\w*)\b|"
    r"\b(?:answer|respond|reply|speak|talk|behave)\b[^.]{0,25}\b(?:without|with no|with zero)\b[^.]{0,10}\b(?:any |the )?(?:filters?|restrictions?|limits?|censorship|rules|guidelines)\b[^.]{0,30}\b(?:your|you)\b")
_DOC_ADDRESS = re.compile(
    r"\b(?:attention|note to|message to|instructions? (?:for|to)|dear|hey|hello|notice to)\s+(?:the\s+)?(?:ai|assistants?|llms?|chatbots?|language models?|models?|gpt|claude|gemini)\b|"
    r"^\W*(?:ai|assistant|llm|chatbot)\s*[,:]\s*(?:you|please|ignore|do not|disregard|respond|say|always|never)\b(?!')|"
    r"\bif you are (?:an? )?(?:ai|llm|language model|assistant|chatbot|large language model)\b|"
    r"\bas an? (?:ai|llm|assistant)\b[^.]{0,40}\b(?:you )?(?:must|should|will|need to)\b")
_DOC_CONDITIONAL = re.compile(r"\b(?:when|if|whenever)\b[^.]{0,30}\b(?:users?|students?|readers?|visitors?|customers?|someone|anyone|a person|they)\b[^.]{0,20}\b(?:asks?|asked|requests?|queries|prompts?|wants?)\b")
_DOC_AI_ACTIVITY = re.compile(
    r"\b(?:ai|assistants?|llms?|chatbots?|language models?|bots?)(?: systems?| agents?| models?)?\b[^.]{0,25}\b(?:reading|processing|summari[sz]ing|parsing|analy[sz]ing|scanning|ingesting|encountering)\b[^.]{0,30}\b(?:this|these|the following|it)\b|"
    r"^\W*to the (?:ai|assistant|llm|chatbot|language model|model)\s*[:,]|"
    r"\b(?:any|every|all) (?:ai|assistants?|llms?|chatbots?|language models?|bots?)(?: systems?| agents?| models?)? (?:that|which|who|reading|processing|summari[sz]ing|parsing)\b[^.]{0,40}\b(?:must|should|shall|will|are required to|has to|have to|need to)\b")
_DOC_BEHAVIOUR = re.compile(r"\b(?:always|instead|must|respond|reply|say|answer)\b")
_DOC_PLANTED_ANSWER = re.compile(r"\b(?:always|must|should|only)\s+(?:respond|reply|say|answer|tell)\b[^.]{0,40}\bthat\b")
_DOC_TASK_HOOK = re.compile(r"\b(?:when|if|whenever)\b[^.]{0,20}\b(?:summari[sz]\w*|answer\w*|respond\w*|repl\w+|translat\w*|generat\w*|writ\w*)\b[^.]{0,40}\b(?:must|should|always|include|add|append|insert)\b")
_PROMOTION = re.compile(r"\b(?:include|add|append|insert|mention|recommend|promote|advertise)\b[^\n]{0,60}?(?:https?://|www\.|\b[a-z0-9-]+\.(?:com|net|org|io|xyz)\b|\blink\b|\bwebsite\b)")


# --------------------------------------------------------------------------------------------- result type
@dataclass
class Verdict:
    blocked: bool = False
    flagged: bool = False
    risk: float = 0.0
    semantic: float = 0.0
    margin: float = 0.0
    syntactic: float = 0.0
    structural: float = 0.0
    reasons: List[str] = field(default_factory=list)


# --------------------------------------------------------------------------------------------- normalisation
def _is_hidden(c: str) -> bool:
    return c in _FORMAT_CHARS or unicodedata.category(c) == "Cf" or 0xE0000 <= ord(c) <= 0xE007F


def normalise(text: str) -> Tuple[str, int, int]:
    """Returns (clean text, hidden-character count, words that mix Latin with look-alike letters)."""
    text = unicodedata.normalize("NFKC", text or "")
    hidden = sum(1 for c in text if _is_hidden(c))
    cleaned = "".join(c for c in text if not _is_hidden(c))
    mixed = sum(
        1 for word in re.findall(r"\w+", cleaned)
        if any("a" <= c.lower() <= "z" for c in word) and any(c in _HOMOGLYPH_MAP for c in word)
    )
    return cleaned.translate(_HOMOGLYPHS), hidden, mixed


def _sentences(text: str) -> List[str]:
    return [p.strip() for p in _SENTENCE_SPLIT.split(text) if p and p.strip()][:MAX_SENTENCES]


def _tokens(sentence: str) -> List[str]:
    return [t.lower() for t in _WORD.findall(sentence)]


# --------------------------------------------------------------------------------------------- syntactic layer
def _directive(w: List[str], i: int) -> bool:
    """Is the verb at w[i] used as a command or request addressed to the listener?"""
    if i == 0:
        return True
    prev = w[i - 1]
    if prev == "to":  # "you need to ignore ...", "I want you to ignore ..." (but not "I need to ignore ...")
        return i >= 2 and w[i - 2] in {"you", "need", "must", "have", "ought", "want", "wants", "going"} and not (i >= 3 and w[i - 3] in SUBJECT_PRONOUNS)
    if prev not in LEAD_WORDS:
        return False
    if prev in {"you", "can", "could", "would", "will"}:
        before = w[i - 2] if i >= 2 else ""
        if before in CONDITIONAL_WORDS or before in SUBJECT_PRONOUNS:
            return False  # "if you ignore ...", "they will ignore ..."
    return True


def _syntactic_rules(sentence: str, source: str) -> List[Tuple[str, float]]:
    found: List[Tuple[str, float]] = []
    w = _tokens(sentence)
    if len(w) < 2:
        return found
    low = sentence.lower()
    is_question = sentence.rstrip().endswith("?") or (w[0] in QUESTION_STARTERS and not (w[0] == "do" and w[1] in {"not", "dont", "don't"}))
    polite_request = len(w) > 2 and w[0] in {"can", "could", "would", "will"} and w[1] == "you"
    commands_possible = (not is_question) or polite_request  # a plain question about X is not a command

    for i, token in enumerate(w):
        window = w[i + 1 : i + 9]
        negated = i >= 1 and w[i - 1] in {"not", "dont", "don't", "never"}
        if commands_possible and not negated and _directive(w, i):
            has_noun = any(t in INSTRUCTION_NOUNS for t in window)
            pointed = any(t in OVERRIDE_POINTERS for t in w[max(0, i - 1) : i + 9])
            if token in OVERRIDE_STRONG_VERBS:
                if has_noun and pointed:
                    found.append(("override_instructions", STRONG))
                elif has_noun:
                    found.append(("override_unqualified", MEDIUM))  # "ignore the instructions in step 2" can be innocent
                elif any(t in ANAPHORA or t in CONTEXT_OBJECTS for t in window):
                    found.append(("override_previous_text", MEDIUM))  # also what a normal "ignore my last question" looks like
            elif token in OVERRIDE_WEAK_VERBS and has_noun and any(t in OVERRIDE_POINTERS - {"all", "any", "every", "these", "those", "above", "everything"} for t in w[max(0, i - 1) : i + 9]):
                found.append(("override_instructions", STRONG))
            if token in EXFIL_VERBS:
                pointers = [t for t in w[i : i + 9] if t in EXFIL_POINTERS]
                if any(t in EXFIL_TIER1 for t in window) and pointers:
                    found.append(("extract_hidden_text", STRONG))
                elif any(t in EXFIL_TIER2 for t in window) and any(t in EXFIL_TIER2_POINTERS for t in pointers):
                    found.append(("extract_hidden_text", STRONG))
            if token in BYPASS_VERBS and any(t in BYPASS_OBJECTS for t in window) and any(t in AI_QUALIFIERS for t in w[max(0, i - 1) : i + 9]):
                found.append(("bypass_safety", STRONG))
            if token in SEND_VERBS and any(t in SEND_OBJECTS for t in window) and _URL_OR_EMAIL.search(sentence):
                found.append(("send_data_out", STRONG))
        if token in {"stop", "quit", "cease"} and window[:1] and window[0] in {"following", "obeying", "respecting", "heeding", "honoring", "honouring", "listening"}:
            if any(t in INSTRUCTION_NOUNS for t in window) and commands_possible:
                found.append(("refuse_instructions", STRONG))
        # "do not follow / obey / listen to the rules you were given"
        if token in {"follow", "obey", "respect", "honor", "honour", "listen"} and i >= 1 and w[i - 1] in {"not", "dont", "don't", "never", "stop"}:
            if any(t in INSTRUCTION_NOUNS for t in window) and commands_possible:
                found.append(("refuse_instructions", STRONG))

    own_rules = bool(_OWN_RULES.search(low))
    if own_rules and _DISMISS.search(low) and (commands_possible or not is_question):
        found.append(("dismiss_own_rules", STRONG))
    elif own_rules and _EXPOSE.search(low) and commands_possible:
        found.append(("reveal_own_rules", STRONG if _SECRECY.search(low) else MEDIUM))
    if _UNRESTRICTED_PERSONA.search(low):
        found.append(("unrestricted_persona", STRONG))
    if _ROLE_REASSIGN.search(low):
        found.append(("reassign_role", STRONG))
    elif _ROLE_PLAY.search(low) and commands_possible:
        found.append(("role_play_request", MEDIUM))
    if _JAILBREAK_WORDS.search(low):
        found.append(("jailbreak_vocabulary", MEDIUM))
    if _AUTHORITY.search(low):
        found.append(("authority_claim", MEDIUM))
    if _FORCED_OUTPUT.search(low) and commands_possible:
        found.append(("forced_output", MEDIUM))
    if _EXTRACT_PHRASE.search(low):
        found.append(("extract_hidden_text", STRONG))
    if _NEW_RULE.search(low):
        found.append(("declares_new_rules", MEDIUM))
    if _UNCONDITIONAL.search(low):
        found.append(("unconditional_compliance", MEDIUM))
    if _ASK_OWN_PROMPT.search(low):
        found.append(("ask_for_own_instructions", STRONG))
    if _CONCEAL.search(low):
        found.append(("concealment_request", MEDIUM))

    if source == "document":  # in a document, text that talks to the AI at all is out of place
        if _DOC_ADDRESS.search(low) or _DOC_AI_ACTIVITY.search(low):
            found.append(("addresses_the_ai", STRONG))
        if _DOC_CONDITIONAL.search(low) and _DOC_PLANTED_ANSWER.search(low):
            found.append(("planted_answer_rule", STRONG))
        elif _DOC_CONDITIONAL.search(low) and _DOC_BEHAVIOUR.search(low):
            found.append(("conditional_behaviour_rule", MEDIUM))
        if _DOC_TASK_HOOK.search(low):
            found.append(("task_hook_rule", MEDIUM))
        if _PROMOTION.search(low):
            found.append(("promotional_insertion", MEDIUM))
    return found


def syntactic_score(text: str, source: str) -> Tuple[float, List[str]]:
    rules: Dict[str, float] = {}
    for sentence in _sentences(text):
        for name, weight in _syntactic_rules(sentence, source):
            rules[name] = max(weight, rules.get(name, 0.0))
    top = max(rules.values(), default=0.0)
    return (top if top >= STRONG else min(1.0, sum(rules.values()))), sorted(rules)


# --------------------------------------------------------------------------------------------- structural layer
def _printable(data: bytes) -> Optional[str]:
    try:
        decoded = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if len(decoded) < 12 or sum(1 for c in decoded if c.isprintable() or c in "\n\t") / len(decoded) < 0.9:
        return None
    return decoded


def structural_score(raw: str, clean: str, hidden: int, mixed: int, source: str, depth: int = 0) -> Tuple[float, List[str]]:
    score, reasons = 0.0, []

    def add(weight: float, code: str) -> None:
        nonlocal score
        score = min(1.0, score + weight)
        reasons.append(code)

    if _TEMPLATE_TOKENS.search(clean):
        add(STRONG, "chat_template_tokens")
    if _ROLE_LABEL.search(clean):
        add(MEDIUM, "role_label_line")
    if _FAKE_DELIMITER.search(clean):
        add(MEDIUM, "fake_delimiter")
    if source == "document" and _HIDDEN_MARKUP.search(clean):
        add(MEDIUM, "hidden_markup")
    if any(0xE0000 <= ord(c) <= 0xE007F for c in (raw or "")) or hidden >= 10:
        add(STRONG, "hidden_characters")
    elif hidden >= 3:
        add(MEDIUM, "hidden_characters")
    if mixed:
        add(MEDIUM, "lookalike_letters")
    for match in _MD_EXFIL.finditer(clean):
        if source == "document" or _MD_EXFIL_HINT.search(match.group(0)):
            add(STRONG, "data_leaking_link")
            break

    if depth == 0:
        # Hidden payloads: decode or un-obfuscate them, then look again with the syntactic and structural rules.
        candidates: List[str] = []
        for m in _BASE64_RUN.finditer(clean):
            try:
                text = _printable(base64.b64decode(m.group(0) + "=" * (-len(m.group(0)) % 4), validate=False))
            except (binascii.Error, ValueError):
                text = None
            if text:
                candidates.append(text)
        if len(re.findall(r"%[0-9A-Fa-f]{2}", clean)) >= 3:
            candidates.append(urllib.parse.unquote(clean))
        if _SPACED_LETTERS.search(clean):
            candidates.append(_SPACED_LETTERS.sub(lambda m: re.sub(r"[\s.\-_*]+", "", m.group(0)) + " ", clean))
            if any(p in re.sub(r"[^a-z]", "", clean.lower()) for p in _SQUASH_PHRASES):
                add(STRONG, "spaced_out_attack_words")
        leet = " ".join(
            (t.translate(_LEET) if re.search(r"[a-z]", t, re.I) and re.search(r"[0-9@$]", t) and len(t) >= 5 else t) for t in clean.split()
        )
        if leet != " ".join(clean.split()):
            candidates.append(leet)
        for candidate in candidates:
            c_clean, c_hidden, c_mixed = normalise(candidate)
            syn, _ = syntactic_score(c_clean, source)
            sub, _ = structural_score(candidate, c_clean, c_hidden, c_mixed, source, depth=1)
            if syn >= STRONG or sub >= STRONG:
                add(STRONG, "obfuscated_or_encoded_attack")
                break
    return score, reasons


# --------------------------------------------------------------------------------------------- semantic layer
@lru_cache(maxsize=1)
def _embedder():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(config.INJECTION_EMBEDDING_MODEL)


@lru_cache(maxsize=1)
def _libraries():
    """Embeddings of the attack phrasings (with their category) and of the normal phrasings."""
    model = _embedder()
    attacks = [(cat, p) for cat, group in ATTACKS.items() for p in group]
    attack_vecs = model.encode([p for _, p in attacks], normalize_embeddings=True, show_progress_bar=False)
    benign_vecs = model.encode(BENIGN, normalize_embeddings=True, show_progress_bar=False)
    return [c for c, _ in attacks], attack_vecs, benign_vecs


NO_SEMANTIC = (0.0, 0.0, None)


def semantic_scores(texts: Sequence[str]) -> List[Tuple[float, float, Optional[str]]]:
    """
    For each text: (attack similarity, margin, category) of its most attack-like sentence. Attack similarity is the
    cosine similarity to the nearest known attack phrasing; the margin is how much closer that is than the nearest
    ordinary study phrasing. A question or lesson ABOUT injection sits near the ordinary phrasings, so its margin is
    small even when its attack similarity is high. All sentences of all texts go through the model in one batch.
    """
    try:
        spans, flat = [], []
        for text in texts:
            sentences = [x for x in _sentences(text) if len(x) >= 8]
            if 0 < len(text.strip()) <= 400:
                sentences.append(text.strip())
            spans.append((len(flat), len(sentences)))
            flat.extend(sentences)
        if not flat:
            return [NO_SEMANTIC] * len(texts)
        categories, attack_vecs, benign_vecs = _libraries()
        vectors = _embedder().encode(flat, normalize_embeddings=True, show_progress_bar=False, batch_size=64)
        to_attack = vectors @ attack_vecs.T
        attack_best = to_attack.max(axis=1)
        benign_best = (vectors @ benign_vecs.T).max(axis=1)
        results = []
        for start, count in spans:
            if count == 0:
                results.append(NO_SEMANTIC)
                continue
            row = start + int(attack_best[start : start + count].argmax())
            results.append((float(attack_best[row]), float(attack_best[row] - benign_best[row]), categories[int(to_attack[row].argmax())]))
        return results
    except Exception:  # noqa: BLE001 - a broken model must not take chat or uploads down
        logger.warning("semantic injection check unavailable", exc_info=True)
        return [NO_SEMANTIC] * len(texts)


def semantic_score(text: str) -> Tuple[float, float, Optional[str]]:
    return semantic_scores([text])[0]


def warm_up() -> None:
    """Load the model and the phrase libraries now, so the first chat message or upload is not slow."""
    semantic_score("warm up the injection check")


# --------------------------------------------------------------------------------------------- combining the layers
_QUESTION_OPENERS = {"what", "whats", "why", "how", "when", "where", "who", "which", "does", "do", "did", "is", "are", "was", "were"}
QUESTION_EXTRA = 0.12  # an informational question needs this much more similarity before meaning alone blocks it


def is_informational_question(text: str) -> bool:
    """A plain wh-/yes-no question ("What does the note on page 3 say?"). It asks ABOUT something, it does not command."""
    words = _tokens(text.strip())
    return bool(words) and text.rstrip().endswith("?") and words[0] in _QUESTION_OPENERS


def decide(syn: float, struct: float, attack_sim: float, margin: float, question: bool = False) -> str:
    """"block", "flag" or "clean" from the three layers' scores. Kept separate so it can be tuned and tested alone."""
    form = syn + struct  # evidence from how the text is written, independent of what it means
    attack_like = attack_sim >= config.INJECTION_SEMANTIC_FLAG and margin >= config.INJECTION_MARGIN_FLAG
    clearly_attack = attack_sim >= config.INJECTION_SEMANTIC_BLOCK + (QUESTION_EXTRA if question else 0.0) and margin >= config.INJECTION_MARGIN_BLOCK
    if syn >= STRONG or struct >= STRONG or clearly_attack:
        return "block"
    if attack_like and form >= MEDIUM:
        return "block"  # the meaning and the way it is written agree
    if form >= STRONG:
        return "block"  # two independent medium signals
    if attack_like or form >= MEDIUM:
        return "flag"
    return "clean"


def analyze_many(texts: Sequence[str], source: str = "user") -> List[Verdict]:
    """
    `source` is "user" (chat messages) or "document" (text from an uploaded file). The structural and syntactic layers
    run per text; the semantic layer embeds every sentence of every text in one batch, which is what makes scanning a
    whole document affordable.
    """
    analysed = [bool(t) and len(t.strip()) >= MIN_ANALYSED_CHARS for t in texts]
    cleaned, per_text = [], []
    for text, ok in zip(texts, analysed):
        if not ok:
            cleaned.append("")
            per_text.append(None)
            continue
        clean, hidden, mixed = normalise(text)
        syn, syn_codes = syntactic_score(clean, source)
        struct, struct_codes = structural_score(text, clean, hidden, mixed, source)
        cleaned.append(clean)
        per_text.append((syn, syn_codes, struct, struct_codes))
    semantic = semantic_scores([c for c, ok in zip(cleaned, analysed) if ok])
    semantic_iter = iter(semantic)

    verdicts = []
    for parts in per_text:
        verdict = Verdict()
        if parts is not None:
            syn, syn_codes, struct, struct_codes = parts
            attack_sim, margin, category = next(semantic_iter)
            verdict.syntactic, verdict.structural = round(syn, 2), round(struct, 2)
            verdict.semantic, verdict.margin = round(attack_sim, 3), round(margin, 3)
            verdict.reasons = [f"syntax:{c}" for c in syn_codes] + [f"structure:{c}" for c in struct_codes]
            decision = decide(syn, struct, attack_sim, margin, is_informational_question(clean))
            verdict.blocked, verdict.flagged = decision == "block", decision == "flag"
            attack_like = attack_sim >= config.INJECTION_SEMANTIC_FLAG and margin >= config.INJECTION_MARGIN_FLAG
            if attack_like:
                verdict.reasons.append(f"meaning:{category}")
            scaled = max(0.0, min(1.0, (attack_sim - 0.45) / (config.INJECTION_SEMANTIC_BLOCK - 0.45))) if attack_like else 0.0
            verdict.risk = round(1.0 if verdict.blocked else max(syn, struct, scaled * 0.8), 2)
        verdicts.append(verdict)
    return verdicts


def analyze(text: str, source: str = "user") -> Verdict:
    return analyze_many([text], source)[0]


BLOCK_MESSAGE = "Security Alert: This looks like an attempt to change or extract my instructions, so I can't process it."


def check_message(text: str) -> Tuple[bool, str]:
    """(ok, message) for a learner's chat message."""
    verdict = analyze(text, "user")
    if verdict.blocked:
        logger.warning("blocked a message as prompt injection: %s", ",".join(verdict.reasons) or "meaning")
        return False, BLOCK_MESSAGE
    return True, ""
