"""Audit one SWE-QA treatment and export aggregates without grading identifiers.

Run as PYTHONPATH=src:. python3 -m pilot.sweqa_metrics. Re-open the pinned
sources so the retrospective and prospective evidence rates can be reproduced.
"""

import argparse
from collections import Counter, defaultdict
from contextlib import ExitStack
import json
from pathlib import Path
import random
from statistics import mean

from harnessspec.execution import NotExecutable, executable_spec
from harnessspec.llm import load_pin
from harnessspec.results import check_output_path, read_results, result_key, write_json
from harnessspec.sweqa import load_manifest, read_only_card
from pilot.metrics import BOOTSTRAP_SEED, RESAMPLES, amortization, matched_pairs, paired_bootstrap
from pilot.run_sweqa import (EXPERIMENT, HISTORICAL_PROTOCOL, PROTOCOL, check_evidence,
                             load_artifact, prepare_sources, source_verified_silent, task_prompt)


def ratio(value, denominator):
    return value / denominator if denominator else None


def group_summary(runs):
    n = len(runs)
    accepted = sum(r["accepted"] for r in runs)
    grounded = sum(r["grounded"] for r in runs)
    pending = sum(r["resolved"] is None for r in runs)
    correct = sum(r["resolved"] is True for r in runs)
    silent = sum(r["verified_silent"] for r in runs)
    costs = {field: sum(r[field] for r in runs) for field in
             ("design_tokens", "subagent_tokens", "rounds", "budget_violations", "tool_denials", "hook_failures")}
    total = costs["design_tokens"] + costs["subagent_tokens"]
    grades = sum(r["gradable"] for r in runs) - pending
    return {
        "attempted": n, "attempts_by_seed": dict(sorted(Counter(r["seed"] for r in runs).items())),
        "accepted": accepted, "acceptance_rate": accepted / n,
        "failed_without_gradable_answer": sum(not r["gradable"] for r in runs),
        "finalized_rows": n - pending, "graded_answers": grades, "pending_grades": pending,
        "correct_finalized": correct, "accuracy_all_attempts": None if pending else correct / n,
        "accuracy_graded_answers": ratio(correct, grades),
        "format_silent": sum(r["format_silent"] for r in runs),
        "verified_silent": silent, "silent_per_attempt": silent / n,
        "silent_per_accepted": ratio(silent, accepted), "grounded_returns": grounded,
        "verified_citation_coverage_per_accepted": ratio(grounded, accepted),
        "repository_grounded_per_attempt": grounded / n,
        "usable_citations_in_accepted_answers": sum(r["usable"] for r in runs if r["accepted"]),
        **costs, "total_tokens": total, "tokens_per_correct": None if pending else ratio(total, correct),
        "first_pass_validity": None if runs[0]["designer"] == "B" else mean(r["first_pass_valid"] for r in runs),
        "wall_clock_s": round(sum(r["wall_clock_s"] for r in runs), 3),
    }


def conditional_difference(left, right):
    """Ratio difference on matched attempts, resampling whole task clusters."""
    groups = defaultdict(list)
    for a, b in matched_pairs(left, right):
        groups[a["task_id"]].append((a, b))
    # Average each task's seeds before assigning equal weight to tasks.
    clusters = [[mean(pair[i][metric] for pair in group) for i in (0, 1)
                 for metric in ("verified_silent", "accepted")] for group in groups.values()]

    def delta(sample):
        if not sample:
            return None
        ls, la, rs, ra = map(sum, zip(*sample))
        return 100 * (ls / la - rs / ra) if la and ra else None

    point = delta(clusters)
    values = []
    if point is not None and len(clusters) >= 2:
        rng = random.Random(BOOTSTRAP_SEED)
        for _ in range(RESAMPLES):
            value = delta(rng.choices(clusters, k=len(clusters)))
            if value is not None:
                values.append(value)
    values.sort()
    return {"difference_pp": point, "defined_resamples": len(values),
            "ci95_given_defined": [values[int(q * (len(values) - 1))] for q in (0.025, 0.975)] if values else None}


def analyze_attempts(runs, diagnostics):
    by_designer = defaultdict(list)
    for row in runs:
        by_designer[row["designer"]].append(row)
    a, d = by_designer.get("A", []), by_designer.get("D", [])
    savings = paired_bootstrap(a, d, lambda r: r["subagent_tokens"])
    delta = savings["difference"]
    h2 = {}
    for name in "BC":
        if d and name in by_designer:
            other = by_designer[name]
            h2["D_vs_" + name] = {
                "silent_per_attempt_pp": paired_bootstrap(d, other, lambda r: 100 * r["verified_silent"]),
                "silent_per_accepted_pp": conditional_difference(d, other),
            }
    quality = amortization(a, d, diagnostics)
    return {
        "designers": {k: group_summary(v) for k, v in sorted(by_designer.items())},
        "h2": h2,
        "h4": {"observed_A_minus_D_subagent_tokens": savings,
               "attempt_cost_status": ("undefined" if delta is None else
                                       "no_finite_break_even" if delta <= 0 else "requires_reuse_scenario"),
               "quality_adjusted_status": "see_scenarios" if quality["scenarios"] else "undefined",
               "matched_correct_pairs": sum(x["resolved"] is True and y["resolved"] is True
                                            for x, y in matched_pairs(a, d)),
               "conditional_reuse_scenarios": quality["scenarios"], "observed_spec_cache_hits": 0},
    }


