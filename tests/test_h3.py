"""The committed H3 file must agree with its own rows. No model is called."""

import json
import unittest
from pathlib import Path

from harnessspec.h3 import summarize
from harnessspec.llm import load_pin

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "pilot" / "h3_results.json"
RESULTS_V2 = ROOT / "pilot" / "h3_results_v2.json"


@unittest.skipUnless(RESULTS.exists(), "pilot/h3_results.json not generated yet")
class H3ResultsTests(unittest.TestCase):
    path = RESULTS

    def setUp(self):
        self.payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.rows = self.payload["rows"]

    def test_summary_is_recomputed_from_rows(self):
        self.assertEqual(summarize(self.rows), self.payload["summary"])

    def test_every_row_uses_the_pinned_model(self):
        pin = load_pin()
        for row in self.rows:
            self.assertEqual(row["model"], pin["name"])
            self.assertEqual(row["model_digest"], pin["digest"])

    def test_one_row_per_corpus_spec(self):
        corpus = [row["spec_id"] for row in self.rows if row["source"] == "corpus"]
        self.assertEqual(len(corpus), 15)
        self.assertEqual(len(set(corpus)), 15)

    def test_designer_invariants(self):
        for row in self.rows:
            if row["designer"] == "A":
                self.assertEqual(row["design_tokens"], 0)
            if row["designer"] == "B":
                self.assertIsNone(row["first_pass_valid"])
            if row["designer"] == "C":
                self.assertEqual(row["rounds"], 0)
            self.assertLessEqual(row["rounds"], 3)


@unittest.skipUnless(RESULTS_V2.exists(), "pilot/h3_results_v2.json not generated yet")
class H3ResultsV2Tests(H3ResultsTests):
    path = RESULTS_V2

    def test_v2_records_the_allowlist_it_ran_with(self):
        from harnessspec.parent import ALLOWED_COMMANDS

        self.assertEqual(self.payload["allowed_commands"], sorted(ALLOWED_COMMANDS))


if __name__ == "__main__":
    unittest.main()
