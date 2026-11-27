"""Run SWE-bench instances unattended.

The cluster job puts the instance's Python on PATH and serves the pinned
model. Example::

    PYTHONPATH=src python3 pilot/run_swebench.py \
        --designers A D --seeds 1 \
        --instances astropy__astropy-12907 \
        --workdir /tmp/swebench \
        --output pilot/swebench_results.json \
        --ollama-host http://127.0.0.1:11434

Finished rows are skipped. Results and traces are replaced atomically.
No instance in this repository has been installed or run yet.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from harnessspec.llm import OllamaClient, load_pin
from harnessspec.results import check_output_path
from harnessspec.swebench import MAX_TOKENS, run_plan

ROOT = Path(__file__).resolve().parents[1]
INSTANCES = ROOT / "pilot" / "swebench_instances.json"


def selected_instances(path: Path, ids: list[str] | None) -> list[dict]:
    document = json.loads(path.read_text(encoding="utf-8"))
    rows = document["instances"]
    if not ids:
        return rows
    wanted = set(ids)
    chosen = [row for row in rows if row["instance_id"] in wanted]
    missing = wanted - {row["instance_id"] for row in chosen}
    if missing:
        raise SystemExit(f"unknown instance ids: {', '.join(sorted(missing))}")
    return chosen


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run SWE-bench designers against the pinned model.")
    parser.add_argument("--designers", nargs="+", default=["A", "D"])
    parser.add_argument("--seeds", nargs="+", type=int, default=[1])
    parser.add_argument("--instances", nargs="*", default=None)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ollama-host", default="http://127.0.0.1:11434")
    parser.add_argument("--instances-file", type=Path, default=INSTANCES)
    parser.add_argument("--repo-summary", action="store_true",
                        help="v2: give the designer the registered repository summary (depth-2 tracked paths)")
    args = parser.parse_args(argv)
    for designer in args.designers:
        if designer not in {"A", "B", "C", "D"}:
            raise SystemExit(f"unknown designer {designer}")
    trace_dir = args.output.parent / f"{args.output.stem}_traces"
    check_output_path(args.output)
    check_output_path(trace_dir)
    pin = load_pin()
    created = {"client": None}

    def client_factory():
        if created["client"] is None:
            client = OllamaClient(pin, host=args.ollama_host)
            # A reply longer than the run's whole generated-token budget can never be
            # admitted; capping it stops a looping generation from hanging the job.
            # The largest reply in every recorded run is 2,001 tokens, so this changes none.
            client.max_output_tokens = MAX_TOKENS
            created["client"] = client
        return created["client"]

    rows = run_plan(
        selected_instances(args.instances_file, args.instances),
        args.designers,
        args.seeds,
        args.workdir,
        args.output,
        trace_dir,
        pin,
        client_factory,
        with_repo_summary=args.repo_summary,
    )
    print(json.dumps({"rows": len(rows), "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
