import asyncio
import json
import os
import stat

import httpx

from beseder.ai.providers import AIConfig, ClaudeCLIProvider, OpenAICompatProvider


def test_openai_compat_request_and_fast_model():
    seen = {}

    def handler(request: httpx.Request):
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})

    cfg = AIConfig(kind="openai_compat", base_url="https://openrouter.ai/api/v1/", model="big", model_fast="small", api_key="k")
    p = OpenAICompatProvider(cfg, transport=httpx.MockTransport(handler))
    assert asyncio.run(p.complete("sys", "user", fast=True)) == "OK"
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert seen["auth"] == "Bearer k"
    assert seen["body"]["model"] == "small"
    assert "tools" not in seen["body"]
    asyncio.run(p.complete("sys", "user"))
    assert seen["body"]["model"] == "big"


def test_claude_cli_runs_without_tools_or_mcp(tmp_path):
    # Faux binaire `claude` qui renvoie ses arguments et ce qu'il lit sur stdin.
    fake = tmp_path / "claude"
    fake.write_text(
        "#!/usr/bin/env python3\nimport json, os, sys\n"
        "print(json.dumps({'args': sys.argv[1:], 'stdin': sys.stdin.read(), 'cwd': os.getcwd()}))\n"
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    p = ClaudeCLIProvider(AIConfig(kind="claude_cli", command=str(fake), model_fast="haiku"))
    out = json.loads(asyncio.run(p.complete("SYSTEME", "contenu du mail", fast=True)))
    args = out["args"]
    assert args[args.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in args
    assert args[args.index("--model") + 1] == "haiku"
    assert args[args.index("--system-prompt") + 1] == "SYSTEME"
    assert out["stdin"] == "contenu du mail"
    assert os.path.basename(out["cwd"]).startswith("beseder-ai-")
