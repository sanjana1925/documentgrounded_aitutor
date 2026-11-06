"""
Adaptive Quiz Engine for the AI Tutor Platform.
Implements a 3-phase deterministic difficulty controller (SIMPLE -> MEDIUM -> HIGH),
topic performance tracking, duplicate prevention, and question generation.
"""
import json
import random
from typing import Dict, Any, List, Optional, Tuple
from pydantic import BaseModel, Field

from backend.guardrails import validate_quiz_question

SIMPLE_BENCHMARK = 70.0
MEDIUM_BENCHMARK = 70.0
SIMPLE_REQUIRED_QUESTIONS = 15
MEDIUM_CHECK_INTERVAL = 5
WEAK_TOPIC_THRESHOLD = 60.0
MIN_TOPIC_ATTEMPTS = 2


class TopicStats(BaseModel):
    attempts: int = 0
    correct: int = 0
    accuracy: float = 0.0


class LearnerState(BaseModel):
    session_id: str
    filename: str
    current_phase: str = "SIMPLE"  # SIMPLE, MEDIUM, HIGH
    phase_question_count: int = 0
    total_attempted: int = 0
    total_correct: int = 0
    simple_attempted: int = 0
    simple_correct: int = 0
    medium_attempted: int = 0
    medium_correct: int = 0
    high_attempted: int = 0
    high_correct: int = 0
    topic_stats: Dict[str, TopicStats] = Field(default_factory=dict)
    asked_questions: List[str] = Field(default_factory=list)
    current_question: Optional[Dict[str, Any]] = None
    quiz_complete: bool = False  # the 15-question SIMPLE round ended below the benchmark

    def get_overall_accuracy(self) -> float:
        return (self.total_correct / self.total_attempted * 100.0) if self.total_attempted > 0 else 0.0

    def get_simple_accuracy(self) -> float:
        return (self.simple_correct / self.simple_attempted * 100.0) if self.simple_attempted > 0 else 0.0

    def get_medium_accuracy(self) -> float:
        return (self.medium_correct / self.medium_attempted * 100.0) if self.medium_attempted > 0 else 0.0

    def get_high_accuracy(self) -> float:
        return (self.high_correct / self.high_attempted * 100.0) if self.high_attempted > 0 else 0.0

    def get_weak_topics(self) -> List[str]:
        weak = []
        for topic, stats in self.topic_stats.items():
            if stats.attempts >= MIN_TOPIC_ATTEMPTS and stats.accuracy < WEAK_TOPIC_THRESHOLD:
                weak.append(topic)
        return weak

    def get_strong_topics(self) -> List[str]:
        strong = []
        for topic, stats in self.topic_stats.items():
            if stats.attempts >= MIN_TOPIC_ATTEMPTS and stats.accuracy >= 70.0:
                strong.append(topic)
        return strong


def record_quiz_answer(state: LearnerState, is_correct: bool, topic: str, question_str: str) -> Dict[str, Any]:
    """
    Updates the learner state deterministically after a quiz response,
    evaluating phase progression and updating topic analytics.
    """
    state.total_attempted += 1
    state.phase_question_count += 1
    if is_correct:
        state.total_correct += 1

    if state.current_phase == "SIMPLE":
        state.simple_attempted += 1
        if is_correct:
            state.simple_correct += 1
    elif state.current_phase == "MEDIUM":
        state.medium_attempted += 1
        if is_correct:
            state.medium_correct += 1
    elif state.current_phase == "HIGH":
        state.high_attempted += 1
        if is_correct:
            state.high_correct += 1

    # Update topic stats
    t_stats = state.topic_stats.setdefault(topic, TopicStats())
    t_stats.attempts += 1
    if is_correct:
        t_stats.correct += 1
    t_stats.accuracy = (t_stats.correct / t_stats.attempts) * 100.0

    if question_str and question_str not in state.asked_questions:
        state.asked_questions.append(question_str)

    phase_transitioned = False
    old_phase = state.current_phase

    # Deterministic Phase Progression Logic
    if state.current_phase == "SIMPLE":
        if state.phase_question_count >= SIMPLE_REQUIRED_QUESTIONS:
            simple_acc = state.get_simple_accuracy()
            if simple_acc >= SIMPLE_BENCHMARK:
                state.current_phase = "MEDIUM"
                state.phase_question_count = 0
                phase_transitioned = True
            else:
                state.quiz_complete = True  # the round is exactly 15 questions: never a 16th
    elif state.current_phase == "MEDIUM":
        if state.phase_question_count >= MEDIUM_CHECK_INTERVAL:
            medium_acc = state.get_medium_accuracy()
            if medium_acc >= MEDIUM_BENCHMARK:
                state.current_phase = "HIGH"
                state.phase_question_count = 0
                phase_transitioned = True

    state.current_question = None

    return {
        "is_correct": is_correct,
        "old_phase": old_phase,
        "current_phase": state.current_phase,
        "phase_transitioned": phase_transitioned,
        "weak_topics": state.get_weak_topics(),
        "overall_accuracy": round(state.get_overall_accuracy(), 1),
    }


PHASE_GUIDANCE = {
    "SIMPLE": "Generate a SIMPLE question testing basic recall, definitions, or fundamental terms directly stated in the document.",
    "MEDIUM": "Generate a MEDIUM question testing conceptual understanding, application, or relationships between concepts.",
    "HIGH": "Generate a HIGH difficulty question testing multi-step reasoning, critical analysis, or complex scenario application.",
}
QUIZ_JSON_INSTRUCTION = (
    "Return ONLY a JSON object with this exact schema:\n"
    "{\n"
    '  "question": "string",\n'
    '  "options": ["option 0", "option 1", "option 2", "option 3"],\n'
    '  "correct_answer_index": integer (0 to 3),\n'
    '  "topic": "string (main topic/concept name)",\n'
    '  "difficulty": "simple" | "medium" | "high",\n'
    '  "explanation": "short explanation referencing the document"\n'
    "}"
)


def build_quiz_prompt(phase: str, context: str, weak_topics: List[str], asked_questions: List[str]) -> str:
    """Builds the instruction prompt for generating a grounded quiz question."""
    weak_note = ""
    if weak_topics:
        weak_note = f"\nTarget the question on one of these identified weak topics: {', '.join(weak_topics)}."

    asked_note = ""
    if asked_questions:
        recent = asked_questions[-10:]
        asked_note = f"\nDo NOT repeat or duplicate these previous questions:\n" + "\n".join(f"- {q}" for q in recent)

    phase_guidance = PHASE_GUIDANCE.get(phase, "Generate a simple recall question.")

    return (
        f"Document Excerpts:\n{context}\n\n"
        f"Difficulty Level: {phase}\n"
        f"Guidance: {phase_guidance}{weak_note}{asked_note}\n\n"
        + QUIZ_JSON_INSTRUCTION
    )
