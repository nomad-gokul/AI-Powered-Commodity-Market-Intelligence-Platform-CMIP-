"""PromptRegistry: register, load, and search versioned PromptPackages.

Versions are immutable once registered - re-registering the same
(name, version) key raises, even with identical content, so a prompt's
wording for a given version is guaranteed never to change silently. This
is why `extraction_runs.prompt_version`/`prompt_hash` (see
app/modules/extraction) are trustworthy provenance: a run recorded against
"entity_extraction v1.2" always means the exact same wording, forever -
changing the prompt means registering v1.3, not editing v1.2 in place.

Generic, reusable infra: this module knows nothing about documents,
entities, or any specific prompt's content - those are registered into it
by whichever module owns them (see app/modules/extraction/prompts/).
"""

import hashlib

from app.ai.exceptions import PromptAlreadyRegisteredError, PromptNotFoundError
from app.ai.prompts.package import PromptPackage


def _version_key(version: str) -> tuple[int, int]:
    major, minor = version.split(".", 1)
    return (int(major), int(minor))


class PromptRegistry:
    def __init__(self) -> None:
        self._packages: dict[tuple[str, str], PromptPackage] = {}
        self._latest: dict[str, str] = {}

    def register(self, package: PromptPackage) -> None:
        version = str(package.version)
        key = (package.name, version)
        if key in self._packages:
            raise PromptAlreadyRegisteredError(
                f"{package.name!r} version {version!r} is already registered - "
                "prompt versions are immutable; register a new version instead"
            )
        self._packages[key] = package
        current_latest = self._latest.get(package.name)
        if current_latest is None or _version_key(version) > _version_key(current_latest):
            self._latest[package.name] = version

    def get(self, name: str, version: str | None = None) -> PromptPackage:
        resolved_version = version or self._latest.get(name)
        if resolved_version is None:
            raise PromptNotFoundError(f"No prompt registered under name {name!r}")
        try:
            return self._packages[(name, resolved_version)]
        except KeyError:
            raise PromptNotFoundError(
                f"No prompt {name!r} version {resolved_version!r} registered. "
                f"Known versions: {self.list_versions(name)}"
            ) from None

    def list_versions(self, name: str) -> list[str]:
        versions = [v for (n, v) in self._packages if n == name]
        return sorted(versions, key=_version_key)

    def search(self, *, tag: str | None = None, author: str | None = None) -> list[PromptPackage]:
        results = list(self._packages.values())
        if tag is not None:
            results = [p for p in results if tag in p.metadata.tags]
        if author is not None:
            results = [p for p in results if p.metadata.author == author]
        return results

    @staticmethod
    def compute_hash(package: PromptPackage) -> str:
        """A content hash over the prompt's actual wording (system prompt +
        user template), not its metadata - two versions with identical
        wording but different descriptions would still hash identically,
        which is the intent: the hash exists to prove *what was sent to
        the model*, recorded on extraction_runs.prompt_hash."""
        payload = f"{package.system_prompt}\n---\n{package.user_prompt_template}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_default_registry = PromptRegistry()


def get_prompt_registry() -> PromptRegistry:
    return _default_registry
