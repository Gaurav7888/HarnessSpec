"""Run designers A and D on the off-by-one fixture with the pinned model.

A is ``fixed_generic_harness``. D comes from ``design()`` (Join 1), not the
``harness_d`` stand-in, so its row carries real ``design_tokens``, ``rounds``,
and ``first_pass_valid``. The subagent is the model in ``pilot/model.json``,
called through ``OllamaClient``, the same client the orchestrator and the
SWE-QA runner use.

Token accounting matches ``pilot/run_sweqa.py``. The step budget charges the
tokens the model generates on each step. ``subagent_tokens`` in the row is the
full server count, prompt plus output, summed over every step.

Writes ``pilot/subagent_fixture_pinned.json`` and ``pilot/subagent_fixture_pinned_traces.json``.
The earlier Grok rows in ``pilot/subagent_fixture.json`` are frozen in the SWE-QA
snapshot manifest and kept unchanged as history. They are not results.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from harnessspec.llm import ROOT, OllamaClient, Reply, load_pin
from harnessspec.orchestrator import design, fixture_task
from harnessspec.parent import reference_parent
from harnessspec.runtime import SystemClock
from harnessspec.subagent import result_row, run_subagent

WORKSPACE = ROOT / "fixtures" / "off_by_one"
ROWS = ROOT / "pilot" / "subagent_fixture_pinned.json"
TRACES = ROOT / "pilot" / "subagent_fixture_pinned_traces.json"


class PinnedSubagentClient:
    """``OllamaClient`` whose step budget charges generated tokens only."""

    def __init__(self, client: OllamaClient):
        self.client = client

    def chat(self, messages, seed, json_mode=False) -> Reply:
        return self.client.chat(messages, seed=seed, json_mode=json_mode)

    def budget_tokens(self, reply: Reply) -> int:
        return reply.output_tokens + reply.reasoning_tokens


def run(seed: int = 1) -> dict:
    pin = load_pin()
    client = OllamaClient(pin)
    parent = reference_parent()
    task = fixture_task()
    designs = {
        "A": ("fixed_generic_harness", design(task, parent, "A", seed)),
        "D": ("design", design(task, parent, "D", seed, client=client)),
    }
    rows = []
    traces = []
    for designer, (source, result) in designs.items():
        spec = result["spec"]
        if not result["valid"]:
            # An invalid design is an orchestrator failure and is not run.
            rows.append({
                "task_id": task["task_id"], "benchmark": "fixture", "designer": designer,
                "seed": seed, "model": pin["name"], "model_digest": pin["digest"],
                "spec_source": source, "design_tokens": result["design_tokens"],
                "subagent_tokens": 0, "rounds": result["rounds"],
                "first_pass_valid": result["first_pass_valid"], "resolved": False,
                "silent_handoff": False, "budget_violations": 0, "tool_denials": 0,
                "hook_failures": 0, "wall_clock_s": result["wall_clock_s"],
            })
            traces.append({"designer": designer, "spec_source": source, "design": result,
                           "trace": None, "log": []})
            continue
        held = tempfile.TemporaryDirectory(prefix="harnessspec-subagent-")
        try:
            shutil.copytree(WORKSPACE, Path(held.name), dirs_exist_ok=True)
            print(f"subagent {designer} via {pin['name']}", flush=True)
            outcome = run_subagent(spec, parent, Path(held.name), seed,
                                   PinnedSubagentClient(client), clock=SystemClock())
        finally:
            held.cleanup()
        row = result_row(spec, designer, seed, pin, source, outcome)
        row.update(
            design_tokens=result["design_tokens"],
            rounds=result["rounds"],
            first_pass_valid=result["first_pass_valid"],
            subagent_tokens=sum(item["prompt_tokens"] + item["output_tokens"] for item in outcome["log"]),
            budget_charged_tokens=outcome["subagent_tokens"],
            wall_clock_s=round(result["wall_clock_s"] + outcome["wall_clock_s"], 3),
        )
        rows.append(row)
        traces.append({"designer": designer, "spec_source": source, "design": result,
                       "trace": outcome["trace"].as_dict(), "log": outcome["log"]})
    payload = {
        "seed": seed,
        "model": pin["name"],
        "model_digest": pin["digest"],
        "options": pin["options"],
        "token_accounting": (
            "subagent_tokens is the server's prompt plus output count over every step. "
            "budget_charged_tokens is what the step budget charged: generated tokens only, "
            "as in pilot/run_sweqa.py. design_tokens comes from design()."
        ),
        "rows": rows,
    }
    ROWS.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    TRACES.write_text(json.dumps(traces, indent=2) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(json.dumps(run()["rows"], indent=2))
