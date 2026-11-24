"""Subagent client that calls a Grok model through the Cursor CLI.

``agent -p --mode ask`` is read-only, so the model cannot edit the workspace.
The harness applies every action itself. The CLI's ``inputTokens`` count
includes the agent preamble, which is larger than either fixture token cap,
so ``budget_tokens`` charges output tokens and reasoning tokens. The preamble
is still stored on the reply as ``prompt_tokens``. The CLI reports no weight
digest and no seed flag. ``reply.seconds`` is ``duration_api_ms``, not process
startup.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from harnessspec.llm import Reply

DEFAULT_MODEL = "grok-4.7-low"


def reply_from_cli(payload: dict) -> Reply:
    if payload.get("is_error"):
        raise RuntimeError(payload.get("result") or "cursor cli returned an error")
    usage = payload.get("usage") or {}
    return Reply(
        content=str(payload.get("result") or ""),
        prompt_tokens=int(usage.get("inputTokens") or 0),
        output_tokens=int(usage.get("outputTokens") or 0),
        reasoning_tokens=int(usage.get("reasoningTokens") or 0),
        seconds=round(int(payload.get("duration_api_ms") or 0) / 1000, 3),
    )


def _parse_stdout(stdout: str) -> dict:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("type") == "result":
            return payload
    raise RuntimeError(f"cursor cli returned no result payload: {stdout[-500:]}")


class CursorCliClient:
    def __init__(self, model: str = DEFAULT_MODEL, timeout: float = 180.0, agent: str | None = None):
        self.model = model
        self.name = model
        self.digest = "cursor-cli; no weight digest"
        self.timeout = timeout
        self.agent = agent or shutil.which("agent")
        if not self.agent:
            raise RuntimeError("cursor cli `agent` is not on PATH")
        self.workspace = Path(tempfile.mkdtemp(prefix="harnessspec-cursor-"))

    def budget_tokens(self, reply: Reply) -> int:
        return reply.output_tokens + reply.reasoning_tokens

    def chat(self, messages: list[dict], seed: int, json_mode: bool = False) -> Reply:
        prompt = _prompt(messages, seed, json_mode)
        completed = subprocess.run(
            [
                self.agent,
                "-p",
                "--mode",
                "ask",
                "--trust",
                "--sandbox",
                "enabled",
                "--model",
                self.model,
                "--output-format",
                "json",
                "--workspace",
                str(self.workspace),
                prompt,
            ],
            capture_output=True,
            text=True,
            timeout=self.timeout,
            shell=False,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(f"cursor cli exited {completed.returncode}: {detail[-800:]}")
        reply = reply_from_cli(_parse_stdout(completed.stdout))
        print(
            f"cursor cli {self.model} api={reply.seconds}s "
            f"in={reply.prompt_tokens} out={reply.output_tokens} reason={reply.reasoning_tokens}",
            flush=True,
        )
        return reply


def _prompt(messages: list[dict], seed: int, json_mode: bool) -> str:
    lines = [
        "You are answering inside a harness. Reply with one JSON object and no other text.",
        "Do not call tools. Do not edit files. Do not add markdown.",
        f"The harness seed is {seed}. Do not copy the seed into the JSON.",
    ]
    if json_mode:
        lines.append("The reply must be one JSON object.")
    lines.append("")
    for message in messages:
        lines.append(f"[{message.get('role', 'user')}]")
        lines.append(str(message.get("content", "")))
        lines.append("")
    return "\n".join(lines)
