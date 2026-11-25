"""Turn any designer's ``design()`` result into a spec the runtime will run.

``Session`` runs only a full, valid HarnessSpec. A and D already produce one.
B (a prose brief) and C (the four-field tuple) do not, so both benchmark runners
call ``executable_spec`` and get the same answer for the same design.

The rules follow the B/C execution proposal in ``docs/SWEQA_AUDIT.md``:

- **A, D**: run ``result["spec"]`` only if ``result["valid"]``. An invalid D is
  an orchestrator failure, not something to run.
- **B**: A's harness, with the brief verbatim as the goal statement. One design
  call, no compilation of the prose, no repair.
- **C**: A's harness, with the tuple's instruction, context, and tools as
  emitted. Each named tool gets the parent card's permission, because the tuple
  carries no permission field and ``aorchestra_tuple`` writes ``read`` on every
  tool (so C could otherwise never write a fix). A tool's paths are the tuple's
  context narrowed to that tool's grant. The tuple's model must be the pinned
  model. Nothing is inferred or repaired. Anything outside the parent card is
  rejected with a reason.

The rest of a B or C harness (acceptance tests, budgets, stop rule, hooks,
return contract, tier) is A's, so B and C differ from A only in what the
designer emitted. C's H3 score is the tuple as emitted and is not changed here.
"""

from __future__ import annotations

from copy import deepcopy

from harnessspec.designers import fixed_generic_harness
from harnessspec.parent import CapabilityCard
from harnessspec.paths import is_relative_safe, within_any
from harnessspec.validator import validate


class NotExecutable(ValueError):
    """The design cannot run under the parent card. ``reason`` is a short code."""

    def __init__(self, reason: str, detail: str):
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


def executable_spec(result: dict, task: dict, card: CapabilityCard) -> dict:
    """Return the HarnessSpec to run for ``result``, or raise ``NotExecutable``.

    ``task`` is the same ``{"task_id", "statement"}`` passed to ``design()``.
    ``card`` is the parent card the run uses.
    """
    designer = result.get("designer")
    if designer in ("A", "D"):
        if not result.get("valid"):
            codes = sorted({error["code"] for error in result.get("remaining_errors", [])})
            raise NotExecutable("design.invalid", ", ".join(codes) or "invalid spec")
        spec = deepcopy(result["spec"])
    elif designer == "B":
        spec = _brief_spec(result, task, card)
    elif designer == "C":
        spec = _tuple_spec(result, task, card)
    else:
        raise NotExecutable("designer.unknown", str(designer))
    problems = validate(spec, card)
    if problems:
        codes = sorted({problem.code for problem in problems})
        raise NotExecutable("spec.invalid", ", ".join(codes))
    return spec


def _baseline(task: dict, card: CapabilityCard, model_name: str) -> dict:
    spec = fixed_generic_harness(task["task_id"], card, task["statement"])
    spec["model"]["name"] = model_name
    return spec


def _brief_spec(result: dict, task: dict, card: CapabilityCard) -> dict:
    brief = result.get("spec") or {}
    text = brief.get("text") if isinstance(brief, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise NotExecutable("brief.empty", "the brief has no text")
    spec = _baseline(task, card, result["model"])
    spec["goal"]["statement"] = text
    return spec


def _tuple_spec(result: dict, task: dict, card: CapabilityCard) -> dict:
    emitted = result.get("spec") or {}
    if any(error.get("code") == "orchestrator.parse" for error in result.get("remaining_errors", [])):
        raise NotExecutable("tuple.unparsed", "the reply was not a JSON object")

    goal = emitted.get("goal")
    instruction = goal.get("statement") if isinstance(goal, dict) else None
    if not isinstance(instruction, str) or not instruction.strip():
        raise NotExecutable("tuple.instruction", "instruction must be a non-empty string")

    context = emitted.get("context")
    include = context.get("include") if isinstance(context, dict) else None
    if (not isinstance(include, list) or not include
            or not all(isinstance(item, str) for item in include)):
        raise NotExecutable("tuple.context", "context must be a non-empty list of paths")
    for item in include:
        if not is_relative_safe(item) or not within_any(item, card.context_paths):
            raise NotExecutable("tuple.context", f"{item} is outside the parent context")

    names = _tool_names(emitted.get("tools"))
    tools = []
    for name in names:
        grant = card.tools.get(name)
        if grant is None:
            raise NotExecutable("tuple.tool", f"{name} is not on the parent card")
        paths = [item for item in include if within_any(item, grant.paths)]
        if not paths:
            raise NotExecutable("tuple.tool", f"{name}: no context path lies inside its grant")
        tools.append({"name": name, "permission": grant.permission, "paths": paths})

    model = emitted.get("model")
    model_name = model.get("name") if isinstance(model, dict) else None
    if model_name != result["model"]:
        raise NotExecutable("tuple.model", f"{model_name!r} is not the pinned model {result['model']!r}")

    spec = _baseline(task, card, result["model"])
    spec["goal"]["statement"] = instruction
    spec["context"] = {"include": list(include), "exclude": []}
    spec["tools"] = tools
    return spec


def _tool_names(tools) -> list[str]:
    """Tool names in order, from the emitted list (strings or aorchestra_tuple dicts)."""
    if not isinstance(tools, list) or not tools:
        raise NotExecutable("tuple.tools", "tools must be a non-empty list of names")
    names = []
    for tool in tools:
        name = tool.get("name") if isinstance(tool, dict) else tool
        if not isinstance(name, str) or not name:
            raise NotExecutable("tuple.tools", "every tool must be a name")
        if name in names:
            raise NotExecutable("tuple.tools", f"{name} is listed twice")
        names.append(name)
    return names