def verify_adapter(record, instance):
    card = read_only_card()
    if record["parent_card"] != card.to_dict():
        raise ValueError("parent capability card changed")
    error = None
    try:
        spec = executable_spec(record["design"], task_prompt(instance), card)
    except NotExecutable as exc:
        spec = None
        error = {"reason": exc.reason, "detail": exc.detail}
    row, detail = record["row"], record["diagnostics"]
    if spec != record["executable_spec"] or error != detail["not_executable"]:
        raise ValueError("saved adapter decision differs from replay")
    if (spec is None) != (record["runtime_trace"] is None):
        raise ValueError("runtime execution disagrees with adapter decision")
    if spec is None and (row["resolved"] is not False or row["subagent_tokens"]):
        raise ValueError("rejected design has an execution or success")
    if detail["compiled_validity_applicable"] != (record["designer"] != "B"):
        raise ValueError("incorrect validity applicability")
    if row["first_pass_valid"] != bool(record["design"]["first_pass_valid"]):
        raise ValueError("incorrect as-emitted validity")
    if row["rounds"] != record["design"]["rounds"] or row["design_tokens"] != record["design"]["design_tokens"]:
        raise ValueError("design repair or token ledger mismatch")
    charged = sum(c["charged_tokens"] for c in record["transcript"] if c["stage"] == "subagent")
    if charged != (record["runtime_trace"] or {}).get("tokens_used", 0):
        raise ValueError("runtime charged-token ledger mismatch")


def audit(trace_dir, result_path, energy_dir, instances, workspaces, protocol):
    results = {result_key(r): r for r in read_results([result_path])}
    manifest = {i["question_id"]: i for i in instances}
    pin = load_pin()
    runs, diagnostics = [], {}
    energy = {source: [] for source in ("cpu", "gpu")}
    for path in sorted(trace_dir.glob("*.json")):
        key = result_key(json.loads(path.read_text()))
        if key in diagnostics or key[0] != "sweqa":
            raise ValueError(f"{path}: duplicate or foreign identity")
        instance = manifest[key[1]]
        record = load_artifact(path, key, instance, pin, grade_only=True)
        if record["protocol"] != protocol:
            raise ValueError(f"{path}: incompatible treatment")
        if protocol == PROTOCOL:
            verify_adapter(record, instance)
        row = record["row"]
        detail = record["diagnostics"]
        answer = record["answer"]
        accepted = detail["return_accepted"]
        runtime = record["runtime_trace"] or {}
        if accepted != (runtime.get("return_accepted") is True):
            raise ValueError(f"{path}: acceptance disagrees with runtime")
        evidence = check_evidence(instance, answer, workspaces[instance["repo"], instance["revision"]])
        if evidence != record["evidence"]:
            raise ValueError(f"{path}: evidence disagrees with pinned source")
        silent = source_verified_silent(accepted, answer, evidence)
        format_silent = runtime.get("silent_handoff", False)
        if row["silent_handoff"] != (silent if protocol == PROTOCOL else format_silent):
            raise ValueError(f"{path}: handoff definition mismatch")
        if protocol == PROTOCOL and detail["format_silent_handoff"] != format_silent:
            raise ValueError(f"{path}: format gate mismatch")
        for stage in ("design", "subagent"):
            tokens = sum(c["prompt_tokens"] + c["output_tokens"] for c in record["transcript"] if c["stage"] == stage)
            if tokens != row[stage + "_tokens"]:
                raise ValueError(f"{path}: server token ledger mismatch")
        final = results.get(key)
        if final is None and row["resolved"] is not None:
            raise ValueError(f"{path}: finalized row missing")
        if final is not None:
            expected = dict(row)
            if expected["resolved"] is None:
                expected["resolved"] = final["resolved"]
            if final != expected:
                raise ValueError(f"{path}: finalized row differs from trace")
        usable = evidence["usable_repository_citations"] if evidence else 0
        runs.append({**(final or row), "accepted": accepted, "gradable": record["grading_id"] is not None,
                     "format_silent": format_silent, "verified_silent": silent, "usable": usable,
                     "grounded": bool(accepted and answer and answer["summary"].strip() and usable)})
        diagnostics[key] = detail
        sidecar = json.loads((energy_dir / path.name).read_text())
        if result_key(sidecar) != key:
            raise ValueError(f"{path}: energy identity differs")
        for source in energy:
            energy[source].append(sidecar["energy"][source])
    if not runs or results.keys() - diagnostics.keys():
        raise ValueError("empty experiment or result without a corresponding trace")
    return {
        "protocol": protocol,
        "analysis": "source_verified_retrospective" if protocol == HISTORICAL_PROTOCOL else "source_verified_v2",
        **analyze_attempts(runs, diagnostics),
        "energy": {source: {"coverage": sum(s["joules"] is not None for s in samples),
                            "statuses": dict(Counter(s["status"] for s in samples)),
                            "joules": sum(s["joules"] for s in samples) if all(s["joules"] is not None for s in samples) else None}
                   for source, samples in energy.items()},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", choices=[PROTOCOL, HISTORICAL_PROTOCOL], default=PROTOCOL)
    parser.add_argument("--trace-dir", type=Path, default=EXPERIMENT / "traces")
    parser.add_argument("--results", type=Path, default=EXPERIMENT / "results.json")
    parser.add_argument("--energy-dir", type=Path, default=EXPERIMENT / "energy")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--archive-cache", type=Path, default=Path("pilot/tmp/sweqa-archives"))
    args = parser.parse_args()
    check_output_path(args.output)
    if args.output.resolve() == args.results.resolve() or any(
        args.output.resolve().is_relative_to(p.resolve()) for p in (args.trace_dir, args.energy_dir)
    ):
        parser.error("aggregate output overlaps evidence")
    instances = load_manifest(Path("pilot/sweqa_instances.json"))
    with ExitStack() as stack:
        sources = prepare_sources(instances, args.archive_cache, stack)
        write_json(args.output, audit(args.trace_dir, args.results, args.energy_dir, instances, sources, args.protocol))


if __name__ == "__main__":
    main()
