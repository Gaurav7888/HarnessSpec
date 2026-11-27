"""SWE-bench runner without a model server: clone, install, hooks, and rows."""

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from harnessspec.hooks import HookOutcome
from harnessspec.llm import Reply
from harnessspec.results import read_results
from harnessspec.swebench import (
    attempt,
    git_clone,
    make_test_hook,
    prepare_workspace,
    run_install,
    run_plan,
    swebench_card,
)
from harnessspec.execution import executable_spec
from harnessspec.orchestrator import design


def git(path: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
        cwd=path, check=True, capture_output=True, text=True,
    )
    return completed.stdout.strip()


def origin_repo(path: Path) -> str:
    path.mkdir()
    git(path, "init", "-b", "main")
    (path / "README.md").write_text("bug\n", encoding="utf-8")
    git(path, "add", "README.md")
    git(path, "commit", "-m", "init")
    return git(path, "rev-parse", "HEAD")


def instance(origin: Path, commit: str, **overrides) -> dict:
    version = f"{sys.version_info[0]}.{sys.version_info[1]}"
    row = {
        "instance_id": "local__demo",
        "repo": "local/demo",
        "clone_url": str(origin),
        "base_commit": commit,
        "python": version,
        "install_commands": ["python -c \"open('ready','w').write('yes')\""],
        "fail_to_pass": ["tests/test_app.py::test_add"],
        "problem_statement": "Make the program pass its test.",
        "test_command": "pytest",
    }
    row.update(overrides)
    return row


class Scripted:
    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.calls = 0

    def chat(self, messages, seed, json_mode=False):
        self.calls += 1
        return Reply(self.replies.pop(0), 4, 3, 0.0)


def passing(_python, _workspace, _tests, _timeout):
    return HookOutcome("test", "pytest", True, "1 passed")


