"""executable_spec: every designer's design() result becomes a runnable spec or a reason."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from harnessspec.execution import NotExecutable, executable_spec
from harnessspec.llm import Reply, load_pin
from harnessspec.orchestrator import design, fixture_task
from harnessspec.parent import reference_parent
from harnessspec.runtime import Session
from harnessspec.subagent import run_subagent
from harnessspec.validator import validate

ROOT = Path(__file__).resolve().parents[1]
PINNED = load_pin()["name"]


class Scripted:
    def __init__(self, *replies):
        self.replies = [r if isinstance(r, str) else json.dumps(r) for r in replies]

    def chat(self, messages, seed, json_mode=False):
        return Reply(self.replies.pop(0), 50, 10, 0.0)


def tuple_reply(**overrides):
    reply = {"instruction": "Fix add in src/app.py.", "context": ["src", "tests"],
             "tools": ["read_file", "write_file"], "model": PINNED}
    reply.update(overrides)
    return reply


class ExecutableSpecTests(unittest.TestCase):
    def setUp(self):
        self.card = reference_parent()
        self.task = fixture_task()
        self.baseline = executable_spec(design(self.task, self.card, "A", 1), self.task, self.card)

    def c_spec(self, **overrides):
        result = design(self.task, self.card, "C", 1, client=Scripted(tuple_reply(**overrides)))
        return executable_spec(result, self.task, self.card)

    def test_a_runs_its_own_spec(self):
        self.assertEqual(validate(self.baseline, self.card), [])

    def test_b_is_a_harness_with_the_brief_as_goal(self):
        result = design(self.task, self.card, "B", 1, client=Scripted("Change add to return a + b."))
        spec = executable_spec(result, self.task, self.card)
        self.assertEqual(spec["goal"]["statement"], "Change add to return a + b.")
        for field in ("tools", "budgets", "stop", "verification", "return_contract", "context", "model"):
            self.assertEqual(spec[field], self.baseline[field], field)

    def test_b_with_an_empty_brief_is_not_run(self):
        result = design(self.task, self.card, "B", 1, client=Scripted("   "))
        with self.assertRaises(NotExecutable) as caught:
            executable_spec(result, self.task, self.card)
        self.assertEqual(caught.exception.reason, "brief.empty")

    def test_c_takes_permissions_from_the_card_and_narrows_paths(self):
        spec = self.c_spec()
        tools = {tool["name"]: tool for tool in spec["tools"]}
        self.assertEqual(tools["write_file"]["permission"], "write")
        self.assertEqual(tools["write_file"]["paths"], ["src"])
        self.assertEqual(tools["read_file"]["paths"], ["src", "tests"])
        self.assertEqual(spec["context"]["include"], ["src", "tests"])
        self.assertEqual(spec["goal"]["statement"], "Fix add in src/app.py.")
        for field in ("budgets", "stop", "verification", "return_contract"):
            self.assertEqual(spec[field], self.baseline[field], field)

    def test_c_h3_score_is_unchanged(self):
        result = design(self.task, self.card, "C", 1, client=Scripted(tuple_reply()))
        self.assertFalse(result["first_pass_valid"])
        self.assertEqual(result["spec"]["tools"][1]["permission"], "read")

    def test_c_rejections(self):
        cases = [
            ({"tools": ["browser"]}, "tuple.tool"),
            ({"tools": []}, "tuple.tools"),
            ({"tools": ["read_file", "read_file"]}, "tuple.tools"),
            ({"context": ["../secrets"]}, "tuple.context"),
            ({"context": []}, "tuple.context"),
            ({"context": "src"}, "tuple.context"),
            ({"context": ["tests"], "tools": ["write_file"]}, "tuple.tool"),
            ({"model": "llama3:8b"}, "tuple.model"),
            ({"instruction": ""}, "tuple.instruction"),
        ]
        for overrides, reason in cases:
            with self.subTest(overrides=overrides):
                with self.assertRaises(NotExecutable) as caught:
                    self.c_spec(**overrides)
                self.assertEqual(caught.exception.reason, reason)

    def test_c_unparsed_reply_is_not_run(self):
        result = design(self.task, self.card, "C", 1, client=Scripted("not json"))
        with self.assertRaises(NotExecutable) as caught:
            executable_spec(result, self.task, self.card)
        self.assertEqual(caught.exception.reason, "tuple.unparsed")

    def test_invalid_d_is_not_run(self):
        draft = json.loads((ROOT / "examples" / "valid_spec.json").read_text())
        draft["goal"]["acceptance_tests"] = []
        result = design(self.task, self.card, "D", 1, client=Scripted(draft, draft))
        with self.assertRaises(NotExecutable) as caught:
            executable_spec(result, self.task, self.card)
        self.assertEqual(caught.exception.reason, "design.invalid")

    def test_b_and_c_specs_run_end_to_end_on_the_fixture(self):
        fixed = "def add(a, b):\n    return a + b\n"
        steps = [
            {"kind": "tool", "tool": "write_file", "permission": "write", "path": "src/app.py",
             "content": fixed},
            {"kind": "return", "summary": "add returns a + b.",
             "citations": [{"file": "src/app.py", "line": 2}], "test_output": "ok"},
        ]
        brief = design(self.task, self.card, "B", 1, client=Scripted("Fix add."))
        tup = design(self.task, self.card, "C", 1, client=Scripted(tuple_reply()))
        for result in (brief, tup):
            spec = executable_spec(result, self.task, self.card)
            held = tempfile.TemporaryDirectory()
            try:
                shutil.copytree(ROOT / "fixtures" / "off_by_one", Path(held.name), dirs_exist_ok=True)
                Session(spec, self.card, Path(held.name))
                outcome = run_subagent(spec, self.card, Path(held.name), 1, Scripted(*steps))
            finally:
                held.cleanup()
            with self.subTest(designer=result["designer"]):
                self.assertTrue(outcome["resolved"])
                self.assertEqual(outcome["trace"].tool_denials, 0)


if __name__ == "__main__":
    unittest.main()
