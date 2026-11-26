"""Validate benchmark runs and produce deterministic metrics and paired intervals."""

from __future__ import annotations

import argparse
from collections import defaultdict
from fractions import Fraction
import json
import math
from pathlib import Path
import random
from statistics import mean

from harnessspec.results import KEY_FIELDS, check_output_path, read_results, result_key, validate_result, write_json

BOOTSTRAP_SEED = 20261124
RESAMPLES = 10000


def total_tokens(row: dict) -> int:
    return row["design_tokens"] + row["subagent_tokens"]


def handoff_counts(rows: list[dict], diagnostics: dict) -> dict:
    silent = sum(row["silent_handoff"] for row in rows)
    accepted = [diagnostics.get(result_key(row), {}).get("return_accepted") for row in rows]
    known = sum(type(value) is bool for value in accepted)
    accepted_count = sum(value is True for value in accepted) if rows and known == len(rows) else None
    return {
        "silent_handoffs": silent, "silent_handoff_rate": silent / len(rows) if rows else None,
        "accepted_return_coverage": known, "accepted_returns": accepted_count,
        "acceptance_rate": accepted_count / len(rows) if accepted_count is not None else None,
        "silent_given_accepted": silent / accepted_count if accepted_count else None,
    }


def summarize(rows: list[dict], diagnostics: dict) -> dict:
    n = len(rows)
    correct = sum(row["resolved"] for row in rows)
    # A is compiler-checked, C is measured as emitted against the full schema,
    # and B's free-text brief has no compiled-spec validity.
    validity = [row["first_pass_valid"] for row in rows if row["designer"] != "B"]
    design = sum(row["design_tokens"] for row in rows)
    subagent = sum(row["subagent_tokens"] for row in rows)
    return {
        "attempted": n,
        "resolved": correct,
        "accuracy": correct / n if n else None,
        "first_pass_validity": mean(validity) if validity else None,
        "design_tokens": design,
        "subagent_tokens": subagent,
        "total_tokens": design + subagent,
        "mean_tokens": (design + subagent) / n if n else None,
        "tokens_per_correct": (design + subagent) / correct if correct else None,
        **handoff_counts(rows, diagnostics),
        **{field: sum(row[field] for row in rows)
           for field in ("budget_violations", "tool_denials", "hook_failures")},
        "mean_rounds": mean(row["rounds"] for row in rows) if n else None,
        "mean_wall_clock_s": mean(row["wall_clock_s"] for row in rows) if n else None,
    }


def matched_pairs(left: list[dict], right: list[dict]) -> list[tuple[dict, dict]]:
    def index(rows):
        return {(row["benchmark"], row["task_id"], row["seed"]): row for row in rows}

    first, second = index(left), index(right)
    return [(first[key], second[key]) for key in sorted(first.keys() & second.keys())]


def paired_bootstrap(left: list[dict], right: list[dict], metric,
                     resamples: int = RESAMPLES, seed: int = BOOTSTRAP_SEED) -> dict:
    """Difference left minus right, with equally weighted matched task clusters."""
    if resamples <= 0:
        raise ValueError("resamples must be positive")
    pairs = matched_pairs(left, right)
    task_differences = defaultdict(list)
    seeds = defaultdict(list)
    for first, second in pairs:
        task = (first["benchmark"], first["task_id"])
        task_differences[task].append(metric(first) - metric(second))
        seeds[task].append(first["seed"])
    values = [mean(differences) for differences in task_differences.values()]
    interval = None
    if len(values) >= 2:
        rng = random.Random(seed)
        distribution = sorted(mean(rng.choices(values, k=len(values))) for _ in range(resamples))
        interval = [distribution[int(q * (resamples - 1))] for q in (0.025, 0.975)]
    return {
        "difference": mean(values) if values else None, "ci95": interval,
        "matched_tasks": len(values), "matched_observations": len(pairs),
        "matched_seeds": sorted({value for group in seeds.values() for value in group}),
        "matched_seeds_by_task": [
            {"benchmark": benchmark, "task_id": task, "seeds": values}
            for (benchmark, task), values in seeds.items()
        ],
        "excluded_left": len(left) - len(pairs), "excluded_right": len(right) - len(pairs),
        "resamples": resamples, "bootstrap_seed": seed,
    }


