"""Static model metadata: what models exist per provider, their context
windows, capabilities, and approximate pricing.

Pricing is best-effort reference data captured at implementation time from
each vendor's public pricing page, NOT a billing-accurate source of truth -
vendors change prices without notice. It exists so app.ai.observability can
produce a rough estimated_cost_usd per call for dashboards and budgeting,
not for invoicing. Treat PRICING_LAST_VERIFIED as a prompt to re-check
these numbers, not a guarantee they're still current.
"""

from dataclasses import dataclass, field

from app.ai.providers.base import ProviderCapabilities

PRICING_LAST_VERIFIED = "2026-08"


@dataclass(frozen=True, slots=True)
class ProviderModelInfo:
    provider: str
    model_id: str
    context_window: int
    max_output_tokens: int
    capabilities: ProviderCapabilities
    input_price_per_million_tokens: float | None
    """USD per 1,000,000 input tokens. None means unknown/not applicable
    (e.g. a self-hosted Ollama model has no per-token vendor cost)."""
    output_price_per_million_tokens: float | None
    aliases: tuple[str, ...] = field(default_factory=tuple)
    deprecated: bool = False


GROQ_CAPABILITIES = ProviderCapabilities(
    supports_streaming=True,
    supports_tools=True,
    supports_json_schema=True,
    supports_function_calling=True,
    max_context=131_072,
    max_output_tokens=32_768,
)

CLAUDE_CAPABILITIES = ProviderCapabilities(
    supports_streaming=True,
    supports_tools=True,
    supports_json_schema=False,  # no native mode; structured output goes via tool-forcing
    supports_function_calling=True,
    supports_multimodal=True,
    supports_vision=True,
    supports_reasoning=True,
    max_context=200_000,
    max_output_tokens=64_000,
)

OPENAI_CAPABILITIES = ProviderCapabilities(
    supports_streaming=True,
    supports_tools=True,
    supports_json_schema=True,
    supports_function_calling=True,
    supports_multimodal=True,
    supports_vision=True,
    max_context=128_000,
    max_output_tokens=16_384,
)

OLLAMA_CAPABILITIES = ProviderCapabilities(
    supports_streaming=True,
    supports_tools=False,
    supports_json_schema=True,  # via format="json"; best-effort per model, not a hard constraint
    supports_function_calling=False,
    max_context=128_000,
    max_output_tokens=8_192,
)

MODELS: tuple[ProviderModelInfo, ...] = (
    # --- Groq (development default) ---
    ProviderModelInfo(
        provider="groq",
        model_id="llama-3.3-70b-versatile",
        context_window=131_072,
        max_output_tokens=32_768,
        capabilities=GROQ_CAPABILITIES,
        input_price_per_million_tokens=0.59,
        output_price_per_million_tokens=0.79,
    ),
    ProviderModelInfo(
        provider="groq",
        model_id="deepseek-r1-distill-llama-70b",
        context_window=131_072,
        max_output_tokens=131_072,
        capabilities=ProviderCapabilities(
            supports_streaming=True,
            supports_tools=True,
            supports_json_schema=True,
            supports_function_calling=True,
            supports_reasoning=True,
            max_context=131_072,
            max_output_tokens=131_072,
        ),
        input_price_per_million_tokens=0.75,
        output_price_per_million_tokens=0.99,
    ),
    ProviderModelInfo(
        provider="groq",
        model_id="qwen/qwen3-32b",
        context_window=131_072,
        max_output_tokens=40_960,
        capabilities=GROQ_CAPABILITIES,
        input_price_per_million_tokens=0.29,
        output_price_per_million_tokens=0.59,
    ),
    ProviderModelInfo(
        provider="groq",
        model_id="llama-3.1-8b-instant",
        context_window=131_072,
        max_output_tokens=8_192,
        capabilities=GROQ_CAPABILITIES,
        input_price_per_million_tokens=0.05,
        output_price_per_million_tokens=0.08,
        aliases=("llama-3.1-8b",),
    ),
    # --- Claude ---
    ProviderModelInfo(
        provider="claude",
        model_id="claude-sonnet-5",
        context_window=200_000,
        max_output_tokens=64_000,
        capabilities=CLAUDE_CAPABILITIES,
        input_price_per_million_tokens=3.00,
        output_price_per_million_tokens=15.00,
    ),
    ProviderModelInfo(
        provider="claude",
        model_id="claude-haiku-4-5-20251001",
        context_window=200_000,
        max_output_tokens=64_000,
        capabilities=CLAUDE_CAPABILITIES,
        input_price_per_million_tokens=1.00,
        output_price_per_million_tokens=5.00,
        aliases=("claude-haiku-4-5",),
    ),
    # --- OpenAI ---
    ProviderModelInfo(
        provider="openai",
        model_id="gpt-4o-mini",
        context_window=128_000,
        max_output_tokens=16_384,
        capabilities=OPENAI_CAPABILITIES,
        input_price_per_million_tokens=0.15,
        output_price_per_million_tokens=0.60,
    ),
    ProviderModelInfo(
        provider="openai",
        model_id="gpt-4o",
        context_window=128_000,
        max_output_tokens=16_384,
        capabilities=OPENAI_CAPABILITIES,
        input_price_per_million_tokens=2.50,
        output_price_per_million_tokens=10.00,
    ),
    # --- Ollama (self-hosted; no vendor cost) ---
    ProviderModelInfo(
        provider="ollama",
        model_id="llama3.1",
        context_window=128_000,
        max_output_tokens=8_192,
        capabilities=OLLAMA_CAPABILITIES,
        input_price_per_million_tokens=None,
        output_price_per_million_tokens=None,
    ),
    ProviderModelInfo(
        provider="ollama",
        model_id="qwen2.5",
        context_window=32_768,
        max_output_tokens=8_192,
        capabilities=OLLAMA_CAPABILITIES,
        input_price_per_million_tokens=None,
        output_price_per_million_tokens=None,
    ),
)

DEFAULT_MODEL_BY_PROVIDER: dict[str, str] = {
    "groq": "llama-3.3-70b-versatile",
    "claude": "claude-sonnet-5",
    "openai": "gpt-4o-mini",
    "ollama": "llama3.1",
}
