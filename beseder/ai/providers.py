"""Providers IA interchangeables.

Tous exposent la même chose : `complete(system, user, fast)` -> texte.
Aucun ne donne d'outil à l'IA (voir CLAUDE.md).

- openai_compat : OpenRouter, Google AI Studio, Ollama, LM Studio, Groq, Mistral...
- anthropic     : API Claude (clé API)
- claude_cli    : le `claude` installé sur le Pi (ton abonnement), sans outils ni MCP
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
        "note": "Les modèles « :free » sont gratuits mais certains fournisseurs peuvent conserver "
        "ou utiliser tes prompts (donc tes mails). Vérifie la politique du modèle choisi.",
    },
    "google": {
        "kind": "openai_compat",
        "label": "Google AI Studio (Gemini)",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "needs_key": True,
        "note": "Avec l'offre gratuite, Google peut utiliser tes prompts (donc tes mails) pour "
        "améliorer ses produits. L'offre payante ne le fait pas.",
    },
    "ollama": {
        "kind": "openai_compat",
        "label": "Ollama (local)",
        "base_url": "http://localhost:11434/v1",
        "needs_key": False,
        "note": "Tout reste chez toi. Un Pi est lent pour les gros modèles : vise un petit modèle "
        "ou un Ollama sur une autre machine de ton tailnet.",
    },
    "anthropic": {
        "kind": "anthropic",
        "label": "Claude (API Anthropic)",
        "base_url": "",
        "needs_key": True,
        "model": "claude-opus-5-5",
        "model_fast": "claude-haiku-5-5",
        "note": "Payant à l'usage. Haiku pour le tri (peu cher), Opus pour résumés et brouillons.",
    },
    "claude_cli": {
        "kind": "claude_cli",
        "label": "Claude Code sur le Pi",
        "base_url": "",
        "needs_key": False,
        "model": "",
        "model_fast": "haiku",
        "note": "Utilise le `claude` déjà connecté sur le Pi. Lancé sans outils et sans serveurs MCP.",
    },
    "custom": {
        "kind": "openai_compat",
        "label": "Autre (compatible OpenAI)",
        "base_url": "",
        "needs_key": False,
        "note": "",
    },
}

# Modèles Claude qui acceptent `fallbacks: "default"` (refus de sécurité -> autre modèle).
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
            raise AIError(f"{r.status_code} : {r.text[:300]}")
        try:
            return r.json()["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError, ValueError):
            raise AIError("Réponse inattendue du fournisseur")

    async def list_models(self):
        r = await self.http.get(f"{self.base}/models")
        if r.status_code != 200:
            raise AIError(f"{r.status_code} : {r.text[:300]}")
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
                # Tri : rapide et pas cher. Résumés / brouillons : un peu plus de réflexion.
                output_config={"effort": "low" if fast else "medium"},
                **kwargs,
            )
        except anthropic.AuthenticationError:
            raise AIError("Clé API Anthropic refusée")
        except anthropic.RateLimitError:
            raise AIError("Limite de débit Anthropic atteinte, réessaie plus tard")
        except anthropic.APIStatusError as e:
            raise AIError(f"Erreur API Anthropic {e.status_code}")
        except anthropic.APIConnectionError:
            raise AIError("Impossible de joindre l'API Anthropic")
        if resp.stop_reason == "refusal":
            raise AIError("Le modèle a refusé de traiter ce contenu")
        return "".join(b.text for b in resp.content if b.type == "text")

    async def list_models(self):
        try:
            return sorted([m.id async for m in self.client.models.list(limit=100)])
        except anthropic.APIError as e:
            raise AIError(f"Impossible de lister les modèles : {type(e).__name__}")


class ClaudeCLIProvider(Provider):
    """Appelle `claude -p` en mode non interactif, sans aucun outil ni MCP."""

    TIMEOUT = 300

    def __init__(self, cfg: AIConfig):
        self.cfg = cfg

    def build_args(self, system: str, fast: bool) -> list[str]:
        exe = shutil.which(self.cfg.command) or self.cfg.command
        args = [
            exe, "-p",
            "--output-format", "text",
            "--tools", "",              # aucun outil (Bash, Edit, WebFetch...)
            "--strict-mcp-config",      # ignore les serveurs MCP configurés sur le Pi
            "--system-prompt", system,
        ]
        model = (self.cfg.model_fast if fast else "") or self.cfg.model
        if model:
            args += ["--model", model]
        return args

    async def complete(self, system, user, *, fast=False, max_tokens=2000):
        args = self.build_args(system, fast)
        # Dossier vide : pas de CLAUDE.md ni de fichiers du projet visibles.
        with tempfile.TemporaryDirectory(prefix="beseder-ai-") as cwd:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *args, cwd=cwd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except FileNotFoundError:
                raise AIError(f"Commande introuvable : {self.cfg.command}")
            try:
                out, err = await asyncio.wait_for(proc.communicate(user.encode()), self.TIMEOUT)
            except asyncio.TimeoutError:
                proc.kill()
                raise AIError("Claude CLI n'a pas répondu à temps")
        if proc.returncode != 0:
            raise AIError(f"Claude CLI a échoué : {err.decode(errors='replace')[:300]}")
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
    raise AIError("Aucune IA configurée")
