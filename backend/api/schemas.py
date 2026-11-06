from typing import Any, Dict, List, Optional

from pydantic import BaseModel, field_validator


class IngestResponse(BaseModel):
    filename: str
    chunks_added: int
    flagged_chunks: int = 0  # passages set aside because they look like instructions aimed at the AI


class AgentRequest(BaseModel):
    message: str
    filename: str
    session_id: str = "default"
    mode: str = ""  # optional explicit override; empty => the Supervisor Agent decides
    reset_quiz: bool = False
    history: List[Dict[str, str]] = []  # recent {role, content} turns, for follow-up context

    @field_validator("history", mode="before")
    @classmethod
    def keep_role_and_content(cls, value):
        # Clients may send whole chat messages (e.g. with a "sources" list); only role and content are used.
        if not isinstance(value, list):
            return value
        return [
            {"role": str(item.get("role", "user")), "content": str(item.get("content", ""))}
            for item in value
            if isinstance(item, dict)
        ]


class AgentResponse(BaseModel):
    mode: str
    reply: str
    retrieved_chunks: List[str] = []
    search_query: str = ""
    retrieval_attempts: int = 0
    generation_attempts: int = 0
    quiz_score: int = 0
    quiz_total: int = 0
    quiz_details: Optional[Dict[str, Any]] = None
    agent_trace: Optional[Dict[str, Any]] = None  # supervisor decision, tool calls, evaluations, budget usage
