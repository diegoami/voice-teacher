"""The language-model connection: any OpenAI-compatible chat-completions API.

The engine does not depend on one vendor. OpenRouter is the default (every
model family on one key); OpenCode Zen and OpenAI work by changing the
provider. Models are settings, one per role, so the teacher's model can be
chosen by measurement.

Environment:
  LLM_PROVIDER    openrouter (default) | opencode | openai
  OPENROUTER_API_KEY / OPENCODE_API_KEY / OPENAI_API_KEY
  TARGETS_MODEL   model that derives the step targets (one call per lesson)
  TEACHER_MODEL   model that plays the teacher (chosen in milestone 2)
  TEACHER_REASONING  reasoning effort for the teacher (default "minimal"; "none" sends nothing,
                  for models without reasoning)
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import openai

PROVIDERS = {
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "opencode": ("https://opencode.ai/zen/v1", "OPENCODE_API_KEY"),
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
}
DEFAULT_TARGETS_MODEL = "openai/gpt-6-sol"  # a strong model: the targets are written once and judged against


@dataclass(frozen=True)
class Connection:
    provider: str
    base_url: str
    key_env: str

    def client(self) -> openai.OpenAI:
        key = os.environ.get(self.key_env)
        if not key:
            raise RuntimeError(f"{self.key_env} is not set (LLM_PROVIDER={self.provider})")
        return openai.OpenAI(base_url=self.base_url, api_key=key)

    def extra_body(self) -> dict:
        """Provider-specific request fields."""
        if self.provider == "openrouter":
            # Route only to endpoints that honour structured output and tools, fastest first
            # (a model's cheaper "flex" endpoints took 2–4 s a call); report the cost.
            return {"provider": {"require_parameters": True, "sort": "latency"}, "usage": {"include": True}}
        return {}

    def reasoning(self) -> dict:
        """The teacher's reasoning setting, as a request field ({} for none)."""
        effort = os.environ.get("TEACHER_REASONING", "minimal")
        return {"reasoning": {"effort": effort}} if self.provider == "openrouter" and effort != "none" else {}

    def model(self, role: str) -> str:
        name = os.environ.get(f"{role.upper()}_MODEL") or (DEFAULT_TARGETS_MODEL if role == "targets" else "")
        if not name:
            raise RuntimeError(f"{role.upper()}_MODEL is not set")
        if self.provider != "openrouter":
            name = name.split("/", 1)[-1]  # OpenRouter names carry the vendor; the others do not
        return name


def connection() -> Connection:
    provider = os.environ.get("LLM_PROVIDER", "openrouter")
    if provider not in PROVIDERS:
        raise RuntimeError(f"LLM_PROVIDER must be one of {sorted(PROVIDERS)}, not {provider!r}")
    return Connection(provider, *PROVIDERS[provider])


def usage_of(completion) -> dict:
    """Tokens, and the cost where the provider reports it (OpenRouter does)."""
    usage = completion.usage
    extra = getattr(usage, "model_extra", None) or {}
    return {"model": completion.model, "input_tokens": usage.prompt_tokens,
            "output_tokens": usage.completion_tokens, "cost_usd": extra.get("cost")}
