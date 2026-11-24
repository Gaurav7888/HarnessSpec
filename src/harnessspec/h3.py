"""H3: does validation with typed feedback raise first-pass validity?

Two row sources, both written to ``pilot/h3_results.json``:

- ``fixture``: ``design()`` for A, B, C, and D on ``fixtures/off_by_one``,
  once per seed. H3 compares C against D on these rows.
- ``corpus``: each of the 15 hand-written specs in ``pilot.corpus()`` is used
  as the first draft, and D's repair loop (compiler clamp, then typed errors
  back to the pinned model) runs on it. ``compiler_only_valid`` is what
  ``repair.py`` alone reaches on the same draft, as in ``pilot/results.json``.

H3 fails if first-pass validity does not rise from C to D.
"""

from __future__ import annotations

import time

from harnessspec.llm import load_pin
from harnessspec.orchestrator import (
    DESIGNERS,
    _codes,
    design,
    fixture_task,
    missing_acceptance_test,
    repair_with_model,
)
from harnessspec.parent import reference_parent
from harnessspec.pilot import corpus
from harnessspec.repair import repair_until_valid
from harnessspec.validator import validate

SEEDS = (1, 2, 3)


def _row(source: str, spec_id: str, result: dict) -> dict:
    return {
        "source": source,
        "spec_id": spec_id,
        "designer": result["designer"],
        "seed": result["seed"],
        "model": result["model"],
        "model_digest": result["model_digest"],
        "first_pass_valid": result["first_pass_valid"],
        "first_pass_errors": result["first_pass_errors"],
        "rounds": result["rounds"],
        "model_calls": sum(1 for entry in result["log"] if entry["kind"] != "compiler"),
        "valid": result["valid"],
        "remaining_errors": _codes(result["remaining_errors"]),
        "missing_acceptance_test": result["missing_acceptance_test"],
        "design_tokens": result["design_tokens"],
        "wall_clock_s": result["wall_clock_s"],
    }


def fixture_rows(client, seeds=SEEDS, designers=DESIGNERS):
    rows, transcripts = [], []
    task, card = fixture_task(), reference_parent()
    for seed in seeds:
        for designer in designers:
            result = design(task, card, designer, seed, client=client)
            rows.append(_row("fixture", "off_by_one", result))
            transcripts.append({"spec_id": "off_by_one", "designer": designer, "seed": seed,
                                "spec": result["spec"], "log": result["log"]})
    return rows, transcripts


def corpus_rows(client, seed: int = 1):
    pin = load_pin()
    card = reference_parent()
    statement = fixture_task()["statement"]
    rows, transcripts = [], []
    for name, draft in corpus():
        task_id = draft.get("task_id") if isinstance(draft.get("task_id"), str) else name
        task = {"task_id": task_id, "statement": statement}
        started = time.monotonic()
        first_errors = validate(draft, card)
        log: list[dict] = []
        spec, remaining, rounds = repair_with_model(
            draft, task, card, seed, client, pin["name"], log, first_errors=first_errors)
        result = {
            "designer": "D",
            "seed": seed,
            "model": pin["name"],
            "model_digest": pin["digest"],
            "first_pass_valid": not first_errors,
            "first_pass_errors": _codes(first_errors),
            "rounds": rounds,
            "valid": not remaining,
            "remaining_errors": [error.as_dict() for error in remaining],
            "missing_acceptance_test": missing_acceptance_test(remaining),
            "design_tokens": sum(e.get("prompt_tokens", 0) + e.get("output_tokens", 0) for e in log),
            "wall_clock_s": round(time.monotonic() - started, 3),
            "log": log,
        }
        row = _row("corpus", name, result)
        row["compiler_only_valid"] = repair_until_valid(draft, card).valid
        rows.append(row)
        transcripts.append({"spec_id": name, "designer": "D", "seed": seed, "spec": spec, "log": log})
    return rows, transcripts


def _rate(values) -> float | None:
    values = [bool(value) for value in values]
    return round(sum(values) / len(values), 4) if values else None


def summarize(rows: list[dict]) -> dict:
    fixture = [row for row in rows if row["source"] == "fixture"]
    per_designer = {}
    for designer in DESIGNERS:
        mine = [row for row in fixture if row["designer"] == designer]
        if not mine:
            continue
        scored = [row for row in mine if row["first_pass_valid"] is not None]
        per_designer[designer] = {
            "n": len(mine),
            "first_pass_valid_rate": _rate(row["first_pass_valid"] for row in scored) if scored else None,
            "valid_rate": _rate(row["valid"] for row in scored) if scored else None,
            "mean_rounds": round(sum(row["rounds"] for row in mine) / len(mine), 3),
            "mean_design_tokens": round(sum(row["design_tokens"] for row in mine) / len(mine), 1),
        }
    corpus_part = [row for row in rows if row["source"] == "corpus"]
    rounds_histogram = {}
    for row in corpus_part:
        if row["valid"]:
            key = str(row["rounds"])
            rounds_histogram[key] = rounds_histogram.get(key, 0) + 1
    c = per_designer.get("C", {}).get("first_pass_valid_rate")
    d = per_designer.get("D", {}).get("first_pass_valid_rate")
    failures = [
        {"source": row["source"], "spec_id": row["spec_id"], "designer": row["designer"],
         "seed": row["seed"], "remaining_errors": row["remaining_errors"],
         "missing_acceptance_test": row["missing_acceptance_test"]}
        for row in rows
        if row["designer"] == "D" and row["valid"] is False
    ]
    return {
        "fixture": per_designer,
        "corpus": {
            "n": len(corpus_part),
            "first_pass_valid": sum(1 for row in corpus_part if row["first_pass_valid"]),
            "valid_after_model_repair": sum(1 for row in corpus_part if row["valid"]),
            "valid_after_compiler_only": sum(1 for row in corpus_part if row.get("compiler_only_valid")),
            "still_invalid": sum(1 for row in corpus_part if not row["valid"]),
            "rounds_to_valid": dict(sorted(rounds_histogram.items())),
            "design_tokens": sum(row["design_tokens"] for row in corpus_part),
        },
        "h3": {
            "c_first_pass_valid_rate": c,
            "d_first_pass_valid_rate": d,
            "d_valid_after_repair_rate": per_designer.get("D", {}).get("valid_rate"),
            "first_pass_rises_c_to_d": None if c is None or d is None else d > c,
            "note": "C has no acceptance test, budgets, stop rule, verification, or return contract"
                    " by construction, so its first-pass validity is 0 unless the validator changes.",
        },
        "orchestrator_failures": failures,
    }
