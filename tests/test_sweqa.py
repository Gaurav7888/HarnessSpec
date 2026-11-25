"""Mocked model calls and synthetic repository slices."""
from argparse import Namespace
import io
import json
from pathlib import Path
import tarfile
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from harnessspec.designers import fixed_generic_harness
from harnessspec.llm import Reply, load_pin
from harnessspec.results import read_results
from harnessspec.runtime import Action, Session
from harnessspec.sweqa import parse_manifest, read_only_card, source_snapshot
from pilot.run_sweqa import (RUBRIC, execute, finalized_row, run_attempt, source_verified_silent, task_prompt)
from pilot.select_sweqa import evidence


def instance(**overrides):
    return {
        "question_id": "sample:1", "repo": "example/sample", "revision": "a" * 40,
        "question": "How does the package calculate a total?", "reference_answer": "GOLD_ANSWER",
        "gold_files": ["secret/gold.py"], "gold_evidence": [{"file": "secret/gold.py", "start": 2, "end": 2}],
        **overrides,
    }


class Client:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.requests = []

    def chat(self, messages, seed, json_mode=False):
        self.requests.append(json.dumps(messages))
        return next(self.replies)


def response(content, prompt=9, output=4, reasoning=0):
    return Reply(content if isinstance(content, str) else json.dumps(content), prompt, output, 0, reasoning)


class SweqaTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "secret").mkdir()
        (self.root / "secret/gold.py").write_text("# text\nanswer = 42\n", encoding="utf-8")

    def test_parse_manifest_and_evidence(self):
        self.assertEqual(parse_manifest({"instances": [instance()]}), [instance()])
        for item in [instance(repo="../other"), instance(revision="master"),
                     instance(gold_files=["../a.py"], gold_evidence=[]),
                     instance(gold_files=["/a.py"], gold_evidence=[]),
                     instance(gold_evidence=[{"file": "a.py", "start": 2, "end": 1}])]:
            with self.subTest(item=item), self.assertRaises(ValueError):
                parse_manifest({"instances": [item]})
        with self.assertRaisesRegex(ValueError, "duplicate"):
            parse_manifest({"instances": [instance(), instance()]})
        self.assertEqual(evidence("See `./src/a.py` (lines 3-5), `tests/b.py:9`."),
                         (["src/a.py", "tests/b.py"], [
                             {"file": "src/a.py", "start": 3, "end": 5},
                             {"file": "tests/b.py", "start": 9, "end": 9},
                         ]))

    def test_snapshot_filters_metadata_and_symlinks(self):
        archive = self.root / "test.tar.gz"
        with tarfile.open(archive, "w:gz", pax_headers={"comment": "a" * 40}) as output:
            root = tarfile.TarInfo("package")
            root.type = tarfile.DIRTYPE
            output.addfile(root)
            for name in ("ok.py", ".git/config", "../escape.py"):
                entry = tarfile.TarInfo(f"package/{name}")
                entry.size = 2
                output.addfile(entry, io.BytesIO(b"ok"))
            link = tarfile.TarInfo("package/link.py")
            link.type = tarfile.SYMTYPE
            link.linkname = "ok.py"
            output.addfile(link)
        with source_snapshot(archive, "a" * 40) as workspace:
            self.assertEqual([file.name for file in workspace.iterdir()], ["ok.py"])
        with self.assertRaisesRegex(ValueError, "archive commit"):
            with source_snapshot(archive, "b" * 40):
                pass

    def test_read_only_tools(self):
        card = read_only_card()
        spec = fixed_generic_harness("sample", card, "answer")
        session = Session(spec, card, self.root)
        for tool, permission, path in (
            ("write_file", "write", "secret/gold.py"), ("run_tests", "exec", "."),
            ("read_file", "write", "secret/gold.py"), ("read_file", "read", "../gold.py"),
        ):
            with self.subTest(tool=tool, path=path):
                self.assertFalse(session.step(Action("tool", 1, 0, tool, permission, path, "changed")).applied)
        self.assertTrue(session.step(Action("tool", 1, 0, "read_file", "read", "secret/gold.py")).applied)
        self.assertIn("answer = 42", (self.root / "secret/gold.py").read_text())

    def test_invalid_D_retains_cost_and_never_executes(self):
        client = Client([response("{}", prompt=17, output=4, reasoning=3)] * 4)
        artifact = run_attempt(instance(), "D", 1, load_pin(), self.root, client)
        final = finalized_row(artifact, {})
        self.assertGreater(final["design_tokens"], 0)
        self.assertEqual(final["design_tokens"], 24 * len(client.requests))
        self.assertGreater(final["rounds"], 0)
        self.assertFalse(final["first_pass_valid"])
        self.assertFalse(final["resolved"])
        self.assertEqual(final["subagent_tokens"], 0)
        self.assertIsNone(artifact["runtime_trace"])
        self.assertTrue(artifact["design"]["remaining_errors"])
        self.assertNotIn("GOLD_ANSWER", str(client.requests))
        self.assertNotIn("secret/gold.py", str(client.requests))

    def test_mock_execution_counts_malformed_and_silent(self):
        client = Client([
            response("not JSON"), response({"kind": "tool", "tool": "list_dir", "path": ".", "permission": "read"}),
            response({"kind": "return", "summary": "a confident result"}, reasoning=2),
        ])
        artifact = run_attempt(instance(), "A", 1, load_pin(), self.root, client)
        record = artifact["row"]
        self.assertTrue(record["silent_handoff"])
        self.assertTrue(artifact["diagnostics"]["return_accepted"])
        self.assertIsNone(finalized_row(artifact, {}))
        self.assertEqual(record["subagent_tokens"], 41)
        self.assertEqual(artifact["runtime_trace"]["tokens_used"], 14)
        self.assertEqual(record["tool_denials"], 1)
        self.assertIn("remaining tokens", client.requests[-1])
        self.assertIn("remaining seconds", client.requests[-1])
        self.assertNotIn("GOLD_ANSWER", str(client.requests))
        self.assertNotIn("secret/gold.py", str(client.requests))

    def test_brief_and_tuple_execute_as_emitted(self):
        emitted = {"instruction": "Inspect this package", "context": ["."],
                   "tools": ["read_file"], "model": load_pin()["name"]}
        for designer, first in [("B", emitted["instruction"]), ("C", emitted)]:
            with self.subTest(designer=designer):
                client = Client([response(first), response({"kind": "return", "summary": "answer"})])
                run = run_attempt(instance(), designer, 1, load_pin(), self.root, client)
                self.assertTrue(run["diagnostics"]["return_accepted"])
                self.assertEqual(run["executable_spec"]["goal"]["statement"], emitted["instruction"])
                self.assertIsNone(run["diagnostics"]["not_executable"])
                self.assertIs(run["row"]["first_pass_valid"], False)
                self.assertEqual(run["diagnostics"]["compiled_validity_applicable"], designer == "C")
                self.assertEqual(run["row"]["design_tokens"], 13)
                self.assertEqual(run["row"]["subagent_tokens"], 13)
                if designer == "C":
                    self.assertFalse(run["design"]["valid"])
                    self.assertEqual([t["name"] for t in run["executable_spec"]["tools"]], ["read_file"])

    def test_rejected_tuple_retains_actual_cost(self):
        client = Client([response({"instruction": "read", "context": ["."], "tools": ["shell"],
                                   "model": load_pin()["name"]})])
        run = run_attempt(instance(), "C", 1, load_pin(), self.root, client)
        error = run["diagnostics"]["not_executable"]
        self.assertEqual(error["reason"], "tuple.tool")
        self.assertIn("shell", error["detail"])
        self.assertFalse(finalized_row(run, {})["resolved"])
        self.assertEqual((run["row"]["design_tokens"], run["row"]["subagent_tokens"]), (13, 0))
        self.assertIsNone(run["runtime_trace"])

    def test_silent_requires_an_accepted_summary_and_counts_verified_lines(self):
        for file, line, usable in [("missing.py", 1, 0), ("secret/gold.py", 3, 0),
                                   ("secret/gold.py", 2, 1)]:
            with self.subTest(file=file, line=line):
                answer = {"kind": "return", "summary": "answer", "citations": [{"file": file, "line": line}]}
                run = run_attempt(instance(), "A", 1, load_pin(), self.root, Client([response(answer)]))
                self.assertTrue(run["diagnostics"]["return_accepted"])
                self.assertFalse(run["diagnostics"]["format_silent_handoff"])
                self.assertEqual(run["evidence"]["usable_repository_citations"], usable)
                self.assertEqual(run["row"]["silent_handoff"], usable == 0)
        self.assertFalse(source_verified_silent(True, None, None))
        self.assertFalse(source_verified_silent(True, {"summary": " "}, None))
        self.assertFalse(source_verified_silent(False, {"summary": "rejected"}, None))

    def test_reads_cited_lines_past_the_default_output_cap(self):
        (self.root / "secret/gold.py").write_text("# filler\n" * 1500 + "final_total = 42\n")
        client = Client([
            response({"kind": "tool", "tool": "read_file", "path": "secret/gold.py",
                      "permission": "read", "start_line": 1500, "end_line": 1502}),
            response({"kind": "return", "summary": "The final total is 42."}),
        ])
        artifact = run_attempt(instance(), "A", 1, load_pin(), self.root, client)
        self.assertIn("1501: final_total = 42", client.requests[-1])
        self.assertEqual(artifact["row"]["tool_denials"], 0)
        card = read_only_card()
        spec = fixed_generic_harness("sample", card, "answer")
        session = Session(spec, card, self.root)
        observation = session.step(Action("tool", 1, 0, "read_file", "read", "secret/gold.py",
                                          line_range=(1, 201)))
        self.assertEqual(observation.code, "tool.line_range")

    def test_gold_evidence_and_external_grade(self):
        client = Client([response({"kind": "return", "summary": "reasoned answer",
                                   "citations": [{"file": "secret/gold.py", "line": 2}]})])
        artifact = run_attempt(instance(), "A", 1, load_pin(), self.root, client)
        self.assertEqual(artifact["evidence"]["gold_range_files_matched"], ["secret/gold.py"])
        self.assertFalse(artifact["row"]["silent_handoff"])
        for score, resolves in [(7, True), (6, False)]:
            grades = {artifact["grading_id"]: {field: score for field in RUBRIC}}
            self.assertIs(finalized_row(artifact, grades)["resolved"], resolves)

    def test_verified_D_return_without_citation_is_rejected(self):
        spec = fixed_generic_harness("sample:1", read_only_card(), task_prompt(instance())["statement"])
        spec["return_contract"].update(require_citations=True, min_citations=1)
        client = Client([response(spec), response({"kind": "return", "summary": "no citation"})])
        artifact = run_attempt(instance(), "D", 1, load_pin(), self.root, client)
        self.assertTrue(artifact["design"]["valid"])
        self.assertFalse(artifact["row"]["silent_handoff"])
        self.assertFalse(artifact["row"]["resolved"])
        self.assertEqual(artifact["runtime_trace"]["stopped"], "return_rejected")

    def test_forbidden_test_hooks_are_logged(self):
        spec = fixed_generic_harness("sample:1", read_only_card(), "answer")
        spec["verification"]["hooks"] = [{"kind": "test", "command": "unittest"}]
        client = Client([response(spec), response({"kind": "return", "summary": "answer"})])
        with patch("pilot.run_sweqa.run_hook") as hook:
            artifact = run_attempt(instance(), "D", 1, load_pin(), self.root, client)
        hook.assert_not_called()
        self.assertEqual(artifact["row"]["hook_failures"], 1)
        self.assertFalse(artifact["row"]["silent_handoff"])

    def test_intercepted_reply_is_counted_but_uncharged(self):
        client = Client([response({"kind": "return", "summary": "x"}, output=8001)])
        artifact = run_attempt(instance(), "A", 1, load_pin(), self.root, client)
        self.assertEqual(artifact["runtime_trace"]["tokens_used"], 0)
        self.assertEqual(artifact["row"]["subagent_tokens"], 8010)
        self.assertEqual(artifact["row"]["budget_violations"], 1)
        self.assertFalse(artifact["row"]["resolved"])

    def test_pending_grades_resume_without_another_model_call(self):
        args = Namespace(output=self.root / "results.json", trace_dir=self.root / "traces", resume=False,
                         grades=None, grading_packet=self.root / "packet.json", archive_cache=self.root,
                         grade_only=False, energy_dir=None)
        task = instance()
        pin = load_pin()
        plan = [(("sweqa", "sample:1", "A", 1), task)]
        client = Client([response({"kind": "return", "summary": "answer"})])
        with patch("pilot.run_sweqa.OllamaClient", return_value=client), patch(
            "pilot.run_sweqa.prepare_sources", return_value={(task["repo"], task["revision"]): self.root}
        ):
            execute(args, plan, pin)
        self.assertEqual(read_results([args.output]), [])
        identifier = json.loads(args.grading_packet.read_text())[0]["grading_id"]
        args.grades = self.root / "grades.json"
        args.grades.write_text(json.dumps({identifier: {**dict.fromkeys(RUBRIC, 9),
                                                        "rationale": "mock review"}}), encoding="utf-8")
        args.resume = args.grade_only = True
        with patch("pilot.run_sweqa.OllamaClient") as model:
            execute(args, plan, pin)
            execute(args, plan, pin)
        model.assert_not_called()
        self.assertEqual(len(read_results([args.output])), 1)
        self.assertTrue(read_results([args.output])[0]["resolved"])

    def test_examples_follow_grants_and_return_contract(self):
        from pilot.run_sweqa import opening_prompt
        spec = fixed_generic_harness("sample", read_only_card(), "Answer.")
        spec["tools"] = [{"name": "read_file", "permission": "read", "paths": ["module.py"]}]
        spec["return_contract"]["require_test_output"] = True
        prompt = opening_prompt("Question?", spec)
        examples = [json.loads(line) for line in prompt.splitlines() if line.startswith("{")]
        self.assertEqual(examples, [{"kind": "tool", "tool": "read_file", "permission": "read",
                                     "path": "module.py"}])
        shape = next(line.removeprefix("Return shape: ") for line in prompt.splitlines()
                     if line.startswith("Return shape: "))
        self.assertIn("test_output", json.loads(shape))

    def test_wrong_discriminator_feedback_and_no_thirteenth_call(self):
        from pilot.run_sweqa import RecordingClient, run_answer
        for kind in ("read", "read_file"):
            with self.subTest(kind=kind):
                spec = fixed_generic_harness("sample", read_only_card(), "Answer.")
                spec["budgets"]["max_steps"] = 2
                client = Client([response({"kind": kind, "path": "."})] * 2)
                trace, _ = run_answer(instance(), spec, read_only_card(), self.root,
                                      RecordingClient(client), 1)
                self.assertEqual(len(client.requests), 2)
                self.assertIn("Expected a JSON object", client.requests[-1])
                self.assertEqual([e.code for e in trace.events],
                                 ["action.unknown", "action.unknown", "budget.exhausted"])
                self.assertEqual(trace.budget_violations, 0)
                self.assertFalse(trace.return_accepted)

    def test_preflight_handles_exact_token_and_wall_limits(self):
        for limit in ("max_tokens", "max_seconds"):
            spec = fixed_generic_harness("sample", read_only_card(), "Answer.")
            session = Session(spec, read_only_card(), self.root)
            if limit == "max_seconds":
                session.clock.advance(session.budgets[limit])
            else:
                session.step(Action("unparsed", session.budgets[limit], 0))
            with self.subTest(limit=limit):
                self.assertFalse(session.ready_for_call())
                events = len(session.trace.events)
                self.assertFalse(session.ready_for_call())
                self.assertEqual(events, len(session.trace.events))
                self.assertEqual(session.trace.stopped, spec["stop"]["on_exhaust"])

    def test_listing_and_reading_require_the_right_target_type(self):
        spec = fixed_generic_harness("sample", read_only_card(), "Answer.")
        session = Session(spec, read_only_card(), self.root)
        for tool, path in (("list_dir", "secret/gold.py"), ("read_file", "secret"), ("read_file", "absent")):
            observed = session.step(Action("tool", 1, 0, tool, "read", path))
            self.assertEqual(observed.code, "tool.path")
            self.assertEqual(observed.output, "")

    def test_validate_external_grades_before_writing(self):
        from pilot.run_sweqa import load_grades
        grade = {**dict.fromkeys(RUBRIC, 7), "rationale": "Independent review."}
        path = self.root / "review.json"
        for update in ({"clarity": True}, {"reasoning": 11}, {"relevance": -1},
                       {"clarity": 5.5}, {"extra": 1}, {"rationale": "  "}):
            path.write_text(json.dumps({"candidate": {**grade, **update}}))
            with self.subTest(update=update), self.assertRaises(ValueError):
                load_grades(path)
        path.write_text('{"duplicate": {}, "duplicate": {}}')
        with self.assertRaisesRegex(ValueError, "duplicate"):
            load_grades(path)

    def test_grade_only_refuses_missing_traces_and_unknown_ids_offline(self):
        from pilot.run_sweqa import artifact_path, grading_packet
        task = instance()
        pin = load_pin()
        key = ("sweqa", task["question_id"], "A", 1)
        args = Namespace(output=self.root / "rows", grading_packet=self.root / "packet",
                         trace_dir=self.root / "traces", energy_dir=None, grades=None,
                         resume=True, grade_only=True)
        with patch("pilot.run_sweqa.OllamaClient", side_effect=AssertionError):
            with self.assertRaisesRegex(ValueError, "requires completed traces"):
                execute(args, [(key, task)], pin)
            artifact = run_attempt(task, "A", 1, pin, self.root, Client([response(
                {"kind": "return", "summary": "candidate answer"})]))
            packet = grading_packet(artifact, task)
            self.assertEqual(packet["reference_ranges"], task["gold_evidence"])
            self.assertEqual(packet["dimensions"], list(RUBRIC))
            self.assertFalse({"designer", "seed", "task_id"} & packet.keys())
            args.trace_dir.mkdir()
            path = artifact_path(args.trace_dir, key)
            path.write_text(json.dumps(artifact))
            original = path.read_bytes()
            args.grades = self.root / "grades"
            args.grades.write_text(json.dumps({"unknown": {**dict.fromkeys(RUBRIC, 8), "rationale": "test"}}))
            with self.assertRaisesRegex(ValueError, "unknown grading ID"):
                execute(args, [(key, task)], pin)
            args.grades = None
            execute(args, [(key, task)], pin)
            args.output = path
            with self.assertRaisesRegex(ValueError, "outside the trace"):
                execute(args, [(key, task)], pin)
            self.assertEqual(list(args.trace_dir.iterdir()), [path])
            self.assertEqual(original, path.read_bytes())
            args.output = self.root / "rows"
            artifact["answer"]["summary"] = "different answer"
            path.write_text(json.dumps(artifact))
            with self.assertRaisesRegex(ValueError, "grading ID does not match"):
                execute(args, [(key, task)], pin)

    def test_historical_outputs_are_protected(self):
        from harnessspec.results import check_output_path, SCHEMA_PATH
        for name in ("sweqa_results.json", "metrics_summary.md", "traces/sweqa",
                     "traces/sweqa-energy/new.json", "snapshots/sweqa-ad-seed1-v1/SHA256SUMS"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "frozen pilot"):
                check_output_path(SCHEMA_PATH.parent / name)