def break_even(initial_design_tokens: int | None, savings: Fraction | int | float | None) -> dict:
    """Return the estimated number of tasks or explicitly classify its absence."""
    if initial_design_tokens is None or initial_design_tokens <= 0 or savings is None:
        return {"status": "undefined", "break_even_tasks": None}
    if savings <= 0:
        return {"status": "no_finite_break_even", "break_even_tasks": None}
    return {"status": "estimated", "break_even_tasks": math.ceil(Fraction(initial_design_tokens) / savings)}


def amortization(baseline: list[dict], designed: list[dict], diagnostics: dict) -> dict:
    groups = defaultdict(list)
    for reference, run in matched_pairs(baseline, designed):
        detail = diagnostics.get(result_key(run), {})
        group = detail.get("reuse_group")
        if group and detail.get("design_tokens_measured") is True and detail.get("design_valid") is True:
            # Compare work at matched correctness, so an aborted run cannot
            # create apparent savings by stopping early.
            if reference["resolved"] and run["resolved"]:
                groups[group].append((reference, run))
    scenarios = []
    for group, pairs in sorted(groups.items()):
        priming = next((run for _, run in pairs if run["design_tokens"] > 0), None)
        savings_by_task = defaultdict(list)
        for reference, run in pairs:
            if priming is not None and run["task_id"] != priming["task_id"]:
                savings_by_task[run["task_id"]].append(reference["subagent_tokens"] - run["subagent_tokens"])
        values = [Fraction(sum(values), len(values)) for values in savings_by_task.values()]
        savings = mean(values) if values else None
        initial = priming["design_tokens"] if priming else None
        scenarios.append({
            "group": group, "initial_design_tokens": initial,
            "priming_task": priming["task_id"] if priming else None,
            "priming_seed": priming["seed"] if priming else None,
            "matched_savings_tasks": len(values),
            "per_task_subagent_token_savings": float(savings) if savings is not None else None,
            **break_even(initial, savings),
        })
    return {
        "baseline": "A", "reuse_observed": False,
        "status": "conditional_estimate" if scenarios else "no_eligible_reuse_groups",
        "scenarios": scenarios,
    }


def validate_inputs(rows: list[dict], diagnostics: dict) -> dict:
    groups = defaultdict(lambda: defaultdict(list))
    pins = defaultdict(set)
    keys = set()
    for row in rows:
        validate_result(row)
        key = result_key(row)
        if key in keys:
            raise ValueError(f"duplicate run {key}")
        keys.add(key)
        acceptance = diagnostics.get(key, {}).get("return_accepted")
        if acceptance is not None and type(acceptance) is not bool:
            raise ValueError(f"{key}: return_accepted must be boolean or null")
        if row["silent_handoff"] and acceptance is False:
            raise ValueError(f"{key}: a rejected return cannot be a silent handoff")
        groups[row["benchmark"]][row["designer"]].append(row)
        pins[row["benchmark"]].add((row["model"], row["model_digest"]))
    if any(len(values) > 1 for values in pins.values()):
        raise ValueError("each benchmark input must use a single model pin")
    return groups


def analyze(rows: list[dict], diagnostics: dict | None = None) -> dict:
    diagnostics = diagnostics or {}
    groups = validate_inputs(rows, diagnostics)
    output = {}
    for benchmark, designers in sorted(groups.items()):
        comparisons = {}
        for baseline in "ABC":
            if baseline not in designers or "D" not in designers:
                continue
            left, right = designers["D"], designers[baseline]
            comparisons[f"D_vs_{baseline}"] = {
                "status": "preliminary_A_D" if baseline == "A" else "H2_comparison",
                "accuracy_pp": paired_bootstrap(left, right, lambda row: 100 * row["resolved"]),
                "silent_handoff_pp": paired_bootstrap(left, right, lambda row: 100 * row["silent_handoff"]),
                "total_tokens": paired_bootstrap(left, right, total_tokens),
            }
        output[benchmark] = {
            "designers": {name: summarize(data, diagnostics) for name, data in sorted(designers.items())},
            "comparisons": comparisons,
            "h2_pending": [name for name in "BC" if f"D_vs_{name}" not in comparisons],
            "h4": amortization(designers.get("A", []), designers.get("D", []), diagnostics),
            "three_seed_requirement_met": all(
                len(seeds) >= 3 for data in designers.values()
                for seeds in seeds_by_task(data).values()
            ),
        }
    return {"benchmarks": output}


