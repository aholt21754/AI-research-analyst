import json
from pathlib import Path

PROMPT_DIR = Path(__file__).parent
LATEST_VERSION = "v1"  # Update this string when promoting a new version


class PromptRegistry:
    _cache: dict = {}

    @classmethod
    def load(cls, version: str = "latest") -> dict:
        if version == "latest":
            version = LATEST_VERSION
        if version in cls._cache:
            return cls._cache[version]
        path = PROMPT_DIR / f"{version}.json"
        if not path.exists():
            raise FileNotFoundError(f"Prompt version '{version}' not found at {path}")
        with open(path) as f:
            prompt = json.load(f)
        cls._cache[version] = prompt
        return prompt


def get_prompt(version: str = None) -> tuple[str, str, str]:
    """Returns (version_str, system_prompt, user_template)."""
    version = version or "latest"
    data = PromptRegistry.load(version)
    return data["version"], data["system"], data["user_template"]
