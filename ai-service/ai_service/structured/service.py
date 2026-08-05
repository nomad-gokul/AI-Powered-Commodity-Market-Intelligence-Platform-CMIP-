"""StructuredOutputService: LLMResponse -> Pydantic validation -> typed
object, with automatic retry-on-invalid.

Providers never validate Pydantic models (see LLMProvider.generate's
docstring) - this is the one place a response's content is parsed against
a schema, and the only path any caller should use to get a typed object
back from an LLM call. A manual `json.loads(response.content)` in
application code is exactly what this class exists to make unnecessary.
"""

from typing import TypeVar

from pydantic import BaseModel, ValidationError
from shared.ai_contracts import LLMMessage, LLMRequest, LLMResponse, LLMUsage
from shared.ai_exceptions import StructuredOutputError

from ai_service.client.llm_client import LLMClient

T = TypeVar("T", bound=BaseModel)


class StructuredOutputService:
    def __init__(self, llm_client: LLMClient) -> None:
        self._client = llm_client

    async def generate_structured(
        self,
        request: LLMRequest,
        response_model: type[T],
        *,
        max_retries: int = 2,
        correlation_id: str | None = None,
    ) -> T:
        """Call `request` and validate the result against `response_model`.

        On invalid JSON or a schema mismatch, feeds the model back its own
        (invalid) response plus the validation error and asks it to
        correct itself, up to `max_retries` additional attempts, before
        raising StructuredOutputError.
        """
        result, _response = await self._generate_and_validate(
            request, response_model, max_retries=max_retries, correlation_id=correlation_id
        )
        return result

    async def generate_structured_with_usage(
        self,
        request: LLMRequest,
        response_model: type[T],
        *,
        max_retries: int = 2,
        correlation_id: str | None = None,
    ) -> tuple[T, LLMUsage]:
        """Identical to generate_structured(), but also returns the
        successful attempt's LLMUsage - added for callers that aggregate
        token usage across multiple structured calls (see
        app.modules.extraction's agents, which sum this into
        extraction_runs.token_usage). Deliberately a separate method
        rather than changing generate_structured()'s return type: this
        class is Phase 3.1, frozen, and existing callers depend on
        generate_structured() returning exactly `T`.
        """
        result, response = await self._generate_and_validate(
            request, response_model, max_retries=max_retries, correlation_id=correlation_id
        )
        return result, response.usage

    async def _generate_and_validate(
        self,
        request: LLMRequest,
        response_model: type[T],
        *,
        max_retries: int,
        correlation_id: str | None,
    ) -> tuple[T, LLMResponse]:
        schema = response_model.model_json_schema()
        working_request = request.model_copy(update={"response_format": schema})
        last_error = "no content returned"

        for attempt in range(max_retries + 1):
            response = await self._client.generate(working_request, correlation_id=correlation_id)
            content = response.content

            if content is not None:
                try:
                    return response_model.model_validate_json(content), response
                except ValidationError as exc:
                    last_error = str(exc)
            else:
                last_error = "response had no content"

            if attempt < max_retries:
                correction = (
                    f"Your previous response was invalid: {last_error}. "
                    "Return ONLY valid JSON matching the required schema, with no extra commentary."
                )
                working_request = working_request.model_copy(
                    update={
                        "messages": [
                            *working_request.effective_messages(),
                            LLMMessage(role="assistant", content=content or ""),
                            LLMMessage(role="user", content=correction),
                        ],
                        "system_prompt": None,
                        "user_prompt": None,
                    }
                )

        raise StructuredOutputError(
            f"{response_model.__name__} validation failed after "
            f"{max_retries + 1} attempt(s): {last_error}",
            details={"model": response_model.__name__, "attempts": max_retries + 1},
        )
