"""Unit tests for PromptPackage.render()."""

from app.ai.prompts.package import FewShotExample, PromptPackage, PromptVersion


class TestRender:
    def test_substitutes_template_variables(self) -> None:
        package = PromptPackage(
            name="test",
            version=PromptVersion(major=1),
            system_prompt="You are an extractor.",
            user_prompt_template="Extract commodities from: {document_text}",
        )
        system, user = package.render(document_text="wheat futures rose")

        assert system == "You are an extractor."
        assert user == "Extract commodities from: wheat futures rose"

    def test_prepends_few_shot_examples(self) -> None:
        package = PromptPackage(
            name="test",
            version=PromptVersion(major=1),
            system_prompt="sys",
            user_prompt_template="Extract: {text}",
            few_shot_examples=[FewShotExample(input="corn", output='{"commodity": "corn"}')],
        )
        _, user = package.render(text="soybeans")

        assert "Example input:\ncorn" in user
        assert "Example output:\n{\"commodity\": \"corn\"}" in user
        assert user.endswith("Extract: soybeans")

    def test_no_examples_means_no_example_preamble(self) -> None:
        package = PromptPackage(
            name="test",
            version=PromptVersion(major=1),
            system_prompt="sys",
            user_prompt_template="Extract: {text}",
        )
        _, user = package.render(text="soybeans")
        assert user == "Extract: soybeans"


class TestPromptVersion:
    def test_str_formats_as_major_dot_minor(self) -> None:
        assert str(PromptVersion(major=2, minor=3)) == "2.3"

    def test_minor_defaults_to_zero(self) -> None:
        assert str(PromptVersion(major=1)) == "1.0"
