"""Shared test doubles for the OpenAI-shaped chat.completions provider
tests (Groq, OpenAI). Not a production module - lives under tests/ only.
"""

from types import SimpleNamespace

import httpx


def fake_completion(
    *,
    content: str | None = "hello",
    finish_reason: str = "stop",
    tool_calls: list[object] | None = None,
) -> SimpleNamespace:
    message = SimpleNamespace(content=content, tool_calls=tool_calls or [])
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    return SimpleNamespace(choices=[choice], usage=usage)


def fake_response(status_code: int) -> httpx.Response:
    return httpx.Response(status_code=status_code, request=httpx.Request("POST", "http://test"))


def fake_stream_chunk(*, delta: str, finish_reason: str | None = None) -> SimpleNamespace:
    choice = SimpleNamespace(delta=SimpleNamespace(content=delta), finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


class FakeAsyncStream:
    """An async-iterable of fake_stream_chunk()s, mimicking the SDK's
    AsyncStream[ChatCompletionChunk] return type from create(stream=True)."""

    def __init__(self, chunks: list[SimpleNamespace]) -> None:
        self._chunks = chunks

    def __aiter__(self) -> "FakeAsyncStream":
        self._iter = iter(self._chunks)
        return self

    async def __anext__(self) -> SimpleNamespace:
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration from None
