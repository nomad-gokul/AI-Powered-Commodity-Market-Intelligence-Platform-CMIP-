"""PromptPackage: the unit of prompt content passed into an LLMRequest.

Moved out of ai-service.prompts.package verbatim (Pre-Phase 5 AI Service
Extraction): business modules construct PromptPackage instances directly
(see app.modules.extraction.prompts) and pass them to PromptRegistry.register(),
so the shape is a shared contract - the registry (ai-service, a real
lookup/versioning implementation) is what stays out of shared.
"""

from typing import Any

from pydantic import BaseModel, Field


class FewShotExample(BaseModel):
    input: str
    output: str


class PromptMetadata(BaseModel):
    author: str | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None


class PromptVersion(BaseModel):
    """Identifies one revision of a prompt's wording, so an extraction_run
    can record exactly which version produced its output and a reprocess
    can pin to it deliberately rather than silently picking up whatever
    the prompt says today."""

    major: int
    minor: int = 0

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}"


class PromptPackage(BaseModel):
    name: str
    version: PromptVersion
    system_prompt: str
    user_prompt_template: str
    few_shot_examples: list[FewShotExample] = Field(default_factory=list)
    expected_schema: dict[str, Any] | None = None
    metadata: PromptMetadata = Field(default_factory=PromptMetadata)

    def render(self, **kwargs: Any) -> tuple[str, str]:
        """Substitute `kwargs` into user_prompt_template via str.format,
        prefixed with any few-shot examples, and return
        (system_prompt, user_prompt) ready to pass to LLMRequest."""
        rendered_user = self.user_prompt_template.format(**kwargs)
        if self.few_shot_examples:
            examples_text = "\n\n".join(
                f"Example input:\n{example.input}\nExample output:\n{example.output}"
                for example in self.few_shot_examples
            )
            rendered_user = f"{examples_text}\n\n{rendered_user}"
        return self.system_prompt, rendered_user
