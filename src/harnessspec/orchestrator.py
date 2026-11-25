"""The orchestrator: four designers behind one function.

``design(task, card, designer, seed)`` returns at least
``{spec, design_tokens, rounds, first_pass_valid}``.

- A: ``fixed_generic_harness``. No model call, so ``design_tokens`` is 0.
- B: a free-text brief from the model, stored by ``free_text_brief`` and not validated.
- C: the four-field AOrchestra tuple, scored as the model emitted it, before repair.
- D: a full HarnessSpec. On failure the compiler first clamps what it may
  (``repair.py``: privileges, budgets, defaults), then the typed errors that
  are left go back to the model, for at most three rounds. The model has to
  write the goal, the acceptance test, and the context paths itself.

``rounds`` counts repair rounds after the first reply, so 0 means the first
spec was valid. ``design_tokens`` is the sum of prompt and output tokens over
every model call the designer made.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from harnessspec.designers import aorchestra_tuple, fixed_generic_harness, free_text_brief
from harnessspec.errors import SpecError
from harnessspec.llm import ROOT, load_pin
from harnessspec.parent import ALLOWED_COMMANDS, PERMISSION_RANK, STOP_CONDITIONS, CapabilityCard
from harnessspec.repair import MAX_REPAIR_ROUNDS, repair_until_valid
from harnessspec.validator import SPEC_VERSION, validate

DESIGNERS = ("A", "B", "C", "D")
SCHEMA = ROOT / "schema" / "harnessspec.schema.json"
PARSE_ERROR = "orchestrator.parse"


# --------------------------------------------------------------------------- prompts

def _schema_text() -> str:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    for key in ("$schema", "$id"):
        schema.pop(key, None)
    return json.dumps(schema, separators=(",", ":"))


def _rules(card: CapabilityCard, model_name: str) -> str:
    commands = ", ".join(f"{name} (kind {kind})" for name, kind in sorted(ALLOWED_COMMANDS.items()))
    order = " < ".join(sorted(PERMISSION_RANK, key=PERMISSION_RANK.get))
    return "\n".join(
        [
            "Rules the compiler enforces beyond the schema:",
            f'- spec_version is "{SPEC_VERSION}".',
            "- Every tool must be on the parent card. Its permission may not exceed the card's"
            f" ({order}), and each of its paths must lie inside the card's paths for that tool.",
            "- context.include is non-empty, and every path lies inside the card's context_paths."
            " Paths are relative, with no '..' and no leading '/'.",
            "- Budgets are integers >= 1 and at most the card's. max_tokens >= max_steps.",
            f"- Acceptance-test commands and hook commands must be one of: {commands}."
            " A hook's kind must match its command's kind.",
            f"- stop.conditions are drawn from: {', '.join(STOP_CONDITIONS)}."
            ' on_exhaust is "stop" or "escalate".',
            "- If return_contract.require_citations is true, min_citations >= 1.",
            f"- model.tier is one of the card's allowed_tiers. model.name is \"{model_name}\".",
        ]
    )


SYSTEM_D_QA = (
    "Design a HarnessSpec for read-only repository question answering. "
    "Return exactly one object following the supplied schema. "
    "The parent permits source exploration, and a reviewer assesses the answer after return. "
    "Do not invent source paths, named tests, test selectors, or test output. "
    "Command fields accept a single allowlisted identifier without arguments. "
    "Include only checks you can justify. Repository test execution is unavailable. "
    # Feasibility, not a design choice: no test runs here, so a contract that
    # demands test output can never be met and every return would be rejected.
    "No test output can exist, so set return_contract.require_test_output to false. "
    # Same reason: the SWE-QA runner denies every test hook, so a test hook
    # fails and the return is rejected regardless of the answer.
    "Test hooks would execute repository code, which is denied, so use no hook of kind test."
)


def _design_role(task: dict) -> str:
    """D's system message. Coding tasks keep SYSTEM_D unchanged.

    A task with ``assessment == "external_qa"`` (the SWE-QA runner) gets the
    read-only QA message for its first design call and for every repair call.
    """
    if task.get("assessment") != "external_qa":
        return SYSTEM_D
    return SYSTEM_D_QA


def _task_block(task: dict, card: CapabilityCard) -> str:
    return (
        f"Task id: {task['task_id']}\n"
        f"Task:\n{task['statement'].strip()}\n\n"
        f"Parent capability card (the most you may grant):\n{json.dumps(card.to_dict())}"
    )


SYSTEM_D = (
    "You are the orchestrator of a coding agent. You delegate one task to a subagent and design"
    " the harness it runs inside. Reply with exactly one JSON object, a HarnessSpec. Add no field"
    " the schema does not define. Write the goal, the acceptance tests, and the context slice"
    " yourself; nothing will fill them in for you."
)


def spec_messages(task: dict, card: CapabilityCard, model_name: str) -> list[dict]:
    user = (
        f"{_task_block(task, card)}\n\n"
        f"HarnessSpec JSON Schema:\n{_schema_text()}\n\n"
        f"{_rules(card, model_name)}\n\n"
        f'Use task_id "{task["task_id"]}". Reply with the HarnessSpec only.'
    )
    return [{"role": "system", "content": _design_role(task)}, {"role": "user", "content": user}]


def hint(error: SpecError, card: CapabilityCard, previous) -> str | None:
    """The values the compiler would accept at this path, read off the card.

    The validator's message says what is wrong. A hint says what is allowed,
    as a compiler diagnostic does. The validator itself is unchanged.
    """
    code, path = error.code, error.path
    if code == "command.unknown":
        names = ", ".join(f'"{name}" (kind {kind})' for name, kind in sorted(ALLOWED_COMMANDS.items()))
        return f"use one of these command names exactly, not a shell command: {names}"
    if code in ("context.path", "context.empty"):
        return f"paths must lie inside: {list(card.context_paths)}"
    if code in ("tool.path", "tool.privilege", "tool.unknown"):
        grants = {name: {"permission": g.permission, "paths": list(g.paths)} for name, g in card.tools.items()}
        return f"tools on the card: {json.dumps(grants)}"
    if code in ("budget.above_parent", "budget.infeasible"):
        return (f"max_steps <= {card.max_steps}, max_tokens <= {card.max_tokens}, "
                f"max_seconds <= {card.max_seconds}, and max_tokens >= max_steps")
    if code == "model.tier":
        return f"tier must be one of {list(card.allowed_tiers)}"
    if path.startswith("goal.acceptance_tests"):
        return "add at least one acceptance test, e.g. {\"id\": \"suite\", \"command\": \"unittest\"}"
    if code == PARSE_ERROR:
        return "reply with one JSON object and nothing else"
    return None


def repair_messages(task: dict, card: CapabilityCard, model_name: str, previous,
                    errors: list[SpecError]) -> list[dict]:
    if isinstance(previous, dict):
        shown = "Your previous spec, after the compiler clamped what it may:\n" + json.dumps(previous)
    else:
        shown = "Your previous reply was not a JSON object:\n" + str(previous)[:2000]
    items = []
    for error in errors:
        item = error.as_dict()
        extra = hint(error, card, previous)
        if extra:
            item["allowed"] = extra
        items.append(item)
    listed = json.dumps(items)
    user = (
        f"{_task_block(task, card)}\n\n"
        f"HarnessSpec JSON Schema:\n{_schema_text()}\n\n"
        f"{_rules(card, model_name)}\n\n"
        f"{shown}\n\n"
        f"The compiler still reports these typed errors:\n{listed}\n\n"
        "Return the full corrected HarnessSpec as one JSON object. Fix every error listed."
    )
    return [{"role": "system", "content": _design_role(task)}, {"role": "user", "content": user}]


SYSTEM_C = (
    "You are the orchestrator of a coding agent. You delegate one task to a subagent by naming"
    " an instruction, a context, a tool set, and a model. Reply with exactly one JSON object."
)


def tuple_messages(task: dict, card: CapabilityCard, model_name: str) -> list[dict]:
    user = (
        f"{_task_block(task, card)}\n\n"
        "Reply with one JSON object with exactly these four fields:\n"
        '- "instruction": the instruction for the subagent (string)\n'
        '- "context": the paths the subagent may see (list of strings)\n'
        '- "tools": the tool names it may call (list of strings)\n'
        f'- "model": the model it runs on (string, use "{model_name}")'
    )
    return [{"role": "system", "content": SYSTEM_C}, {"role": "user", "content": user}]


SYSTEM_B = (
    "You are the orchestrator of a coding agent. You delegate one task to a subagent by writing"
    " it a brief in plain prose."
)


def brief_messages(task: dict, card: CapabilityCard) -> list[dict]:
    user = (
        f"{_task_block(task, card)}\n\n"
        "Write the brief the subagent will receive: what to do, what it may look at and use,"
        " how to tell it is done, and what to report back. Plain text, no JSON."
    )
    return [{"role": "system", "content": SYSTEM_B}, {"role": "user", "content": user}]


# --------------------------------------------------------------------------- parsing

def parse_object(text: str):
    """Return (object, errors). A reply that is not one JSON object is a typed error."""
    body = text.strip()
    if body.startswith("```"):
        body = body.strip("`")
        body = body[body.find("\n") + 1:] if "\n" in body else body
    try:
        value = json.loads(body)
    except json.JSONDecodeError as exc:
        return None, [SpecError(PARSE_ERROR, "", f"reply is not JSON: {exc.msg}")]
    if not isinstance(value, dict):
        return None, [SpecError(PARSE_ERROR, "", "reply is JSON but not an object")]
    return value, []


def _codes(errors) -> list[str]:
    return sorted({error.code if isinstance(error, SpecError) else error["code"] for error in errors})


def missing_acceptance_test(errors) -> bool:
    for error in errors:
        path = error.path if isinstance(error, SpecError) else error["path"]
        if path.startswith("goal.acceptance_tests") or path == "goal":
            return True
    return False


def _call(client, messages, seed, json_mode, log, round_number, kind):
    reply = client.chat(messages, seed=seed, json_mode=json_mode)
    entry = {
        "round": round_number,
        "kind": kind,
        "prompt_tokens": reply.prompt_tokens,
        "output_tokens": reply.output_tokens,
        "seconds": reply.seconds,
        "reply": reply.content,
    }
    log.append(entry)
    return reply, entry


# --------------------------------------------------------------------------- repair loop

def repair_with_model(draft, task: dict, card: CapabilityCard, seed: int, client,
                      model_name: str, log: list[dict], first_errors=None,
                      max_rounds: int = MAX_REPAIR_ROUNDS):
    """Drive a draft to validity: compiler clamp first, then the model, per round.

    Returns (spec, remaining_errors, rounds). ``log`` gains one entry per model
    call, with the codes the compiler cleared and the codes the model cleared.
    """
    spec = draft
    errors = list(first_errors) if first_errors is not None else (
        validate(spec, card) if isinstance(spec, dict) else [SpecError(PARSE_ERROR, "", "no object")]
    )
    rounds = 0
    while errors and rounds < max_rounds:
        rounds += 1
        before = _codes(errors)
        if isinstance(spec, dict):
            clamped = repair_until_valid(spec, card)
            base, remaining = clamped.spec, clamped.remaining
        else:
            base, remaining = spec, errors
        if not remaining:
            log.append({"round": rounds, "kind": "compiler", "errors_before": before,
                        "cleared_by_compiler": before, "errors_after": []})
            return base, [], rounds
        reply, entry = _call(client, repair_messages(task, card, model_name, base, remaining),
                             seed, True, log, rounds, "repair")
        parsed, parse_errors = parse_object(reply.content)
        spec = parsed if parsed is not None else reply.content
        errors = parse_errors or validate(parsed, card)
        entry.update(
            errors_before=before,
            cleared_by_compiler=sorted(set(before) - set(_codes(remaining))),
            sent_to_model=_codes(remaining),
            errors_after=_codes(errors),
        )
        if isinstance(parsed, dict) and isinstance(base, dict) and parsed == base:
            # Same prompt, same seed, same reply: another round would repeat it.
            entry["stopped"] = "unchanged"
            break
    if errors and isinstance(spec, dict):
        # The last reply still gets the free compiler clamp. It is not a round.
        clamped = repair_until_valid(spec, card)
        spec, errors = clamped.spec, clamped.remaining
    return spec, list(errors), rounds


# --------------------------------------------------------------------------- design()

def design(task: dict, card: CapabilityCard, designer: str, seed: int, client=None) -> dict:
    """Run one designer on one task.

    ``task`` is ``{"task_id": str, "statement": str}``. ``client`` is an
    ``OllamaClient`` (or a test double with the same ``chat``); it is created
    from ``pilot/model.json`` when omitted and the designer needs a model.
    """
    if designer not in DESIGNERS:
        raise ValueError(f"designer must be one of {DESIGNERS}")
    pin = load_pin()
    model_name = pin["name"]
    started = time.monotonic()
    log: list[dict] = []
    result = {
        "designer": designer,
        "task_id": task["task_id"],
        "seed": seed,
        "model": model_name,
        "model_digest": pin["digest"],
    }

    if designer == "A":
        spec = fixed_generic_harness(task["task_id"], card, task["statement"])
        spec["model"]["name"] = model_name
        errors = validate(spec, card)
        result.update(spec=spec, design_tokens=0, rounds=0, first_pass_valid=not errors,
                      valid=not errors, first_pass_errors=_codes(errors),
                      remaining_errors=[e.as_dict() for e in errors])
    else:
        if client is None:
            from harnessspec.llm import OllamaClient

            client = OllamaClient(pin)
        if designer == "B":
            reply, _ = _call(client, brief_messages(task, card), seed, False, log, 0, "design")
            result.update(spec=free_text_brief(reply.content), design_tokens=reply.tokens, rounds=0,
                          first_pass_valid=None, valid=None, first_pass_errors=[],
                          remaining_errors=[])
        elif designer == "C":
            reply, _ = _call(client, tuple_messages(task, card, model_name), seed, True, log, 0, "design")
            raw, parse_errors = parse_object(reply.content)
            spec = _tuple_as_emitted(task["task_id"], raw)
            errors = parse_errors or validate(spec, card)
            result.update(spec=spec, design_tokens=reply.tokens, rounds=0,
                          first_pass_valid=not errors, valid=not errors,
                          first_pass_errors=_codes(errors),
                          remaining_errors=[e.as_dict() for e in errors])
        else:
            reply, _ = _call(client, spec_messages(task, card, model_name), seed, True, log, 0, "design")
            draft, parse_errors = parse_object(reply.content)
            first_errors = parse_errors or validate(draft, card)
            spec, remaining, rounds = repair_with_model(
                draft if draft is not None else reply.content, task, card, seed, client,
                model_name, log, first_errors=first_errors)
            result.update(spec=spec, design_tokens=_tokens(log), rounds=rounds,
                          first_pass_valid=not first_errors, valid=not remaining,
                          first_pass_errors=_codes(first_errors),
                          remaining_errors=[e.as_dict() for e in remaining])

    result["missing_acceptance_test"] = missing_acceptance_test(result["remaining_errors"])
    result["wall_clock_s"] = round(time.monotonic() - started, 3)
    result["log"] = log
    return result


def _tokens(log: list[dict]) -> int:
    return sum(entry.get("prompt_tokens", 0) + entry.get("output_tokens", 0) for entry in log)


def _tuple_as_emitted(task_id: str, raw) -> dict:
    """Build condition C's object from the model's four fields, without repair.

    Well-typed fields go through ``aorchestra_tuple``. Ill-typed ones are kept
    as emitted, so the validator scores what the model wrote.
    """
    if not isinstance(raw, dict):
        return {"spec_version": SPEC_VERSION, "task_id": task_id}
    instruction = raw.get("instruction")
    context = raw.get("context")
    tools = raw.get("tools")
    model = raw.get("model")
    typed = (
        isinstance(instruction, str)
        and isinstance(context, list) and all(isinstance(item, str) for item in context)
        and isinstance(tools, list) and all(isinstance(item, str) for item in tools)
        and isinstance(model, str)
    )
    if typed:
        return aorchestra_tuple(task_id, instruction, context, tools, model)
    return {
        "spec_version": SPEC_VERSION,
        "task_id": task_id,
        "goal": {"statement": instruction},
        "context": {"include": context, "exclude": []},
        "tools": tools,
        "model": {"name": model},
    }


def fixture_task(name: str = "off_by_one") -> dict:
    """The task text for a fixture is its README."""
    readme = ROOT / "fixtures" / name / "README.md"
    return {"task_id": name, "statement": Path(readme).read_text(encoding="utf-8")}