def execution_handoffs(paths: list[Path], finalized: list[dict] | None = None) -> dict:
    """Analyze completed traces even when answer grading is still pending."""
    rows = []
    diagnostics = {}
    pending = defaultdict(int)
    protocols = set()
    scored = {result_key(row): row for row in finalized or [] if row["benchmark"] == "sweqa"}
    for directory in paths:
        if not directory.is_dir():
            raise ValueError(f"{directory}: expected a completed execution trace directory")
        for path in sorted(directory.glob("*.json")):
            trace = json.loads(path.read_text(encoding="utf-8"))
            protocols.add(trace.get("protocol"))
            if len(protocols) > 1:
                raise ValueError("cannot pool traces from different experiment protocols")
            row = trace["row"]
            key = result_key(row)
            if key != result_key(trace) or key[0] != "sweqa":
                raise ValueError(f"{path}: inconsistent SWE-QA trace identity")
            acceptance = trace["diagnostics"]["return_accepted"]
            if type(acceptance) is not bool:
                raise ValueError(f"{path}: return_accepted must be boolean")
            diagnostics[key] = trace["diagnostics"]
            if key in scored:
                completed = dict(row)
                if completed["resolved"] is None:
                    completed["resolved"] = scored[key]["resolved"]
                if scored[key] != completed:
                    raise ValueError(f"{path}: finalized row conflicts with trace")
            pending[key[2]] += row["resolved"] is None and key not in scored
            # Use the required boolean only for shape validation. Execution-only
            # analysis never reads answer correctness from the trace.
            rows.append({**row, "resolved": False} if row["resolved"] is None else row)
    designers = validate_inputs(rows, diagnostics).get("sweqa", {})
    comparisons = {}
    for baseline in "ABC":
        if baseline in designers and "D" in designers:
            comparisons[f"D_vs_{baseline}"] = paired_bootstrap(
                designers["D"], designers[baseline], lambda row: 100 * row["silent_handoff"],
            )
    totals = {}
    for name, runs in sorted(designers.items()):
        totals[name] = {
            "attempted": len(runs), **handoff_counts(runs, diagnostics),
            "design_tokens": sum(row["design_tokens"] for row in runs),
            "subagent_tokens": sum(row["subagent_tokens"] for row in runs),
            "total_tokens": sum(total_tokens(row) for row in runs),
            "mean_tokens": mean(total_tokens(row) for row in runs),
            "first_pass_validity": None if name == "B" else mean(row["first_pass_valid"] for row in runs),
            "mean_rounds": mean(row["rounds"] for row in runs),
            "mean_wall_clock_s": mean(row["wall_clock_s"] for row in runs),
            **{field: sum(row[field] for row in runs)
               for field in ("budget_violations", "tool_denials", "hook_failures")},
            "requires_external_grade": pending[name],
        }
    baseline = designers.get("A", [])
    designed = designers.get("D", [])
    savings = paired_bootstrap(baseline, designed, lambda row: row["subagent_tokens"])
    delta = savings["difference"]
    has_cost = any(run["design_tokens"] > 0 and diagnostics[result_key(run)].get("design_tokens_measured")
                   and diagnostics[result_key(run)].get("design_valid")
                   for _, run in matched_pairs(baseline, designed))
    # All attempts, including invalid designs, describe the observed workload.
    # A positive delta alone cannot identify a compatible spec for reuse.
    status = "undefined"
    if has_cost and delta is not None:
        status = "no_finite_break_even" if delta <= 0 else "requires_reuse_scenario"
    return {
        "attempt_cost_scenario": {"subagent_tokens_saved_A_minus_D": savings,
                                  "status": status, "reuse_observed": False},
        "designers": totals, "silent_handoff_difference_pp": comparisons,
        "h2_pending": [name for name in "BC" if f"D_vs_{name}" not in comparisons],
    }


def seeds_by_task(rows: list[dict]) -> dict:
    seeds = defaultdict(set)
    for row in rows:
        seeds[row["task_id"]].add(row["seed"])
    return seeds


