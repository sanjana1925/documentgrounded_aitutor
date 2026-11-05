"""Read-only views of the learner's recorded performance. Numbers come from Python state, never from an LLM."""
from typing import Callable, List

from pydantic import Field

from backend.services.retrieval_service import Scope
from backend.tools.base import ToolArgs, ToolContext, ToolResult, ToolSpec
from backend.domain.quiz_engine import LearnerState


class HistoryArgs(ToolArgs):
    limit: int = Field(default=10, ge=1, le=50)


def build_learning_tools(get_state: Callable[[Scope], LearnerState]) -> List[ToolSpec]:
    def get_quiz_history(ctx: ToolContext, args: HistoryArgs) -> ToolResult:
        s = get_state(ctx.scope)
        return ToolResult(ok=True, tool="get_quiz_history", data={"asked_questions": s.asked_questions[-args.limit :]})

    return [
        ToolSpec("get_quiz_history", "recently asked quiz questions", HistoryArgs, get_quiz_history),
    ]
