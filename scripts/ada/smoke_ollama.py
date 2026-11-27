"""Smoke test for the pinned model on an Ada GPU node.

Runs inside a SLURM job after ``ollama serve`` is up on ``--host``:

1. the digest check in ``OllamaClient`` against ``pilot/model.json``
2. ``design()`` for designer D on ``fixtures/off_by_one`` (seed 1), timed
3. the fixture subagent for A and D, end to end, timed

Writes ``smoke.json`` to ``--out``. Nothing in the repository is modified.

    python scripts/ada/smoke_ollama.py --host http://127.0.0.1:PORT --out RUN_DIR
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from harnessspec.execution import executable_spec  # noqa: E402
from harnessspec.llm import OllamaClient, Reply, load_pin  # noqa: E402
from harnessspec.orchestrator import design, fixture_task  # noqa: E402
from harnessspec.parent import reference_parent  # noqa: E402
from harnessspec.runtime import SystemClock  # noqa: E402
from harnessspec.subagent import run_subagent  # noqa: E402


class Generated:
    """Step budget charges generated tokens, as in pilot/run_subagent.py."""

    def __init__(self, client):
        self.client = client

    def chat(self, messages, seed, json_mode=False) -> Reply:
        return self.client.chat(messages, seed=seed, json_mode=json_mode)

    def budget_tokens(self, reply: Reply) -> int:
        return reply.output_tokens + reply.reasoning_tokens


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    pin = load_pin()
    started = time.monotonic()
    client = OllamaClient(pin, host=args.host)  # raises if the digest differs
    report = {"model": pin["name"], "digest_ok": True, "host": args.host, "runs": []}

    task, card = fixture_task(), reference_parent()
    for designer in ("A", "D"):
        t0 = time.monotonic()
        result = design(task, card, designer, 1, client=client)
        design_s = round(time.monotonic() - t0, 2)
        entry = {"designer": designer, "design_s": design_s, "design_tokens": result["design_tokens"],
                 "first_pass_valid": result["first_pass_valid"], "valid": result["valid"]}
        spec = executable_spec(result, task, card)
        held = tempfile.TemporaryDirectory(prefix="hs-smoke-")
        try:
            shutil.copytree(ROOT / "fixtures" / "off_by_one", Path(held.name), dirs_exist_ok=True)
            t1 = time.monotonic()
            outcome = run_subagent(spec, card, Path(held.name), 1, Generated(client), clock=SystemClock())
            entry["subagent_s"] = round(time.monotonic() - t1, 2)
        finally:
            held.cleanup()
        calls = outcome["log"]
        entry.update(
            resolved=outcome["resolved"],
            steps=len(calls),
            subagent_tokens=sum(c["prompt_tokens"] + c["output_tokens"] for c in calls),
            seconds_per_call=round(sum(c["seconds"] for c in calls) / max(1, len(calls)), 2),
            output_tokens_per_s=round(sum(c["output_tokens"] for c in calls)
                                      / max(1e-9, sum(c["seconds"] for c in calls)), 1),
        )
        report["runs"].append(entry)
        print(json.dumps(entry), flush=True)

    report["total_s"] = round(time.monotonic() - started, 2)
    (args.out / "smoke.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return 0 if all(run["resolved"] for run in report["runs"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
