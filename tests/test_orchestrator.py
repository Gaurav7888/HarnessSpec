"""design() against a scripted model. No network, so the suite stays offline."""

import json
import unittest
from copy import deepcopy
from pathlib import Path

from harnessspec.llm import Reply, load_pin
from harnessspec.orchestrator import (
    PARSE_ERROR,
    design,
    fixture_task,
    parse_object,
    spec_messages,
)
from harnessspec.parent import reference_parent
from harnessspec.validator import validate

ROOT = Path(__file__).resolve().parents[1]
VALID = json.loads((ROOT / "examples" / "valid_spec.json").read_text(encoding="utf-8"))
# sha256 prefix of SYSTEM_D as used for pilot/h3_results_v2.json (commit 8cbb81d).
HASH_SYSTEM_D = "644a1aed6d9e2076"


class ScriptedModel:
    """Returns the queued replies in order and records every call."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, messages, seed, json_mode=False):
        self.calls.append({"messages": messages, "seed": seed, "json_mode": json_mode})
        content = self.replies.pop(0)
        if not isinstance(content, str):
            content = json.dumps(content)
        return Reply(content=content, prompt_tokens=100, output_tokens=10, seconds=0.0)


def valid_spec():
    spec = deepcopy(VALID)
    spec["task_id"] = "off_by_one"
    spec["model"]["name"] = load_pin()["name"]
    return spec


class DesignTests(unittest.TestCase):
    def setUp(self):
        self.card = reference_parent()
        self.task = fixture_task()

    def test_a_makes_no_model_call(self):
        result = design(self.task, self.card, "A", seed=1, client=None)
        self.assertEqual(result["design_tokens"], 0)
        self.assertEqual(result["rounds"], 0)
        self.assertTrue(result["first_pass_valid"])
        self.assertEqual(result["spec"]["model"]["name"], load_pin()["name"])

    def test_b_is_stored_not_validated(self):
        model = ScriptedModel("Fix add in src/app.py and run the tests.")
        result = design(self.task, self.card, "B", seed=1, client=model)
        self.assertEqual(result["spec"]["kind"], "free_text")
        self.assertFalse(result["spec"]["compiled"])
        self.assertIsNone(result["first_pass_valid"])
        self.assertEqual(result["design_tokens"], 110)
        self.assertFalse(model.calls[0]["json_mode"])

    def test_c_is_scored_before_repair(self):
        model = ScriptedModel({
            "instruction": "Fix add.", "context": ["src"], "tools": ["read_file"],
            "model": "qwen2.5-coder:7b",
        })
        result = design(self.task, self.card, "C", seed=1, client=model)
        self.assertFalse(result["first_pass_valid"])
        self.assertEqual(result["rounds"], 0)
        self.assertEqual(len(model.calls), 1)
        self.assertTrue(result["missing_acceptance_test"])
        self.assertNotIn("budgets", result["spec"])

    def test_c_keeps_ill_typed_fields_as_emitted(self):
        model = ScriptedModel({"instruction": "Fix add.", "context": "src", "tools": "read_file",
                               "model": "m"})
        result = design(self.task, self.card, "C", seed=1, client=model)
        self.assertEqual(result["spec"]["context"]["include"], "src")
        self.assertFalse(result["valid"])

    def test_d_valid_first_reply_uses_no_rounds(self):
        model = ScriptedModel(valid_spec())
        result = design(self.task, self.card, "D", seed=7, client=model)
        self.assertTrue(result["first_pass_valid"])
        self.assertTrue(result["valid"])
        self.assertEqual(result["rounds"], 0)
        self.assertEqual(result["design_tokens"], 110)
        self.assertEqual(model.calls[0]["seed"], 7)
        self.assertTrue(model.calls[0]["json_mode"])

    def test_d_compiler_clamp_needs_no_model_call(self):
        spec = valid_spec()
        spec["budgets"]["max_steps"] = 500
        model = ScriptedModel(spec)
        result = design(self.task, self.card, "D", seed=1, client=model)
        self.assertFalse(result["first_pass_valid"])
        self.assertTrue(result["valid"])
        self.assertEqual(result["rounds"], 1)
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(result["spec"]["budgets"]["max_steps"], 30)

    def test_d_sends_typed_errors_back_for_what_the_compiler_cannot_write(self):
        draft = valid_spec()
        draft["goal"]["acceptance_tests"] = []
        model = ScriptedModel(draft, valid_spec())
        result = design(self.task, self.card, "D", seed=1, client=model)
        self.assertEqual(result["rounds"], 1)
        self.assertTrue(result["valid"])
        self.assertEqual(result["design_tokens"], 220)
        repair_prompt = model.calls[1]["messages"][-1]["content"]
        self.assertIn("goal.acceptance_tests", repair_prompt)
        self.assertEqual(result["log"][1]["sent_to_model"], ["goal.acceptance_tests"])

    def test_d_stops_after_three_rounds(self):
        drafts = []
        for statement in ("one", "two", "three", "four"):
            draft = valid_spec()
            draft["goal"] = {"statement": statement, "acceptance_tests": []}
            drafts.append(draft)
        model = ScriptedModel(*drafts, valid_spec())
        result = design(self.task, self.card, "D", seed=1, client=model)
        self.assertEqual(result["rounds"], 3)
        self.assertEqual(len(model.calls), 4)
        self.assertFalse(result["valid"])
        self.assertTrue(result["missing_acceptance_test"])
        self.assertIn("goal.acceptance_tests", [e["code"] for e in result["remaining_errors"]])

    def test_d_stops_early_when_the_model_repeats_itself(self):
        draft = valid_spec()
        draft["goal"]["acceptance_tests"] = []
        model = ScriptedModel(draft, draft, valid_spec())
        result = design(self.task, self.card, "D", seed=1, client=model)
        self.assertEqual(result["rounds"], 1)
        self.assertEqual(len(model.calls), 2)
        self.assertEqual(result["log"][-1]["stopped"], "unchanged")

    def test_repair_prompt_names_the_allowed_commands(self):
        draft = valid_spec()
        # A name the compiler cannot reduce, so the hint has to reach the model.
        draft["goal"]["acceptance_tests"] = [{"id": "t", "command": "make test"}]
        model = ScriptedModel(draft, valid_spec())
        design(self.task, self.card, "D", seed=1, client=model)
        repair_prompt = model.calls[1]["messages"][-1]["content"]
        self.assertIn("not a shell command", repair_prompt)
        self.assertIn('\\"unittest\\" (kind test)', repair_prompt)

    def test_d_recovers_from_a_reply_that_is_not_json(self):
        model = ScriptedModel("not json at all", valid_spec())
        result = design(self.task, self.card, "D", seed=1, client=model)
        self.assertEqual(result["first_pass_errors"], [PARSE_ERROR])
        self.assertTrue(result["valid"])
        self.assertEqual(result["rounds"], 1)

    def test_prompt_shows_no_filled_spec_for_the_task(self):
        # A filled example would let the model copy its way to validity.
        prompt = spec_messages(self.task, self.card, "m")[-1]["content"]
        self.assertNotIn('"max_steps": 6', prompt)
        self.assertNotIn(json.dumps(VALID["stop"]), prompt)

    def test_parse_object_rejects_non_objects(self):
        self.assertEqual(parse_object("[1, 2]")[1][0].code, PARSE_ERROR)
        self.assertEqual(parse_object('```json\n{"a": 1}\n```')[0], {"a": 1})

    def test_valid_spec_fixture_is_valid(self):
        self.assertEqual(validate(valid_spec(), self.card), [])


if __name__ == "__main__":
    unittest.main()


class CommandRepairTests(unittest.TestCase):
    """The compiler reduces an allowlisted command with arguments to its name."""

    def setUp(self):
        self.card = reference_parent()

    def _spec(self, test_command, hook_command, hook_kind="test"):
        spec = valid_spec()
        spec["goal"]["acceptance_tests"] = [{"id": "t", "command": test_command}]
        spec["verification"]["hooks"] = [{"kind": hook_kind, "command": hook_command}]
        return spec

    def test_selector_arguments_are_dropped(self):
        from harnessspec.repair import repair_until_valid

        spec = self._spec("pytest tests/test_app.py::test_add", "pytest -q")
        outcome = repair_until_valid(spec, self.card)
        self.assertTrue(outcome.valid)
        self.assertEqual(outcome.spec["goal"]["acceptance_tests"][0]["command"], "pytest")
        self.assertEqual(outcome.spec["verification"]["hooks"][0]["command"], "pytest")

    def test_python_dash_m_form_is_reduced(self):
        from harnessspec.repair import repair_until_valid

        spec = self._spec("python -m unittest tests.test_app", "python3 -m unittest")
        outcome = repair_until_valid(spec, self.card)
        self.assertTrue(outcome.valid)
        self.assertEqual(outcome.spec["goal"]["acceptance_tests"][0]["command"], "unittest")

    def test_unknown_names_and_wrong_kinds_stay_invalid(self):
        from harnessspec.repair import command_name, repair_until_valid

        self.assertIsNone(command_name("run_tests"))
        self.assertIsNone(command_name("bash -c pytest"))
        self.assertIsNone(command_name("pytest", kind="ast"))
        spec = self._spec("make test", "pytest", hook_kind="ast")
        outcome = repair_until_valid(spec, self.card)
        self.assertFalse(outcome.valid)
        self.assertEqual({e.code for e in outcome.remaining}, {"command.unknown"})

    def test_d_clears_a_selector_without_a_model_round(self):
        draft = valid_spec()
        draft["goal"]["acceptance_tests"] = [{"id": "t", "command": "pytest tests/x.py::t"}]
        model = ScriptedModel(draft)
        result = design(fixture_task(), self.card, "D", seed=1, client=model)
        self.assertFalse(result["first_pass_valid"])
        self.assertTrue(result["valid"])
        self.assertEqual(len(model.calls), 1)


class QaPromptTests(unittest.TestCase):
    """The SWE-QA system message applies only to externally assessed tasks."""

    def setUp(self):
        self.card = reference_parent()

    def test_coding_prompt_is_unchanged(self):
        import hashlib

        from harnessspec.orchestrator import SYSTEM_D

        messages = spec_messages(fixture_task(), self.card, "m")
        self.assertEqual(messages[0]["content"], SYSTEM_D)
        # Pins the system message H3 v2 ran with; editing it would invalidate H3.
        self.assertEqual(hashlib.sha256(SYSTEM_D.encode()).hexdigest()[:16],
                         HASH_SYSTEM_D)

    def test_qa_task_gets_the_qa_message_on_design_and_repair(self):
        from harnessspec.orchestrator import SYSTEM_D_QA

        task = {"task_id": "q1", "statement": "Where is X defined?", "assessment": "external_qa"}
        draft = valid_spec()
        draft["task_id"] = "q1"
        draft["goal"]["acceptance_tests"] = []
        fixed = valid_spec()
        fixed["task_id"] = "q1"
        model = ScriptedModel(draft, fixed)
        design(task, self.card, "D", seed=1, client=model)
        self.assertEqual(len(model.calls), 2)
        for call in model.calls:
            self.assertEqual(call["messages"][0]["content"], SYSTEM_D_QA)
        self.assertIn("require_test_output to false", SYSTEM_D_QA)

    def test_c_and_b_are_unaffected_by_assessment(self):
        task = {"task_id": "q1", "statement": "Where is X defined?", "assessment": "external_qa"}
        model = ScriptedModel({"instruction": "i", "context": ["src"], "tools": ["read_file"], "model": "m"})
        result = design(task, self.card, "C", seed=1, client=model)
        self.assertNotIn("HarnessSpec for read-only", model.calls[0]["messages"][0]["content"])
        self.assertEqual(result["rounds"], 0)


class DigestEquivalenceTests(unittest.TestCase):
    """Ollama 0.32 reports the manifest hash; 0.40 reports the config digest."""

    def _client(self, reported):
        from unittest import mock

        from harnessspec.llm import OllamaClient

        with mock.patch.object(OllamaClient, "_post",
                               return_value={"models": [{"name": load_pin()["name"], "digest": reported}]}):
            return OllamaClient(load_pin())

    def test_pinned_config_digest_passes(self):
        self._client(load_pin()["digest"])

    def test_equivalent_manifest_hash_passes(self):
        self._client("4aaba1ee422af93aad53ecbdfc8a159770cf254a9950b7a4304cf9ee3555ef31")

    def test_other_digest_is_refused(self):
        with self.assertRaises(RuntimeError):
            self._client("sha256:" + "0" * 64)
