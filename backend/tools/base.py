"""
Tool layer shared by all agents.

Every tool has typed, validated input (extra fields forbidden - a model can never pass a
session/document id), a typed ToolResult, budget accounting, and error handling. Agents only get the tools on their allowlist.
"""
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Type

from pydantic import BaseModel, ConfigDict, ValidationError

from backend.budget import Budget, BudgetExceeded
from backend.services.retrieval_service import Scope

logger = logging.getLogger("tutor.tools")


class ToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolResult(BaseModel):
    ok: bool
    tool: str
    chunks: List[Dict[str, Any]] = []
    data: Dict[str, Any] = {}
    error: str = ""


@dataclass
class ToolContext:
    scope: Scope  # built by Python from the authenticated request, never by the model
    budget: Budget


@dataclass
class ToolSpec:
    name: str
    description: str
    args_model: Type[ToolArgs]
    fn: Callable[[ToolContext, Any], ToolResult]


class ToolRegistry:
    def __init__(self, specs: Iterable[ToolSpec]):
        self._specs: Dict[str, ToolSpec] = {s.name: s for s in specs}

    def names(self) -> List[str]:
        return list(self._specs)

    def subset(self, names: Iterable[str]) -> "ToolRegistry":
        wanted = list(names)
        missing = [n for n in wanted if n not in self._specs]
        if missing:
            raise KeyError(f"unknown tools: {missing}")
        return ToolRegistry(self._specs[n] for n in wanted)

    def describe(self) -> str:
        lines = []
        for spec in self._specs.values():
            fields = ", ".join(spec.args_model.model_fields) or "no arguments"
            lines.append(f"- {spec.name}({fields}): {spec.description}")
        return "\n".join(lines)

    def run(self, name: str, ctx: ToolContext, raw_args: Dict[str, Any]) -> ToolResult:
        spec = self._specs.get(name)
        if spec is None:
            return ToolResult(ok=False, tool=name, error="unknown or disallowed tool")
        try:
            args = spec.args_model.model_validate(raw_args or {})
        except ValidationError as exc:
            return ToolResult(ok=False, tool=name, error=f"invalid arguments: {exc.errors()[0]['msg']}")
        try:
            ctx.budget.charge_tool()
        except BudgetExceeded as exc:
            return ToolResult(ok=False, tool=name, error=exc.reason)

        def _execute(tool_args: Dict[str, Any]) -> Dict[str, Any]:
            return spec.fn(ctx, args).model_dump()

        try:
            out = _execute(args.model_dump())
            return ToolResult.model_validate(out)
        except Exception as exc:  # noqa: BLE001 - a failing tool is an observation, not a crash
            logger.warning("tool %s failed: %s", name, type(exc).__name__)
            return ToolResult(ok=False, tool=name, error=f"{type(exc).__name__}: tool execution failed")
