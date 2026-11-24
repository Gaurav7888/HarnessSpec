"""Run designers A and D on the off-by-one fixture with Grok through the Cursor CLI.

A is ``fixed_generic_harness``. D is ``harness_d``. Neither spec comes from
``design()``, so ``design_tokens`` is 0 and ``spec_source`` names the stand-in.
The subagent model is ``grok-4.7-low`` via ``agent -p``. The Ollama pin in
``pilot/model.json`` is not called.

Writes ``pilot/subagent_fixture.json`` and ``pilot/subagent_fixture_traces.json``.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from harnessspec.cursor_cli import DEFAULT_MODEL, CursorCliClient
from harnessspec.designers import fixed_generic_harness, harness_d
from harnessspec.llm import ROOT
from harnessspec.parent import reference_parent
from harnessspec.runtime import FakeClock
from harnessspec.subagent import result_row, run_subagent

WORKSPACE = ROOT / "fixtures" / "off_by_one"
ROWS = ROOT / "pilot" / "subagent_fixture.json"
TRACES = ROOT / "pilot" / "subagent_fixture_traces.json"
STATEMENT = "Make add return the sum of its arguments."


def run(seed: int = 1) -> dict:
    client = CursorCliClient()
    pin = {"name": client.name, "digest": client.digest}
    parent = reference_parent()
    specs = [
        ("A", "fixed_generic_harness", fixed_generic_harness("off_by_one", parent, STATEMENT)),
        ("D", "harness_d", harness_d("off_by_one", STATEMENT)),
    ]
    rows = []
    traces = []
    for designer, source, spec in specs:
        held = tempfile.TemporaryDirectory(prefix="harnessspec-subagent-")
        try:
            shutil.copytree(WORKSPACE, Path(held.name), dirs_exist_ok=True)
            print(f"subagent {designer} via {DEFAULT_MODEL}", flush=True)
            outcome = run_subagent(
                spec,
                parent,
                Path(held.name),
                seed,
                client,
                clock=FakeClock(),
            )
        finally:
            held.cleanup()
        row = result_row(spec, designer, seed, pin, source, outcome)
        row["server_input_tokens"] = sum(item["prompt_tokens"] for item in outcome["log"])
        row["server_output_tokens"] = sum(item["output_tokens"] for item in outcome["log"])
        row["server_reasoning_tokens"] = sum(item["reasoning_tokens"] for item in outcome["log"])
        rows.append(row)
        traces.append(
            {
                "designer": designer,
                "spec_source": source,
                "trace": outcome["trace"].as_dict(),
                "log": outcome["log"],
            }
        )
    payload = {
        "seed": seed,
        "model": pin["name"],
        "model_digest": pin["digest"],
        "token_accounting": (
            "subagent_tokens is output tokens plus reasoning tokens, which is what the "
            "step budget charges. server_input_tokens is the CLI inputTokens figure and "
            "includes the agent preamble. The harness clock advances by duration_api_ms."
        ),
        "rows": rows,
    }
    ROWS.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    TRACES.write_text(json.dumps(traces, indent=2) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
