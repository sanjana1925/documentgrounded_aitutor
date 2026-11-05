import operator
from dataclasses import dataclass
from typing import Annotated, Any, Dict, List, TypedDict

from backend.agents.critic import CriticAgent
from backend.agents.guide import GuideAgent
from backend.agents.quiz import QuizAgent
from backend.agents.retrieval import EvidenceEvaluator, RetrievalAgent
from backend.agents.supervisor import SupervisorAgent
from backend.agents.tutor import TutorAgent
from backend.services.learner_state_service import LearnerStateService
from backend.services.retrieval_service import RetrievalService
from backend.tools.base import ToolRegistry


class GraphState(TypedDict, total=False):
    # request (set by Python from the validated API request)
    message: str
    session_id: str
    document_id: str
    history: List[Dict[str, str]]
    conversation_summary: str
    mode_override: str
    quiz_pending: bool
    # supervisor
    decision: Dict[str, Any]
    standalone_query: str
    mode: str
    # retrieval loop
    evidence: List[Dict[str, Any]]
    tried: List[Dict[str, str]]
    last_eval: Dict[str, Any]
    search_query: str
    retrieval_exhausted: bool
    # tutor / critic loop
    draft: Dict[str, Any]
    draft_status: str
    critic: Dict[str, Any]
    critic_action: str
    critic_feedback: str
    generation_attempts: int
    # outputs
    reply: str
    retrieved_chunks: List[str]
    source_chunk_ids: List[int]
    quiz_details: Dict[str, Any]
    quiz_score: int
    quiz_total: int
    stop_reason: str
    llm_error: Dict[str, Any]
    trace: Annotated[List[Dict[str, Any]], operator.add]


@dataclass
class Deps:
    retrieval: RetrievalService
    learner: LearnerStateService
    registry: ToolRegistry
    supervisor: SupervisorAgent
    retrieval_agent: RetrievalAgent
    evaluator: EvidenceEvaluator
    tutor: TutorAgent
    critic: CriticAgent
    quiz: QuizAgent
    guide: GuideAgent
