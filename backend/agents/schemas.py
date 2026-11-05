"""Pydantic schemas for every structured decision an agent makes. Used as Gemini response schemas
and re-validated in Python before anything acts on them."""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

Intent = Literal["qa", "summary", "key_points", "eli5", "glossary", "quiz", "other"]
Action = Literal["retrieve", "generate", "summarize", "quiz", "clarify", "reject", "finish"]
Style = Literal["normal", "simple", "eli5", "key_points", "glossary", "examples"]
Goal = Literal["explain_concept", "find_fact", "compare_concepts", "overview", "practice", "review_progress", "other"]


class SupervisorDecision(BaseModel):
    """What should happen next. The Supervisor never writes the final answer."""

    intent: Intent
    goal: Goal
    needs_retrieval: bool
    response_style: Style
    next_action: Action
    confidence: float = Field(ge=0.0, le=1.0)
    standalone_query: str = Field(description="The user's request rewritten so it makes sense without the chat history")
    clarifying_question: str = Field(default="", description="Only when next_action is clarify")
    reasoning: str = Field(description="One short sentence explaining the decision")


class RetrievalDecision(BaseModel):
    """Which retrieval tool to use next, and with what arguments."""

    strategy: Literal["search_document", "search_topic", "search_similar_chunks", "get_neighbor_chunks", "search_by_metadata"]
    query: str = Field(description="Search text; must differ from queries already tried")
    topic: str = Field(default="", description="Topic phrase for search_topic")
    anchor_chunk_index: int = Field(default=-1, description="Chunk index from current evidence for similar/neighbor search, else -1")
    page: int = Field(default=-1, description="Page number for search_by_metadata, else -1")
    reasoning: str


class EvidenceEvaluation(BaseModel):
    relevant: bool
    sufficient: bool
    coverage: float = Field(ge=0.0, le=1.0)
    missing_information: List[str]
    recommended_action: Literal["use_evidence", "retrieve_again", "rewrite_query", "answer_not_supported"]
    suggested_query: str = Field(default="", description="A better search query if another attempt is recommended")


class TutorOutput(BaseModel):
    action: Literal["answer", "need_more_evidence", "insufficient_evidence"]
    answer: str = Field(default="", description="The explanation for the learner (empty unless action is answer)")
    used_chunk_indices: List[int] = Field(description="Indices of the evidence chunks the answer relies on")
    missing_information: List[str] = Field(default_factory=list)
    style_used: Style = "normal"
    follow_up_question: str = ""


class CriticEvaluation(BaseModel):
    grounded: bool
    relevant: bool
    complete: bool
    unsupported_claims: List[str]
    missing_information: List[str]
    contradictions: List[str]
    revision_required: bool
    recommended_action: Literal["finish", "revise", "retrieve_again"]


class QuizQuestion(BaseModel):
    question: str
    options: List[str]
    correct_answer_index: int
    topic: str
    difficulty: Literal["simple", "medium", "high"]
    explanation: str
    source_quote: str = Field(description="A short verbatim quote from the provided excerpts that supports the correct answer")


class QuizEvaluation(BaseModel):
    """Deterministic scoring record produced by Python, never by an LLM."""

    correct: bool
    selected_index: int
    correct_index: int
    phase_before: str
    phase_after: str
    phase_transitioned: bool
    overall_accuracy: float



class ToolError(BaseModel):
    ok: bool = False
    error: str
    tool: Optional[str] = None
