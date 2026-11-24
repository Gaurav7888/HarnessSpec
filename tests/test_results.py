"""Synthetic test records for the shared benchmark contract."""
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from harnessspec.results import read_results, validate_result


def row(**overrides):
    return {
        "task_id": "synthetic", "benchmark": "sweqa", "designer": "A", "seed": 1,
        "model": "mock", "model_digest": "synthetic", "design_tokens": 0,
        "subagent_tokens": 10, "rounds": 0, "first_pass_valid": True,
        "resolved": False, "silent_handoff": False, "budget_violations": 0,
        "tool_denials": 0, "hook_failures": 0, "wall_clock_s": 0.5, **overrides,
    }


class ResultTests(unittest.TestCase):
    def test_valid(self):
        validate_result(row(rounds=3, benchmark="swebench", seed=-1))

    def test_missing_and_extra(self):
        missing = row()
        del missing["task_id"]
        for record in (missing, row(extra=True), []):
            with self.subTest(record=record), self.assertRaises(ValueError):
                validate_result(record)

    def test_duplicate_json_fields_are_rejected(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text('[{"designer":"A","designer":"D"}]', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate JSON field designer"):
                read_results([path])

    def test_invalid_types_ranges_and_enums(self):
        for field, value in (
            ("designer", "E"), ("benchmark", "fixture"), ("task_id", ""),
            ("seed", True), ("rounds", -1), ("rounds", 4), ("rounds", 1.0),
            ("first_pass_valid", 0), ("design_tokens", -1), ("subagent_tokens", "1"),
            ("wall_clock_s", True), ("wall_clock_s", -0.1), ("hook_failures", -1),
            ("wall_clock_s", math.nan), ("wall_clock_s", math.inf),
            ("wall_clock_s", -math.inf),
        ):
            with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, field):
                validate_result(row(**{field: value}))