def markdown(payload: dict) -> str:
    def display(value):
        if value is None:
            return "N/A"
        return f"{value:.4g}" if isinstance(value, float) else str(value)

    lines = ["# Benchmark metrics", "",
             "Accuracy, first-pass validity and silent handoffs use attempted runs for applicable conditions.",
             "Tokens per correct divides all consumed tokens by resolved runs.",
             "Accepted-return rates require complete diagnostic coverage.", ""]
    if not payload["benchmarks"]:
        lines.append("No finalized benchmark rows supplied.")
    for benchmark, analysis in payload["benchmarks"].items():
        lines += [f"## {benchmark}", ""]
        for columns in (
            ("attempted", "resolved", "accuracy", "first_pass_validity", "silent_handoffs",
             "silent_handoff_rate", "accepted_returns", "accepted_return_coverage", "silent_given_accepted"),
            ("design_tokens", "subagent_tokens", "total_tokens", "mean_tokens",
             "tokens_per_correct", "mean_rounds", "mean_wall_clock_s"),
            ("budget_violations", "tool_denials", "hook_failures"),
        ):
            lines += ["| Designer | " + " | ".join(key.replace("_", " ") for key in columns) + " |",
                      "| --- |" + " --- |" * len(columns)]
            for name, details in analysis["designers"].items():
                values = [display(details[key]) for key in columns]
                lines.append(f"| {name} | " + " | ".join(values) + " |")
            lines.append("")
        lines += ["", "| Comparison | Metric (D minus baseline) | Estimate | 95% CI | Matched tasks / pairs | Seeds | Unmatched D / baseline |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        for name, comparison in analysis["comparisons"].items():
            for metric in ("accuracy_pp", "silent_handoff_pp", "total_tokens"):
                values = comparison[metric]
                estimate = values["difference"]
                interval = values["ci95"]
                effect = "N/A" if estimate is None else f"{estimate:.2f}"
                ci = "N/A" if interval is None else f"[{interval[0]:.2f}, {interval[1]:.2f}]"
                lines.append(f"| {name} | {metric} | {effect} | {ci} | "
                             f"{values['matched_tasks']} / {values['matched_observations']} | "
                             f"{values['matched_seeds']} | {values['excluded_left']} / {values['excluded_right']} |")
        lines.append("")
        if "D_vs_A" in analysis["comparisons"]:
            lines.append("The A/D comparison is preliminary and does not test H2 against B or C.")
        if analysis["h2_pending"]:
            lines.append("Pending H2 comparisons with D: " + ", ".join(analysis["h2_pending"]) + ".")
        if not analysis["three_seed_requirement_met"]:
            lines.append("The supplied runs do not meet the registered three-seed requirement.")
        lines += ["", "H4 estimates are conditional on reuse. The analysis has no observed cache hits.",
                  "", "| Reuse group | Initial tokens | Savings/task | Status | Break-even tasks |",
                  "| --- | --- | --- | --- | --- |"]
        scenarios = analysis["h4"]["scenarios"]
        if not scenarios:
            lines.append("| N/A | N/A | N/A | No eligible reuse group | N/A |")
        for scenario in scenarios:
            columns = ("group", "initial_design_tokens", "per_task_subagent_token_savings",
                       "status", "break_even_tasks")
            lines.append("| " + " | ".join(str(scenario[k]) if scenario[k] is not None else "N/A"
                                             for k in columns) + " |")
        if analysis.get("energy"):
            lines += ["", "| Designer | Energy source | Measured runs | Joules | Watt-hours | Success/kWh |",
                      "| --- | --- | --- | --- | --- | --- |"]
            for item in analysis["energy"]:
                efficiency = item["success_per_kwh"]
                lines.append(f"| {item['designer']} | {item['source']} ({item['method']}) | "
                             f"{item['measured_runs']} | {item['joules']:.3f} | "
                             f"{item['watt_hours']:.5f} | "
                             + ("N/A" if efficiency is None else f"{efficiency:.4g}") + " |")
        lines.append("")
    if "sweqa_execution_only" in payload:
        lines += ["", "## SWE-QA execution-only metrics", "",
                  "Counts cover completed executions regardless of answer grading. A/D is preliminary.",
                  "",
                  "| Designer | Executions | Accepted | Acceptance rate | Silent | Silent/attempt | Silent/accepted |"
                  " Design tokens | Subagent tokens | Needs external grade |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        execution = payload["sweqa_execution_only"]
        for designer, counts in execution["designers"].items():
            fields = ("attempted", "accepted_returns", "acceptance_rate", "silent_handoffs", "silent_handoff_rate",
                      "silent_given_accepted", "design_tokens", "subagent_tokens", "requires_external_grade")
            values = [display(counts[key]) for key in fields]
            lines.append(f"| {designer} | " + " | ".join(values) + " |")
        lines += ["", "| Designer | First-pass validity | Combined tokens | Mean tokens | Mean rounds |"
                  " Mean wall time (s) | Budget violations | Tool denials | Hook failures |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for designer, counts in execution["designers"].items():
            fields = ("first_pass_validity", "total_tokens", "mean_tokens", "mean_rounds", "mean_wall_clock_s",
                      "budget_violations", "tool_denials", "hook_failures")
            lines.append(f"| {designer} | " + " | ".join(display(counts[key]) for key in fields) + " |")
        lines += ["", "| Contrast | Difference (pp) | 95% CI | Matched tasks / pairs | Seeds | Unmatched D / baseline |",
                  "| --- | --- | --- | --- | --- | --- |"]
        for contrast, comparison in execution["silent_handoff_difference_pp"].items():
            lines.append(f"| {contrast} | {display(comparison['difference'])} | "
                         f"{display(comparison['ci95'])} | "
                         f"{comparison['matched_tasks']} / {comparison['matched_observations']} | "
                         f"{comparison['matched_seeds']} | {comparison['excluded_left']} / "
                         f"{comparison['excluded_right']} |")
        scenario = execution["attempt_cost_scenario"]
        delta = scenario["subagent_tokens_saved_A_minus_D"]["difference"]
        lines += ["", f"Matched subagent token savings per attempted task (A minus D): {delta}. "
                  f"At this marginal cost: {scenario['status']}. Cache reuse was not measured."]
        if execution["h2_pending"]:
            lines += ["", "H2 contrasts pending for D versus " + " and ".join(execution["h2_pending"]) + "."]
    return "\n".join(lines) + "\n"


def read_sidecars(paths: list[Path], section: str) -> dict:
    records = {}
    for path in paths:
        files = sorted(path.glob("*.json")) if path.is_dir() else [path]
        for file in files:
            data = json.loads(file.read_text(encoding="utf-8"))
            for entry in data if isinstance(data, list) else [data]:
                values = entry.get(section)
                if values is None:
                    continue
                key = result_key(entry)
                if key in records:
                    raise ValueError(f"{file}: duplicate {section} for {key}")
                if not isinstance(values, dict):
                    raise ValueError(f"{file}: {section} must be an object")
                records[key] = values
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", nargs="*", type=Path)
    parser.add_argument("--diagnostics", nargs="+", type=Path, default=[])
    parser.add_argument("--energy", nargs="+", type=Path, default=[])
    parser.add_argument("--sweqa-executions", nargs="+", type=Path, default=[])
    parser.add_argument("--json-output", type=Path, default=Path("pilot/analysis/metrics_results.json"))
    parser.add_argument("--markdown-output", type=Path, default=Path("pilot/analysis/metrics_summary.md"))
    args = parser.parse_args()
    if not args.results and not args.sweqa_executions:
        parser.error("provide result files or --sweqa-executions")
    try:
        check_output_path(args.json_output)
        check_output_path(args.markdown_output)
        rows = read_results(args.results)
        payload = analyze(rows, read_sidecars(args.diagnostics, "diagnostics"))
        if args.energy:
            from harnessspec.energy import summarize_energy
            energy = read_sidecars(args.energy, "energy")
            for benchmark, analysis in payload["benchmarks"].items():
                analysis["energy"] = summarize_energy(rows, energy, benchmark)
        if args.sweqa_executions:
            payload["sweqa_execution_only"] = execution_handoffs(args.sweqa_executions, rows)
        write_json(args.json_output, payload)
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(markdown(payload), encoding="utf-8")
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