class SwebenchRunnerTests(unittest.TestCase):
    def test_card_accepts_designer_a(self):
        card = swebench_card()
        task = {"task_id": "t", "statement": "Fix it."}
        spec = executable_spec(design(task, card, "A", 1), task, card)
        self.assertEqual(spec["model"]["tier"], "7-14B")
        self.assertEqual([tool["name"] for tool in spec["tools"]], ["read_file", "list_dir", "write_file"])

    def test_prepare_clones_the_base_commit_and_runs_install(self):
        import tempfile
        held = tempfile.TemporaryDirectory()
        self.addCleanup(held.cleanup)
        root = Path(held.name)
        commit = origin_repo(root / "origin")
        checkout, python = prepare_workspace(instance(root / "origin", commit), root / "work")
        self.assertEqual(git(checkout, "rev-parse", "HEAD"), commit)
        self.assertEqual((checkout / "ready").read_text(encoding="utf-8"), "yes")
        self.assertTrue(python.endswith("/bin/python"))

    def test_reused_checkout_drops_files_the_previous_designer_left(self):
        import tempfile
        held = tempfile.TemporaryDirectory()
        self.addCleanup(held.cleanup)
        root = Path(held.name)
        commit = origin_repo(root / "origin")
        inst = instance(root / "origin", commit)
        dest = root / "work" / "checkout"
        git_clone(inst, dest)
        (dest / "README.md").write_text("edited by A\n", encoding="utf-8")
        (dest / "new_by_a.py").write_text("x = 1\n", encoding="utf-8")
        git_clone(inst, dest)
        self.assertEqual((dest / "README.md").read_text(encoding="utf-8"), "bug\n")
        self.assertFalse((dest / "new_by_a.py").exists())

    def test_setup_failure_writes_no_row_and_is_retried(self):
        import tempfile
        from harnessspec.swebench import SetupError
        held = tempfile.TemporaryDirectory()
        self.addCleanup(held.cleanup)
        root = Path(held.name)

        def broken(_instance, _workdir):
            raise SetupError("pip exploded")

        inst = {"instance_id": "x__y-1", "problem_statement": "p", "fail_to_pass": ["t::a"]}
        out, traces = root / "rows.json", root / "traces"
        rows = run_plan([inst], ["A"], [1], root / "work", out, traces, {"name": "m", "digest": "d"},
                        lambda: None, prepare=broken)
        self.assertEqual(rows, [])
        self.assertFalse(out.exists())
        self.assertTrue((traces / "x__y-1__A__seed1__setup_failed.json").exists())

    def test_install_records_a_failing_command(self):
        import tempfile
        from harnessspec.swebench import SetupError
        held = tempfile.TemporaryDirectory()
        self.addCleanup(held.cleanup)
        with self.assertRaises(SetupError):
            run_install(sys.executable, ["python -c \"raise SystemExit(3)\""], Path(held.name))

    def test_test_hooks_run_the_fail_to_pass_ids(self):
        captured = {}

        def fake_run(argv, **kwargs):
            captured["argv"] = argv
            captured["shell"] = kwargs.get("shell")

            class Completed:
                returncode = 1
                stdout = ""
                stderr = "1 failed"

            return Completed()

        hook = make_test_hook({"fail_to_pass": ["tests/test_app.py::test_add"]}, sys.executable)
        with mock.patch("harnessspec.swebench.subprocess.run", fake_run):
            outcome = hook({"kind": "test", "command": "unittest"}, Path("."), ["."], 5)
        self.assertFalse(outcome.passed)
        self.assertFalse(captured["shell"])
        self.assertEqual(captured["argv"][1:4], ["-m", "pytest", "-q"])
        self.assertIn("tests/test_app.py::test_add", captured["argv"])

    def test_test_patch_is_applied_for_the_run_and_hidden_after(self):
        import tempfile
        from harnessspec import swebench
        held = tempfile.TemporaryDirectory()
        self.addCleanup(held.cleanup)
        root = Path(held.name)
        origin = root / "origin"
        commit = origin_repo(origin)
        (origin / "tests").mkdir()
        (origin / "tests" / "test_app.py").write_text("def test_old():\n    pass\n", encoding="utf-8")
        git(origin, "add", "tests/test_app.py")
        git(origin, "commit", "-m", "tests")
        commit = git(origin, "rev-parse", "HEAD")
        checkout = root / "work" / "checkout"
        git_clone(instance(origin, commit), checkout)
        patch = (
            "diff --git a/tests/test_app.py b/tests/test_app.py\n"
            "--- a/tests/test_app.py\n+++ b/tests/test_app.py\n"
            "@@ -1,2 +1,4 @@\n def test_old():\n     pass\n+def test_add():\n+    pass\n"
        )
        # The subagent edited the test file and the source.
        (checkout / "tests" / "test_app.py").write_text("# agent edit\n", encoding="utf-8")
        (checkout / "README.md").write_text("fixed\n", encoding="utf-8")
        seen = {}

        def fake_pytest(python, workspace, tests, timeout):
            seen["test_file"] = (workspace / "tests" / "test_app.py").read_text(encoding="utf-8")
            seen["readme"] = (workspace / "README.md").read_text(encoding="utf-8")
            return HookOutcome("test", "pytest", True, "1 passed")

        row = instance(origin, commit, test_patch=patch)
        with mock.patch.object(swebench, "_pytest_nodes", fake_pytest):
            outcome = swebench.run_with_test_patch(row, sys.executable, checkout, 5)
        self.assertTrue(outcome.passed)
        self.assertIn("def test_add", seen["test_file"])         # gold test present for the run
        self.assertNotIn("agent edit", seen["test_file"])       # on the base version, not the agent's
        self.assertEqual(seen["readme"], "fixed\n")            # with the agent's source change
        self.assertEqual((checkout / "tests" / "test_app.py").read_text(encoding="utf-8"), "# agent edit\n")
        self.assertEqual(git(checkout, "diff", "--cached", "--name-only"), "")
        self.assertFalse(list(checkout.parent.glob("*.test.patch")))

    def test_attempt_writes_a_valid_row_and_resume_skips_it(self):
        import tempfile
        held = tempfile.TemporaryDirectory()
        self.addCleanup(held.cleanup)
        root = Path(held.name)
        workspace = root / "checkout"
        workspace.mkdir()
        (workspace / "src").mkdir()

        def prepare(instance_row, workdir):
            return workspace, sys.executable

        row = instance(root / "missing", "abc")
        client = Scripted(
            '{"kind":"return","summary":"done","citations":[{"file":"README.md","line":1}],"claims":[]}'
        )
        pin = {"name": "qwen2.5-coder:7b", "digest": "sha256:" + "ab" * 32}
        output = root / "swebench_results.json"
        traces = root / "traces"
        with mock.patch("harnessspec.swebench._pytest_nodes", passing):
            run_plan(
                [row], ["A"], [1], root / "work", output, traces, pin, lambda: client,
                prepare=prepare,
            )
        self.assertEqual(client.calls, 1)
        written = json.loads(output.read_text(encoding="utf-8"))[0]
        self.assertTrue(written["resolved"])
        self.assertEqual(written["design_tokens"], 0)
        self.assertEqual(written["subagent_tokens"], 7)
        self.assertFalse(written["silent_handoff"])
        again = Scripted('{"kind":"return","summary":"again"}')
        with mock.patch("harnessspec.swebench._pytest_nodes", passing):
            run_plan([row], ["A"], [1], root / "work", output, traces, pin, lambda: again)
        self.assertEqual(again.calls, 0)
        loaded = read_results([output])
        self.assertEqual(len(loaded), 1)
        self.assertTrue((traces / "local__demo__A__seed1.json").exists())

    def test_invalid_design_is_recorded_and_not_run(self):
        import tempfile
        held = tempfile.TemporaryDirectory()
        self.addCleanup(held.cleanup)
        root = Path(held.name)
        workspace = root / "checkout"
        workspace.mkdir()
        client = Scripted(*(["{}" ] * 8))
        pin = {"name": "qwen2.5-coder:7b", "digest": "sha256:" + "cd" * 32}
        row = instance(root / "missing", "abc")
        with mock.patch("harnessspec.swebench._pytest_nodes", passing):
            written, record = attempt(
                row, "D", 1, client, pin, root / "work",
                prepare=lambda _instance, _workdir: (workspace, sys.executable),
            )
        self.assertFalse(written["resolved"])
        self.assertEqual(written["subagent_tokens"], 0)
        self.assertGreater(written["design_tokens"], 0)
        self.assertIn("not_executable", record)
        self.assertFalse((workspace / "src").exists())


class TruncatedIdTests(unittest.TestCase):
    def test_truncated_parametrized_id_runs_its_file(self):
        from harnessspec.swebench import runnable_test_ids
        ids = ["t/test_w.py::test_a[x]", "t/test_w.py::test_b[a:", "t/test_w.py::test_c", "u/test_v.py::k"]
        self.assertEqual(runnable_test_ids(ids),
                         ["t/test_w.py::test_a[x]", "t/test_w.py", "t/test_w.py::test_c", "u/test_v.py::k"])


class BrokenCheckoutTests(unittest.TestCase):
    def test_a_broken_leftover_clone_is_replaced(self):
        import tempfile
        held = tempfile.TemporaryDirectory()
        self.addCleanup(held.cleanup)
        root = Path(held.name)
        commit = origin_repo(root / "origin")
        dest = root / "work" / "checkout"
        (dest / ".git").mkdir(parents=True)          # a clone killed before it finished
        git_clone(instance(root / "origin", commit), dest)
        self.assertEqual(git(dest, "rev-parse", "HEAD"), commit)
