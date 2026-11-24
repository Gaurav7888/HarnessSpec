"""Live subagent loop.

One reply from the pinned model becomes one action. ``Session.step`` applies
the same budget, tool-grant, hook, and return-gate checks as ``run_trace``.
The model is called only through the client passed in. The fixture runner
uses ``CursorCliClient``. A client may define ``budget_tokens(reply)`` when
the server's prompt count includes a wrapper the harness cap was not sized for.
"""

from __future__ import annotations

import json
import time

from harnessspec.hooks import run_hook
from harnessspec.llm import Reply
from harnessspec.orchestrator import parse_object
from harnessspec.parent import CapabilityCard
from harnessspec.return_gate import AgentResult, Citation
from harnessspec.runtime import Action, FakeClock, Observation, Session, SystemClock


SYSTEM = (
    "You are a coding subagent inside a harness. Take one action per reply. "
    "Reply with one JSON object and no other text. A tool the harness does not grant is refused. "
    "There is no shell. Tests run when you return, through the harness hooks."
)


def _load_object(text: str) -> dict | None:
    value, errors = parse_object(text)
    if not errors and isinstance(value, dict):
        return value
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        loaded = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


def _citations(raw) -> list[Citation]:
    citations = []
    if not isinstance(raw, list):
        return citations
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            line = int(item.get("line"))
        except (TypeError, ValueError, OverflowError):
            continue
        citations.append(Citation(str(item.get("file") or ""), line))
    return citations


def action_from_reply(content: str, tokens: int, seconds: float) -> Action:
    """Turn one model reply into one action. An unreadable reply is an unknown action."""
    data = _load_object(content)
    if data is None or data.get("kind") not in ("tool", "return"):
        return Action(kind="unparsed", tokens=tokens, seconds=seconds)
    if data["kind"] == "return":
        claims = data.get("claims") if isinstance(data.get("claims"), list) else []
        test_output = data.get("test_output")
        return Action(
            kind="return",
            tokens=tokens,
            seconds=seconds,
            result=AgentResult(
                summary=str(data.get("summary") or ""),
                citations=_citations(data.get("citations")),
                test_output=None if test_output is None else str(test_output),
                claims=[str(item) for item in claims],
            ),
        )
    content_value = data.get("content")
    line_range = None
    if "start_line" in data or "end_line" in data:
        line_range = (data.get("start_line"), data.get("end_line"))
    return Action(
        kind="tool",
        tokens=tokens,
        seconds=seconds,
        tool=str(data.get("tool") or ""),
        permission=str(data.get("permission") or ""),
        path=str(data.get("path") or ""),
        write_content=None if content_value is None else str(content_value),
        line_range=line_range,
    )


def opening_prompt(spec: dict) -> str:
    tools = [
        f"- {tool['name']} permission {tool['permission']} paths {list(tool['paths'])}"
        for tool in spec["tools"]
    ]
    contract = spec["return_contract"]
    budgets = spec["budgets"]
    return "\n".join(
        [
            f"Goal: {spec['goal']['statement']}",
            "Tools you may call:",
            *tools,
            (
                f"Budgets: {budgets['max_steps']} steps, "
                f"{budgets['max_tokens']} tokens, {budgets['max_seconds']} seconds."
            ),
            (
                "Return contract: "
                f"citations required={str(contract['require_citations']).lower()}, "
                f"test output required={str(contract['require_test_output']).lower()}, "
                f"min citations={contract['min_citations']}."
            ),
            'Read: {"kind":"tool","tool":"read_file","permission":"read","path":"src/app.py"}',
            'Write the whole file: {"kind":"tool","tool":"write_file","permission":"write","path":"src/app.py","content":"..."}',
            'Return: {"kind":"return","summary":"...","citations":[{"file":"src/app.py","line":2}],"test_output":"...","claims":[]}',
        ]
    )


def workspace_passes(workspace) -> bool:
    """External check. Designer A does not run hooks, so resolution is measured here."""
    outcome = run_hook({"kind": "test", "command": "unittest"}, workspace, ["src", "tests"], 30)
    return outcome.passed


def run_subagent(
    spec: dict,
    parent: CapabilityCard,
    workspace,
    seed: int,
    client,
    clock: FakeClock | SystemClock | None = None,
) -> dict:
    session = Session(spec, parent, workspace, clock)
    # SystemClock has already moved during the model call. Adding reply.seconds
    # again would charge that time twice against max_seconds.
    wall_clock = isinstance(session.clock, SystemClock)
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": opening_prompt(spec)},
    ]
    log = []
    started = time.monotonic()
    while session.trace.stopped is None:
        reply: Reply = client.chat(messages, seed=seed, json_mode=True)
        seconds = 0.0 if wall_clock else reply.seconds
        charged = reply.tokens
        budget_tokens = getattr(client, "budget_tokens", None)
        if budget_tokens is not None:
            charged = budget_tokens(reply)
        action = action_from_reply(reply.content, charged, seconds)
        observation: Observation = session.step(action)
        log.append(
            {
                "reply": reply.content,
                "prompt_tokens": reply.prompt_tokens,
                "output_tokens": reply.output_tokens,
                "reasoning_tokens": reply.reasoning_tokens,
                "charged_tokens": charged,
                "seconds": reply.seconds,
                "observation": observation.as_dict(),
            }
        )
        messages.append({"role": "assistant", "content": reply.content})
        messages.append({"role": "user", "content": observation.for_model()})
    return {
        "trace": session.trace,
        "log": log,
        "subagent_tokens": session.trace.tokens_used,
        "wall_clock_s": round(time.monotonic() - started, 3),
        "resolved": workspace_passes(workspace),
    }


def result_row(spec: dict, designer: str, seed: int, pin: dict, spec_source: str, outcome: dict) -> dict:
    trace = outcome["trace"]
    return {
        "task_id": spec["task_id"],
        "benchmark": "fixture",
        "designer": designer,
        "seed": seed,
        "model": pin["name"],
        "model_digest": pin["digest"],
        "spec_source": spec_source,
        "design_tokens": 0,
        "subagent_tokens": outcome["subagent_tokens"],
        "rounds": 0,
        "first_pass_valid": True,
        "resolved": outcome["resolved"],
        "silent_handoff": trace.silent_handoff,
        "budget_violations": trace.budget_violations,
        "tool_denials": trace.tool_denials,
        "hook_failures": sum(1 for hook in trace.hooks if not hook.passed),
        "wall_clock_s": outcome["wall_clock_s"],
    }
