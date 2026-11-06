"""Retrieval guardrails - the safe fallback message when the document does not support an answer."""

NOT_SUPPORTED_MESSAGE = "I couldn't find enough information about that in the uploaded document."


def get_grounding_fallback() -> str:
    """Standard reply when the document does not contain enough evidence."""
    return NOT_SUPPORTED_MESSAGE

