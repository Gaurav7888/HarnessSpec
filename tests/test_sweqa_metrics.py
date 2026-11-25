"""Evidence denominators are independent of historical format scores and grading."""
from copy import deepcopy
import unittest

from pilot.sweqa_metrics import analyze_attempts, conditional_difference
from test_results import row


class SourceVerifiedTests(unittest.TestCase):
    def test_retrospective_keeps_historical_gate_rows_intact(self):
        runs = [row(designer="A", resolved=None, silent_handoff=False, accepted=True,
                    gradable=True, verified_silent=True, format_silent=False, usable=0, grounded=False),
                row(designer="D", resolved=False, silent_handoff=False, accepted=False,
                    gradable=False, verified_silent=False, format_silent=False, usable=0, grounded=False)]
        original = deepcopy(runs)
        report = analyze_attempts(runs, {})
        self.assertEqual(runs, original)
        a, d = (report["designers"][k] for k in "AD")
        self.assertEqual((a["format_silent"], a["verified_silent"], a["pending_grades"]), (0, 1, 1))
        self.assertIsNone(a["accuracy_all_attempts"])
        self.assertIsNone(a["tokens_per_correct"])
        self.assertEqual(d["silent_per_attempt"], 0)
        self.assertIsNone(d["silent_per_accepted"])
        self.assertIsNone(d["verified_citation_coverage_per_accepted"])
        self.assertEqual(report["h2"], {})
        self.assertEqual(report["h4"]["quality_adjusted_status"], "undefined")

    def test_conditional_interval_groups_seeds_and_handles_zero_acceptance(self):
        left = [row(task_id=task, seed=seed, accepted=True, verified_silent=task == "x")
                for task, seeds in [("x", [1, 2, 3]), ("y", [1])] for seed in seeds]
        right = [{**r, "designer": "B", "verified_silent": False} for r in left]
        result = conditional_difference(left, right)
        self.assertEqual(result["difference_pp"], 50)
        self.assertEqual(result["ci95_given_defined"], [0, 100])
        self.assertIsNone(conditional_difference(left, [{**r, "accepted": False} for r in right])["difference_pp"])
