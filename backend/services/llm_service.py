"""
The single place that talks to Gemini.

Agents depend on the small `LLM` protocol (text / structured), so tests can inject a scripted
fake. Every call is charged against the request Budget.
"""
import logging
import time
from typing import Any, Dict, Optional, Protocol, Type, TypeVar

import httpx
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, ValidationError

from backend.budget import Budget, BudgetExceeded

T = TypeVar("T", bound=BaseModel)
logger = logging.getLogger("tutor.llm")
MIN_REQUEST_SECONDS = 10.0


class LLMError(Exception):
    """The model provider failed in a way the request cannot recover from."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class LLM(Protocol):
    def text(self, prompt: str, system: str, *, budget: Budget, name: str) -> str: ...

    def structured(self, schema: Type[T], prompt: str, system: str, *, budget: Budget, name: str) -> Optional[T]: ...


def _generate(client, model: str, prompt: str, system: str, schema_name: str, response_schema, timeout_s: float):
    config_kwargs: Dict[str, Any] = {
        "system_instruction": system,
        "http_options": types.HttpOptions(timeout=int(max(1.0, timeout_s) * 1000)),
        "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
    }
    if response_schema is not None:
        config_kwargs["response_mime_type"] = "application/json"
        config_kwargs["response_schema"] = response_schema
    response = client.models.generate_content(
        model=model, contents=prompt, config=types.GenerateContentConfig(**config_kwargs)
    )
    outputs: Dict[str, Any] = {"text": response.text or ""}
    usage = getattr(response, "usage_metadata", None)
    if usage is not None and getattr(usage, "total_token_count", None) is not None:
        outputs["usage_metadata"] = {
            "input_tokens": getattr(usage, "prompt_token_count", None) or 0,
            "output_tokens": getattr(usage, "candidates_token_count", None) or 0,
            "total_tokens": usage.total_token_count,
        }
    return outputs


class GeminiLLM:
    def __init__(self, client, model: str):
        self.client = client
        self.model = model

    def _call(self, prompt: str, system: str, response_schema, *, budget: Budget, name: str) -> str:
        budget.charge_llm()
        max_attempts = 4
        for attempt in range(1, max_attempts + 1):
            remaining = budget.remaining_seconds()
            # Gemini rejects a request deadline under 10 s (HTTP 400), so a call that cannot get that long is a
            # time-budget stop, not a model failure.
            if remaining <= MIN_REQUEST_SECONDS:
                raise BudgetExceeded("time_budget_exceeded")
            try:
                out = _generate(
                    self.client,
                    self.model,
                    prompt,
                    system,
                    name,
                    response_schema,
                    min(remaining, 30.0),
                )
                return out["text"]
            except (httpx.TransportError, TimeoutError) as exc:
                if attempt == max_attempts:
                    raise LLMError(503, "Could not reach the AI model. Please try again.") from exc
                time.sleep(min(2**attempt, max(0.0, budget.remaining_seconds() - 2)))
            except genai_errors.ServerError as exc:
                if attempt == max_attempts:
                    raise LLMError(503, "The AI model is temporarily unavailable. Please try again.") from exc
                time.sleep(min(2**attempt, max(0.0, budget.remaining_seconds() - 2)))
            except genai_errors.ClientError as exc:
                if exc.code == 429:
                    if attempt == max_attempts:
                        raise LLMError(429, "Gemini API quota exceeded for now. Please wait and try again later.") from exc
                    time.sleep(min(10, max(0.0, budget.remaining_seconds() - 2)))
                else:
                    logger.warning("model rejected call %s (%s): %s", name, exc.code, str(getattr(exc, "message", exc))[:300])
                    raise LLMError(502, f"The AI model rejected the request ({exc.code}).") from exc
        raise LLMError(503, "The AI model is temporarily unavailable.")

    def text(self, prompt: str, system: str, *, budget: Budget, name: str) -> str:
        return self._call(prompt, system, None, budget=budget, name=name)

    def structured(self, schema: Type[T], prompt: str, system: str, *, budget: Budget, name: str) -> Optional[T]:
        """Structured output validated by Pydantic. One repair retry on malformed output, then None."""
        for _ in range(2):
            raw = self._call(prompt, system, schema, budget=budget, name=name)
            try:
                return schema.model_validate_json(raw)
            except (ValidationError, ValueError):
                prompt = f"{prompt}\n\nYour previous reply was not valid JSON for the required schema. Reply with valid JSON only."
                if budget.llm_calls >= budget.max_llm_calls:
                    break
        return None
