"""Input guardrails - deterministic, run before any agent sees a request."""
import re
from typing import Tuple

from backend import config
from backend.guardrails.injection import check_message

MAX_INPUT_LENGTH = 4000

PROMPT_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|above)\s+instructions",
    r"system\s+prompt",
    r"reveal\s+(your\s+)?instructions",
    r"you\s+are\s+now\s+a",
    r"jailbreak",
    r"disregard\s+(the\s+)?system",
    r"repeat\s+the\s+words\s+above",
    r"developer\s+mode",
    r"act\s+as\s+(an?\s+)?(unrestricted|jailbroken|dan)\b",
    r"forget\s+(all\s+|everything\s+)?(your|the|previous)\s+(instructions|rules|training)",
]

# Requests to expose internal instructions. Anchored on "your"/"the system" so ordinary
# study questions ("what are the rules for balancing equations?") are not blocked.
SYSTEM_PROMPT_EXTRACTION_PATTERNS = [
    r"\b(reveal|show|print|display|repeat|leak|dump|output)\b.{0,30}\b(your|the\s+system|the\s+assistant'?s|hidden|initial|original)\b.{0,20}\b(instructions|prompt|rules|guidelines)\b",
    r"\bwhat\s+(are|is|were)\s+your\s+(instructions|rules|guidelines|prompt)\b",
]

_SESSION_RE = re.compile(config.SESSION_ID_PATTERN)
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def validate_input(message: str) -> Tuple[bool, str]:
    """Validates user input: empty, malformed, oversized, prompt injection, prompt extraction."""
    if not message or not message.strip():
        return False, "Input cannot be empty."

    if _CONTROL_CHARS.search(message):
        return False, "Input contains unsupported control characters."

    if len(message) > MAX_INPUT_LENGTH:
        return False, f"Input exceeds maximum allowed length of {MAX_INPUT_LENGTH} characters."

    lowered = message.lower()
    for pattern in PROMPT_INJECTION_PATTERNS:
        if re.search(pattern, lowered):
            return False, "Security Alert: Input contains restricted prompt injection patterns."

    for pattern in SYSTEM_PROMPT_EXTRACTION_PATTERNS:
        if re.search(pattern, lowered):
            return False, "Security Alert: Requests for internal instructions are not supported."

    # The keyword checks above are cheap but easy to reword around; this adds the structure and meaning checks.
    return check_message(message)


def validate_request_identity(session_id: str, filename: str) -> Tuple[bool, str]:
    """Session / document identifiers come from the client, so they are shape-checked here."""
    if not _SESSION_RE.match(session_id or ""):
        return False, "Invalid session id."
    if not filename or len(filename) > config.MAX_FILENAME_LENGTH:
        return False, "Invalid document name."
    if "/" in filename or "\\" in filename or _CONTROL_CHARS.search(filename):
        return False, "Invalid document name."
    return True, ""
