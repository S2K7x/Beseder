"""Pluggable AI providers.

They all expose the same thing: `complete(system, user, fast)` -> text.
None of them gives the AI any tool (see CLAUDE.md).

- openai_compat: OpenRouter, Google AI Studio, Ollama, LM Studio, Groq, Mistral...
- anthropic:     Claude API (API key)
- claude_cli:    the `claude` installed on the Pi (your subscription), no tools, no MCP
"""

import asyncio
import shutil
import tempfile
from dataclasses import dataclass, field

import anthropic
import httpx

PRESETS = {
    "openrouter": {
        "kind": "openai_compat",
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "needs_key": True,
        "note": "\":free\" models cost nothing, but some of their providers may keep or use your "
        "prompts (so your emails). Check the policy of the model you pick.",
    },
    "google": {
        "kind": "openai_compat",
        "label": "Google AI Studio (Gemini)",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "needs_key": True,
        "note": "On the free tier, Google may use your prompts (so your emails) to improve its "
        "products. The paid tier does not.",
    },
    "ollama": {
        "kind": "openai_compat",
        "label": "Ollama (local)",
        "base_url": "http://localhost:11434/v1",
        "needs_key": False,
        "note": "Everything stays at home. A Pi is slow with large models: pick a small one, "
        "or point to an Ollama running on another machine of your tailnet.",
    },
    "anthropic": {
        "kind": "anthropic",
        "label": "Claude (API Anthropic)",
        "base_url": "",
        "needs_key": True,
        "model": "claude-opus-5-5",
        "model_fast": "claude-haiku-5-5",
        "note": "Pay as you go. Haiku for triage (cheap), Opus for summaries and drafts.",
    },
    "claude_cli": {
        "kind": "claude_cli",
        "label": "Claude Code on the Pi",
        "base_url": "",
        "needs_key": False,
        "model": "",
        "model_fast": "haiku",
        "note": "Uses the `claude` already signed in on the Pi. Runs with no tools and no MCP servers.",
    },
    "custom": {
        "kind": "openai_compat",
        "label": "Other (OpenAI-compatible)",
        "base_url": "",
        "needs_key": False,
        "note": "",
    },
}

# Claude models that accept `fallbacks: "default"` (safety decline -> another model).
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}


class AIError(Exception):
    pass


@dataclass
class AIConfig:
    preset: str = ""
    kind: str = ""
    base_url: str = ""
    model: str = ""
    model_fast: str = ""
    api_key: str = field(default="", repr=False)
    command: str = "claude"

    @property
    def configured(self) -> bool:
        if self.kind == "claude_cli":
            return True
        return bool(self.kind and self.model and (self.base_url or self.kind == "anthropic"))


class Provider:
    async def complete(self, system: str, user: str, *, fast: bool = False, max_tokens: int = 2000) -> str:
        raise NotImplementedError

    async def list_models(self) -> list[str]:
        return []


class OpenAICompatProvider(Provider):
    def __init__(self, cfg: AIConfig, transport: httpx.AsyncBaseTransport | None = None):
        self.cfg = cfg
        self.base = cfg.base_url.rstrip("/")
        headers = {"Content-Type": "application/json"}
        if cfg.api_key:
            headers["Authorization"] = f"Bearer {cfg.api_key}"
        if "openrouter.ai" in self.base:
            headers["X-Title"] = "Beseder"
        self.http = httpx.AsyncClient(headers=headers, timeout=180, transport=transport)

    async def complete(self, system, user, *, fast=False, max_tokens=2000):
        model = (self.cfg.model_fast if fast else "") or self.cfg.model
        r = await self.http.post(
            f"{self.base}/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "max_tokens": max_tokens,
                "temperature": 0.2,
            },
        )
        if r.status_code != 200:
            raise AIError(f"{r.status_code}: {r.text[:300]}")
        try:
            return r.json()["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError, ValueError):
            raise AIError("Unexpected response from the provider")

    async def list_models(self):
        r = await self.http.get(f"{self.base}/models")
        if r.status_code != 200:
            raise AIError(f"{r.status_code}: {r.text[:300]}")
        data = r.json().get("data", [])
        return sorted(m["id"].removeprefix("models/") for m in data if m.get("id"))


class AnthropicProvider(Provider):
    def __init__(self, cfg: AIConfig):
        self.cfg = cfg
        self.client = anthropic.AsyncAnthropic(api_key=cfg.api_key or None, max_retries=2)

    async def complete(self, system, user, *, fast=False, max_tokens=2000):
        model = (self.cfg.model_fast if fast else "") or self.cfg.model
        kwargs = {}
        if model in _FALLBACK_MODELS:
            kwargs = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        try:
            resp = await self.client.beta.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                # Triage: fast and cheap. Summaries and drafts: a bit more thinking.
                output_config={"effort": "low" if fast else "medium"},
                **kwargs,
            )
        except anthropic.AuthenticationError:
            raise AIError("Anthropic API key rejected")
        except anthropic.RateLimitError:
            raise AIError("Anthropic rate limit reached, try again later")
        except anthropic.APIStatusError as e:
            raise AIError(f"Anthropic API error {e.status_code}")
        except anthropic.APIConnectionError:
            raise AIError("Cannot reach the Anthropic API")
        if resp.stop_reason == "refusal":
            raise AIError("The model declined to process this content")
        return "".join(b.text for b in resp.content if b.type == "text")

    async def list_models(self):
        try:
            return sorted([m.id async for m in self.client.models.list(limit=100)])
        except anthropic.APIError as e:
            raise AIError(f"Cannot list models: {type(e).__name__}")


class ClaudeCLIProvider(Provider):
    """Runs `claude -p` non-interactively, with no tools and no MCP."""

    TIMEOUT = 300

    def __init__(self, cfg: AIConfig):
        self.cfg = cfg

    def build_args(self, system: str, fast: bool) -> list[str]:
        exe = shutil.which(self.cfg.command) or self.cfg.command
        args = [
            exe, "-p",
            "--output-format", "text",
            "--tools", "",              # no tools at all (Bash, Edit, WebFetch...)
            "--strict-mcp-config",      # ignore the MCP servers configured on the Pi
            "--system-prompt", system,
        ]
        model = (self.cfg.model_fast if fast else "") or self.cfg.model
        if model:
            args += ["--model", model]
        return args

    async def complete(self, system, user, *, fast=False, max_tokens=2000):
        args = self.build_args(system, fast)
        # Empty folder: no CLAUDE.md and no project files in sight.
        with tempfile.TemporaryDirectory(prefix="beseder-ai-") as cwd:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *args, cwd=cwd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except FileNotFoundError:
                raise AIError(f"Command not found: {self.cfg.command}")
            try:
                out, err = await asyncio.wait_for(proc.communicate(user.encode()), self.TIMEOUT)
            except asyncio.TimeoutError:
                proc.kill()
                raise AIError("Claude CLI timed out")
        if proc.returncode != 0:
            raise AIError(f"Claude CLI failed: {err.decode(errors='replace')[:300]}")
        return out.decode(errors="replace")

    async def list_models(self):
        return ["haiku", "sonnet", "opus"]


def make_provider(cfg: AIConfig) -> Provider:
    if cfg.kind == "openai_compat":
        return OpenAICompatProvider(cfg)
    if cfg.kind == "anthropic":
        return AnthropicProvider(cfg)
    if cfg.kind == "claude_cli":
        return ClaudeCLIProvider(cfg)
    raise AIError("No AI configured")
