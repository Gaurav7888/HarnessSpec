import tempfile
import unittest
from pathlib import Path

from harnessspec.results import KEY_FIELDS, read_results, result_key, write_json
from pilot.metrics import analyze, amortization, break_even, execution_handoffs, paired_bootstrap, summarize
from test_results import row


class MetricsTests(unittest.TestCase):
    def test_denominators_include_failures(self):
        first = row(resolved=True, design_tokens=5, subagent_tokens=15)
        second = row(task_id="second", subagent_tokens=40, silent_handoff=True, rounds=2,
                     budget_violations=1, tool_denials=4, hook_failures=2, wall_clock_s=2.5)
        diagnostics = {result_key(second): {"return_accepted": True},
                       result_key(first): {"return_accepted": False}}
        summary = summarize([first, second], diagnostics)
        expected = {
            "attempted": 2, "resolved": 1, "accuracy": 0.5, "total_tokens": 60, "mean_tokens": 30,
            "tokens_per_correct": 60, "silent_handoff_rate": 0.5, "accepted_returns": 1,
            "silent_given_accepted": 1, "budget_violations": 1, "tool_denials": 4,
            "hook_failures": 2, "mean_rounds": 1, "mean_wall_clock_s": 1.5,
        }
        self.assertEqual(expected, {field: summary[field] for field in expected})
        self.assertIsNone(summarize([first, second], {})["accepted_returns"])

    def test_undefined_denominators_and_B(self):
        self.assertIsNone(summarize([], {})["accuracy"])
        self.assertIsNone(summarize([row()], {})["tokens_per_correct"])
        self.assertIsNone(summarize([row(designer="B", first_pass_valid=False)], {})["first_pass_validity"])
        self.assertIsNone(summarize([row()], {result_key(row()): {"return_accepted": False}})
                          ["silent_given_accepted"])

    def test_duplicate_files_and_direct_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            first, second = (Path(folder) / name for name in ("first.json", "second.json"))
            write_json(first, [row()])
            write_json(second, [row()])
            with self.assertRaisesRegex(ValueError, "duplicate run"):
                read_results([first, second])
        with self.assertRaisesRegex(ValueError, "duplicate run"):
            analyze([row(), row()])

    def test_bootstrap_keeps_same_task_seeds_together(self):
        left = [row(task_id="x", designer="D", seed=i, resolved=True) for i in (1, 2, 3)]
        left += [row(task_id="y", designer="D"), row(task_id="unmatched_D", designer="D")]
        right = [row(task_id="x", seed=i) for i in (1, 2, 3)]
        right += [row(task_id="y"), row(task_id="unmatched_A"), row(task_id="y", seed=2)]
        def score(record):
            return record["resolved"] * 100
        result = paired_bootstrap(left, right, score, 1000, 17)
        self.assertEqual(result, paired_bootstrap(left[::-1], right[::-1], score, 1000, 17))
        self.assertEqual(result["difference"], 50)
        self.assertEqual(result["ci95"], [0, 100])
        self.assertEqual(result["matched_tasks"], 2)
        self.assertEqual(result["matched_observations"], 4)
        self.assertEqual(result["matched_seeds"], [1, 2, 3])
        self.assertEqual([result["excluded_left"], result["excluded_right"]], [1, 2])
        limited = paired_bootstrap(left[:1], right[:1], score)
        self.assertEqual(limited["matched_tasks"], 1)
        self.assertIsNone(limited["ci95"])

    def test_benchmarks_separate_and_h2_comparisons(self):
        rows = [row(designer=d, silent_handoff=d == "B") for d in "ABCD"]
        rows.append(row(benchmark="swebench"))
        analysis = analyze(rows)["benchmarks"]
        self.assertEqual(analysis["swebench"]["designers"]["A"]["attempted"], 1)
        sweqa = analysis["sweqa"]
        self.assertEqual(sweqa["comparisons"]["D_vs_B"]["silent_handoff_pp"]["difference"], -100)
        self.assertEqual(sweqa["comparisons"]["D_vs_C"]["silent_handoff_pp"]["difference"], 0)
        self.assertEqual(sweqa["h2_pending"], [])
        self.assertFalse(sweqa["three_seed_requirement_met"])
        with self.assertRaisesRegex(ValueError, "rejected"):
            analyze(rows, {result_key(rows[1]): {"return_accepted": False}})

    def test_break_even_boundaries_and_unavailable_costs(self):
        for cost, savings, status, tasks in [
            (21, 10, "estimated", 3), (20, 10, "estimated", 2),
            (1, 10, "estimated", 1), (20, 0, "no_finite_break_even", None),
            (20, -1, "no_finite_break_even", None), (0, 10, "undefined", None),
            (None, 10, "undefined", None), (20, None, "undefined", None),
        ]:
            with self.subTest(cost=cost, savings=savings):
                self.assertEqual(break_even(cost, savings), {"status": status, "break_even_tasks": tasks})

    def test_execution_only_handoff_analysis_keeps_ungraded_attempts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, accepted in (("A", True), ("D", False)):
                attempt = row(designer=name, resolved=None if accepted else False, silent_handoff=accepted)
                write_json(root / f"{name}.json", {
                    **{field: attempt[field] for field in KEY_FIELDS}, "row": attempt,
                    "diagnostics": {"return_accepted": accepted},
                })
            report = execution_handoffs([root])
            grade = row(designer="A", resolved=False, silent_handoff=True)
            imported = execution_handoffs([root], [grade])
            self.assertEqual(imported["designers"]["A"]["requires_external_grade"], 0)
            with self.assertRaisesRegex(ValueError, "conflicts with trace"):
                execution_handoffs([root], [{**grade, "subagent_tokens": grade["subagent_tokens"] + 1}])
        self.assertEqual(report["designers"]["A"]["requires_external_grade"], 1)
        self.assertEqual(report["designers"]["A"]["acceptance_rate"], 1)
        self.assertEqual(report["designers"]["D"]["acceptance_rate"], 0)
        self.assertIsNone(report["designers"]["D"]["silent_given_accepted"])
        self.assertEqual(report["attempt_cost_scenario"]["status"], "undefined")
        self.assertNotIn("accuracy", report["designers"]["A"])
        self.assertEqual(report["silent_handoff_difference_pp"]["D_vs_A"]["difference"], -100)

    def test_amortization_excludes_priming_and_aborted_runs(self):
        a = [row(task_id=task, subagent_tokens=30, resolved=True) for task in ("first", "second", "third")]
        d = [row(task_id=task, designer="D", design_tokens=21, subagent_tokens=20,
                 resolved=task != "third") for task in ("first", "second", "third")]
        self.assertEqual(amortization(a, d, {})["scenarios"], [])
        diagnostics = {result_key(item): {"reuse_group": "repo@commit/how", "design_tokens_measured": True,
                                          "design_valid": True} for item in d}
        result = amortization(a, d, diagnostics)
        self.assertFalse(result["reuse_observed"])
        self.assertEqual(result["scenarios"][0]["matched_savings_tasks"], 1)
        self.assertEqual(result["scenarios"][0]["break_even_tasks"], 3)

    def test_execution_metrics_refuse_different_treatments(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for index, protocol in enumerate(("sweqa-ad-v1", "sweqa-ad-v2")):
                attempt = row(task_id=str(index), benchmark="sweqa")
                write_json(root / f"{index}.json", {
                    **{field: attempt[field] for field in KEY_FIELDS}, "row": attempt,
                    "protocol": protocol, "diagnostics": {"return_accepted": False},
                })
            with self.assertRaisesRegex(ValueError, "different experiment protocols"):
                execution_handoffs([root])

    def test_token_only_cost_with_no_successful_pair(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, cost in (("A", 6), ("D", 31)):
                attempt = row(designer=name, design_tokens=8 if name == "D" else 0,
                              subagent_tokens=cost, resolved=None if name == "A" else False)
                write_json(root / f"{name}.json", {
                    **{field: attempt[field] for field in KEY_FIELDS}, "row": attempt,
                    "diagnostics": {"return_accepted": name == "A", "design_valid": True,
                                    "design_tokens_measured": name == "D"},
                })
            scenario = execution_handoffs([root])["attempt_cost_scenario"]
            self.assertEqual(scenario["subagent_tokens_saved_A_minus_D"]["difference"], -25)
            self.assertEqual(scenario["status"], "no_finite_break_even")
            self.assertFalse(scenario["reuse_observed"])
