"""Single-step runtime, the pytest command, and the subagent loop with a scripted model."""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from harnessspec.designers import fixed_generic_harness, harness_d
from harnessspec.hooks import run_hook
from harnessspec.llm import Reply
from harnessspec.parent import ALLOWED_COMMANDS, reference_parent
from harnessspec.pilot import FIXED_APP, WORKSPACE
from harnessspec.return_gate import AgentResult
from harnessspec.runtime import Action, Session, citation, run_trace
from harnessspec.subagent import action_from_reply, result_row, run_subagent
from harnessspec.validator import validate


class ScriptedModel:
    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.calls = []

    def chat(self, messages, seed, json_mode=False):
        self.calls.append({"messages": messages, "seed": seed, "json_mode": json_mode})
        content = self.replies.pop(0)
        return Reply(content, prompt_tokens=11, output_tokens=4, seconds=0.2)


def _copy() -> tempfile.TemporaryDirectory:
    directory = tempfile.TemporaryDirectory(prefix="harnessspec-step-")
    shutil.copytree(WORKSPACE, Path(directory.name), dirs_exist_ok=True)
    return directory


class StepTests(unittest.TestCase):
    def test_step_matches_run_trace_on_the_patched_fix(self):
        parent = reference_parent()
        spec = harness_d("runtime", "Make add return the sum of its arguments.")
        actions = [
            Action("tool", 50, 0.2, "write_file", "write", "src/app.py", FIXED_APP),
            Action(
                "return",
                20,
                0.1,
                result=AgentResult(
                    "add now returns the sum.",
                    [citation("src/app.py", 2)],
                    "ok",
                    ["add returns the sum"],
                ),
            ),
        ]
        held = _copy()
        try:
            workspace = Path(held.name)
            trace = run_trace(spec, parent, actions, workspace)
            self.assertTrue(trace.return_accepted)
            self.assertFalse(trace.silent_handoff)
            self.assertEqual((workspace / "src" / "app.py").read_text(encoding="utf-8"), FIXED_APP)
            self.assertEqual(trace.steps_used, 2)
        finally:
            held.cleanup()

    def test_read_observation_returns_the_file(self):
        parent = reference_parent()
        spec = harness_d("runtime", "Make add return the sum of its arguments.")
        held = _copy()
        try:
            session = Session(spec, parent, Path(held.name))
            observation = session.step(
                Action("tool", 10, 0.1, "read_file", "read", "src/app.py")
            )
        finally:
            held.cleanup()
        self.assertTrue(observation.applied)
        self.assertIn("a + b + 1", observation.output)
        self.assertEqual(observation.remaining_steps, spec["budgets"]["max_steps"] - 1)

    def test_a_third_step_is_a_budget_stop_and_further_steps_do_not_apply(self):
        parent = reference_parent()
        spec = harness_d("runtime", "Make add return the sum of its arguments.", max_steps=2)
        write = Action("tool", 10, 0.1, "write_file", "write", "src/app.py", FIXED_APP)
        held = _copy()
        try:
            session = Session(spec, parent, Path(held.name))
            session.step(write)
            session.step(write)
            third = session.step(write)
            fourth = session.step(write)
        finally:
            held.cleanup()
        self.assertEqual(third.code, "budget.exhausted")
        self.assertEqual(session.trace.budget_violations, 1)
        self.assertEqual(session.trace.steps_used, 2)
        self.assertEqual(fourth.code, "session.stopped")
        self.assertEqual(session.trace.steps_used, 2)

    def test_pytest_is_allowlisted_and_runs_as_a_module(self):
        self.assertEqual(ALLOWED_COMMANDS["pytest"], "test")
        spec = harness_d("t", "Fix it.")
        spec["goal"]["acceptance_tests"] = [{"id": "suite", "command": "pytest"}]
        spec["verification"]["hooks"] = [{"kind": "test", "command": "pytest"}]
        self.assertEqual(validate(spec, reference_parent()), [])

        captured = {}

        def fake_run(argv, **kwargs):
            captured["argv"] = argv
            captured["shell"] = kwargs.get("shell")

            class Completed:
                returncode = 0
                stdout = "1 passed"
                stderr = ""

            return Completed()

        with mock.patch("harnessspec.hooks.subprocess.run", fake_run):
            outcome = run_hook({"kind": "test", "command": "pytest"}, Path("."), ["src"], 5)
        self.assertTrue(outcome.passed)
        self.assertFalse(captured["shell"])
        self.assertEqual(captured["argv"][1:3], ["-m", "pytest"])


class SubagentLoopTests(unittest.TestCase):
    def test_scripted_model_patches_the_fixture_under_d(self):
        parent = reference_parent()
        statement = "Make add return the sum of its arguments."
        spec = harness_d("off_by_one", statement)
        read = '{"kind":"tool","tool":"read_file","permission":"read","path":"src/app.py"}'
        write = (
            '{"kind":"tool","tool":"write_file","permission":"write","path":"src/app.py",'
            '"content":"def add(a, b):\\n    return a + b\\n"}'
        )
        done = (
            '{"kind":"return","summary":"add returns the sum.",'
            '"citations":[{"file":"src/app.py","line":2}],"test_output":"ok","claims":["fixed"]}'
        )
        model = ScriptedModel(read, write, done)
        pin = {"name": "scripted", "digest": "sha256:" + "ab" * 32}
        held = _copy()
        try:
            outcome = run_subagent(spec, parent, Path(held.name), 1, model)
        finally:
            held.cleanup()
        self.assertTrue(outcome["resolved"])
        self.assertTrue(outcome["trace"].return_accepted)
        self.assertFalse(outcome["trace"].silent_handoff)
        self.assertEqual(outcome["subagent_tokens"], 45)
        self.assertTrue(model.calls[0]["json_mode"])
        self.assertIn("a + b + 1", outcome["log"][0]["observation"]["output"])
        row = result_row(spec, "D", 1, pin, "harness_d", outcome)
        self.assertEqual(row["design_tokens"], 0)
        self.assertEqual(row["spec_source"], "harness_d")
        self.assertEqual(row["hook_failures"], 0)

    def test_designer_a_accepts_a_summary_with_no_citation(self):
        parent = reference_parent()
        statement = "Make add return the sum of its arguments."
        spec = fixed_generic_harness("off_by_one", parent, statement)
        done = '{"kind":"return","summary":"The bug is fixed.","citations":[],"claims":["fixed"]}'
        model = ScriptedModel(done)
        held = _copy()
        try:
            outcome = run_subagent(spec, parent, Path(held.name), 1, model)
        finally:
            held.cleanup()
        self.assertTrue(outcome["trace"].return_accepted)
        self.assertTrue(outcome["trace"].silent_handoff)
        self.assertFalse(outcome["resolved"])

    def test_unparsed_reply_is_refused_and_counts_as_a_step(self):
        action = action_from_reply("I will fix it now.", tokens=7, seconds=0.1)
        self.assertEqual(action.kind, "unparsed")
        self.assertEqual(action.tokens, 7)
