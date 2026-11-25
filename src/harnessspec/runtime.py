"""Subagent runtime. Budgets, tool guards, hooks, and the return gate.

The clock is injected. Tests and the fixture pilot use a fake clock so a
budget decision does not depend on machine speed. A wall clock is available
for a later live run.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from harnessspec.hooks import HookOutcome, run_hook
from harnessspec.parent import PERMISSION_RANK, CapabilityCard
from harnessspec.paths import resolve_inside, within_any
from harnessspec.return_gate import AgentResult, Citation, GateDecision, check_return
from harnessspec.validator import validate


@dataclass
class Action:
    kind: str
    tokens: int
    seconds: float
    tool: str | None = None
    permission: str | None = None
    path: str | None = None
    write_content: str | None = None
    result: AgentResult | None = None
    line_range: tuple[int, int] | None = None


@dataclass
class TraceEvent:
    index: int
    kind: str
    code: str | None
    detail: str

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "kind": self.kind,
            "code": self.code,
            "detail": self.detail,
        }


@dataclass
class Trace:
    events: list[TraceEvent] = field(default_factory=list)
    steps_used: int = 0
    tokens_used: int = 0
    seconds_used: float = 0.0
    budget_violations: int = 0
    tool_denials: int = 0
    hooks: list[HookOutcome] = field(default_factory=list)
    return_accepted: bool | None = None
    silent_handoff: bool = False
    stopped: str | None = None

    def as_dict(self) -> dict:
        return {
            "events": [event.as_dict() for event in self.events],
            "steps_used": self.steps_used,
            "tokens_used": self.tokens_used,
            "seconds_used": self.seconds_used,
            "budget_violations": self.budget_violations,
            "tool_denials": self.tool_denials,
            "hooks": [
                {
                    "kind": hook.kind,
                    "command": hook.command,
                    "passed": hook.passed,
                    "output": hook.output,
                }
                for hook in self.hooks
            ],
            "return_accepted": self.return_accepted,
            "silent_handoff": self.silent_handoff,
            "stopped": self.stopped,
        }


@dataclass
class Observation:
    """What the subagent is allowed to see after one step."""

    applied: bool
    code: str | None
    detail: str
    output: str
    remaining_steps: int
    remaining_tokens: int

    def as_dict(self) -> dict:
        return {
            "applied": self.applied,
            "code": self.code,
            "detail": self.detail,
            "output": self.output,
            "remaining_steps": self.remaining_steps,
            "remaining_tokens": self.remaining_tokens,
        }

    def for_model(self) -> str:
        lines = [
            f"applied: {str(self.applied).lower()}",
            f"code: {self.code or 'none'}",
            f"detail: {self.detail}",
            f"remaining steps: {self.remaining_steps}",
            f"remaining tokens: {self.remaining_tokens}",
        ]
        if self.output:
            lines.append("output:")
            lines.append(self.output)
        return "\n".join(lines)


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class SystemClock:
    def now(self) -> float:
        import time

        return time.monotonic()


class Session:
    """One harness run, advanced one action at a time.

    ``run_trace`` feeds a finished list through ``step``. A live subagent
    calls ``step`` after each model reply. The checks are the same ones.
    """

    def __init__(
        self,
        spec: dict,
        parent: CapabilityCard,
        workspace: Path,
        clock: FakeClock | SystemClock | None = None,
        *,
        hook_runner: Callable[[dict, Path, list[str], float], HookOutcome] | None = None,
    ) -> None:
        problems = validate(spec, parent)
        if problems:
            joined = "; ".join(f"{item.code}@{item.path}" for item in problems)
            raise ValueError(f"runtime refuses an invalid harness: {joined}")
        self.spec = spec
        self.workspace = workspace
        self.clock = clock or FakeClock()
        self.start = self.clock.now()
        self.trace = Trace()
        self.budgets = spec["budgets"]
        self.allow = {tool["name"]: tool for tool in spec["tools"]}
        self.hook_runner = hook_runner or run_hook

    def ready_for_call(self) -> bool:
        """Close a live session before inference if a known budget is spent."""
        if self.trace.stopped is not None:
            return False
        if (self.trace.steps_used < self.budgets["max_steps"]
                and self.trace.tokens_used < self.budgets["max_tokens"]
                and self.clock.now() - self.start < self.budgets["max_seconds"]):
            return True
        self.trace.stopped = self.spec["stop"]["on_exhaust"]
        self.trace.events.append(TraceEvent(len(self.trace.events), "stopped", "budget.exhausted",
                                            "no remaining budget for a model call"))
        return False

    def step(self, action: Action) -> Observation:
        if self.trace.stopped is not None:
            return self._observation(
                False,
                "session.stopped",
                f"session already stopped: {self.trace.stopped}",
                "",
            )
        if not _fits(self.trace, action, self.budgets, self.clock, self.start):
            self.trace.budget_violations += 1
            detail = f"{action.kind} would exceed the harness budget"
            self.trace.events.append(
                TraceEvent(len(self.trace.events), "intercepted", "budget.exhausted", detail)
            )
            self.trace.stopped = self.spec.get("stop", {}).get("on_exhaust", "stop")
            return self._observation(False, "budget.exhausted", detail, "")

        _consume(self.trace, action, self.clock)
        if action.kind == "tool":
            denial = _apply_tool(action, self.allow, self.workspace)
            if denial is not None:
                self.trace.tool_denials += 1
                self.trace.events.append(
                    TraceEvent(len(self.trace.events), "intercepted", denial[0], denial[1])
                )
                return self._observation(False, denial[0], denial[1], "")
            detail = f"{action.tool} {action.path}"
            self.trace.events.append(TraceEvent(len(self.trace.events), "applied", None, detail))
            return self._observation(True, None, detail, _tool_output(action, self.workspace))

        if action.kind == "return":
            _finish_return(self.spec, action, self.workspace, self.trace, self.budgets,
                           self.clock, self.start, self.hook_runner)
            last = self.trace.events[-1]
            return self._observation(
                bool(self.trace.return_accepted),
                last.code,
                last.detail,
                _return_output(self.trace),
            )

        detail = f"unknown action {action.kind}"
        self.trace.events.append(
            TraceEvent(len(self.trace.events), "intercepted", "action.unknown", detail)
        )
        self.trace.tool_denials += 1
        return self._observation(False, "action.unknown", detail, "")

    def _observation(self, applied: bool, code: str | None, detail: str, output: str) -> Observation:
        remaining_steps = max(0, self.budgets["max_steps"] - self.trace.steps_used)
        remaining_tokens = max(0, self.budgets["max_tokens"] - self.trace.tokens_used)
        return Observation(applied, code, detail, output, remaining_steps, remaining_tokens)


def run_trace(
    spec: dict,
    parent: CapabilityCard,
    actions: list[Action],
    workspace: Path,
    clock: FakeClock | SystemClock | None = None,
) -> Trace:
    session = Session(spec, parent, workspace, clock)
    for action in actions:
        session.step(action)
        if session.trace.stopped is not None:
            break
    if session.trace.stopped is None and session.trace.return_accepted is None:
        session.trace.stopped = "actions_exhausted"
    return session.trace


def _fits(trace: Trace, action: Action, budgets: dict, clock, start: float) -> bool:
    if trace.steps_used + 1 > budgets["max_steps"]:
        return False
    if trace.tokens_used + action.tokens > budgets["max_tokens"]:
        return False
    elapsed = (clock.now() - start) + action.seconds
    if elapsed > budgets["max_seconds"]:
        return False
    return True


def _consume(trace: Trace, action: Action, clock) -> None:
    trace.steps_used += 1
    trace.tokens_used += action.tokens
    if isinstance(clock, FakeClock):
        clock.advance(action.seconds)
    trace.seconds_used += action.seconds


def _apply_tool(action: Action, allow: dict, workspace: Path) -> tuple[str, str] | None:
    grant = allow.get(action.tool or "")
    if grant is None:
        return ("tool.not_in_allowlist", f"{action.tool} is not in the harness allowlist")
    permission = action.permission or ""
    if permission not in PERMISSION_RANK:
        return ("tool.privilege", "action permission is missing")
    if PERMISSION_RANK[permission] > PERMISSION_RANK[grant["permission"]]:
        return (
            "tool.privilege",
            f"{action.tool} used as {permission}; harness allows {grant['permission']}",
        )
    relative = action.path or ""
    if not within_any(relative, grant["paths"]):
        return ("tool.path", f"{relative} is outside the harness path grant")
    target = resolve_inside(workspace, relative)
    if target is None:
        return ("tool.path", f"{relative} escapes the workspace")
    if permission == "read" and (
        action.tool == "read_file" and not target.is_file()
        or action.tool == "list_dir" and not target.is_dir()
    ):
        return ("tool.path", f"{action.tool} requires an existing "
                + ("file" if action.tool == "read_file" else "directory"))
    if action.line_range is not None:
        first, last = action.line_range
        if (action.tool != "read_file" or permission != "read" or not target.is_file()
                or type(first) is not int or type(last) is not int
                or not 1 <= first <= last or last - first >= 200):
            return ("tool.line_range", "line ranges require a file read of at most 200 lines")
    if permission == "write":
        if action.write_content is None:
            return ("tool.path", "write action has no content")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(action.write_content, encoding="utf-8")
    return None


def _tool_output(action: Action, workspace: Path) -> str:
    """File text on a read, a listing on a directory, a short note on a write."""
    if action.permission == "write":
        return f"wrote {action.path} ({len(action.write_content or '')} characters)"
    if action.permission != "read":
        return f"applied {action.tool} {action.path}"
    target = resolve_inside(workspace, action.path or "")
    if target is None or not target.exists():
        return "path does not exist"
    if target.is_dir():
        names = []
        for child in sorted(target.iterdir()):
            relative = child.relative_to(workspace.resolve()).as_posix()
            names.append(relative + ("/" if child.is_dir() else ""))
            if len(names) == 200:
                names.append("...")
                break
        return "\n".join(names)
    text = target.read_text(encoding="utf-8", errors="replace")
    if action.line_range is not None:
        first, last = action.line_range
        lines = text.splitlines()
        numbered = [f"{index}: {line}" for index, line in enumerate(lines[first - 1:last], first)]
        text = "\n".join([f"File has {len(lines)} lines.", *numbered])
    if len(text) > 12000:
        return text[:12000] + "\n... truncated"
    return text


def _return_output(trace: Trace) -> str:
    chunks = []
    for hook in trace.hooks:
        state = "passed" if hook.passed else "failed"
        chunks.append(f"{hook.command}: {state}\n{hook.output}")
    return "\n".join(chunks)


def _finish_return(spec, action: Action, workspace: Path, trace: Trace, budgets, clock, start,
                   hook_runner) -> None:
    include = list(spec.get("context", {}).get("include", []))
    remaining = budgets["max_seconds"] - (clock.now() - start)
    failed = False
    for hook in spec.get("verification", {}).get("hooks", []):
        outcome = hook_runner(hook, workspace, include, remaining)
        trace.hooks.append(outcome)
        trace.events.append(
            TraceEvent(
                len(trace.events),
                "hook",
                None if outcome.passed else "hook.failed",
                f"{outcome.command}: {outcome.output.splitlines()[0] if outcome.output else ''}",
            )
        )
        if not outcome.passed:
            failed = True
    if failed:
        trace.return_accepted = False
        trace.silent_handoff = False
        trace.stopped = "hook_failed"
        return
    result = action.result or AgentResult(summary="")
    decision: GateDecision = check_return(spec, result)
    trace.return_accepted = decision.accepted
    trace.silent_handoff = decision.silent_handoff
    code = None if decision.accepted else decision.errors[0].code
    detail = "return accepted" if decision.accepted else decision.errors[0].message
    trace.events.append(TraceEvent(len(trace.events), "returned", code, detail))
    trace.stopped = "accepted" if decision.accepted else "return_rejected"


def citation(file: str, line: int) -> Citation:
    return Citation(file, line)
