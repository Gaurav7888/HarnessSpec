"""Unattended SWE-bench runner for one cluster job.

The job supplies the Python named on each instance and an Ollama server.
This module clones the repo, installs it, asks ``design()`` for a spec,
refuses anything ``executable_spec`` rejects, and runs the subagent.
Test hooks run that instance's ``fail_to_pass`` node ids, not the whole
suite. ``resolved`` is those same tests at the end of the run.

The parent card allows read, then write, on the checkout. The ceilings are
30 steps, 8000 generated tokens, and 900 seconds. 900 seconds is the
SWE-QA ceiling. The fixture's 120 seconds cannot cover a real edit loop.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path

from harnessspec.execution import NotExecutable, executable_spec
from harnessspec.hooks import HookOutcome, run_hook
from harnessspec.llm import Reply, load_pin
from harnessspec.orchestrator import design
from harnessspec.parent import TIERS, CapabilityCard, ToolGrant
from harnessspec.results import result_key, validate_result, write_json
from harnessspec.runtime import SystemClock
from harnessspec.subagent import run_subagent

MAX_STEPS = 30
MAX_TOKENS = 8000
MAX_SECONDS = 900
FINAL_TEST_TIMEOUT = 600.0


class SetupError(RuntimeError):
    """The checkout or install failed before any model call."""


class GeneratedTokenBudget:
    """Charge the step budget for generated tokens. The row stores the full server count."""

    def __init__(self, client):
        self.client = client

    def chat(self, messages, seed, json_mode=False) -> Reply:
        return self.client.chat(messages, seed=seed, json_mode=json_mode)

    def budget_tokens(self, reply: Reply) -> int:
        return reply.output_tokens + reply.reasoning_tokens


def swebench_card() -> CapabilityCard:
    return CapabilityCard(
        tools={
            "read_file": ToolGrant("read", (".",)),
            "list_dir": ToolGrant("read", (".",)),
            "write_file": ToolGrant("write", (".",)),
        },
        context_paths=(".",),
        max_steps=MAX_STEPS,
        max_tokens=MAX_TOKENS,
        max_seconds=MAX_SECONDS,
        allowed_tiers=TIERS,
    )


def resolve_python(version: str) -> str:
    """Return an interpreter whose major.minor is ``version``."""
    named = shutil.which(f"python{version}")
    if named:
        return named
    fallback = shutil.which("python3") or shutil.which("python")
    if fallback:
        reported = subprocess.check_output(
            [fallback, "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"],
            text=True,
        ).strip()
        if reported == version:
            return fallback
    raise SetupError(f"python {version} is not on PATH")


def git_clone(instance: dict, dest: Path) -> None:
    url = instance.get("clone_url") or f"https://github.com/{instance['repo']}.git"
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    if not (dest / ".git").exists():
        if dest.exists():
            shutil.rmtree(dest)
        subprocess.run(["git", "clone", url, str(dest)], check=True, env=env)
    subprocess.run(
        ["git", "checkout", "--force", instance["base_commit"]],
        cwd=dest, check=True, env=env,
    )
    # A reused checkout keeps files the previous designer created; checkout
    # --force restores tracked files only. Build artifacts are ignored files
    # and stay (no -x), so the editable install keeps working.
    subprocess.run(["git", "clean", "-fd"], cwd=dest, check=True, env=env)


def run_install(python: str, commands: list[str], workspace: Path) -> None:
    env = os.environ.copy()
    bindir = str(Path(python).resolve().parent)
    env["PATH"] = bindir + os.pathsep + env.get("PATH", "")
    env["VIRTUAL_ENV"] = bindir
    for command in commands:
        argv = shlex.split(command)
        if not argv:
            continue
        if argv[0] == "python":
            argv[0] = python
        completed = subprocess.run(
            argv,
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            shell=False,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise SetupError(detail[-2000:] or f"{command} exited {completed.returncode}")


def make_venv(python: str, venv: Path) -> str:
    if not (venv / "bin" / "python").exists():
        subprocess.run([python, "-m", "venv", str(venv)], check=True)
    return str(venv / "bin" / "python")


def prepare_workspace(instance: dict, workdir: Path) -> tuple[Path, str]:
    """Clone at ``base_commit`` and install. The venv sits beside the checkout."""
    workdir.mkdir(parents=True, exist_ok=True)
    checkout = workdir / instance["instance_id"]
    git_clone(instance, checkout)
    python = make_venv(resolve_python(instance["python"]), workdir / f"{instance['instance_id']}.venv")
    run_install(python, list(instance.get("install_commands") or []), checkout)
    return checkout, python


def _pytest_nodes(python: str, workspace: Path, tests: list[str], timeout: float) -> HookOutcome:
    completed = subprocess.run(
        [python, "-m", "pytest", "-q", "--tb=line", *tests],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=max(1.0, timeout),
        shell=False,
        check=False,
    )
    output = (completed.stdout + completed.stderr).strip()
    return HookOutcome("test", "pytest", completed.returncode == 0, output)


def test_patch_files(patch: str) -> list[str]:
    """Paths a unified git diff touches (the ``b/`` side of each ``diff --git``)."""
    return [line.split(" b/", 1)[1] for line in patch.splitlines()
            if line.startswith("diff --git ") and " b/" in line]


def runnable_test_ids(ids: list[str]) -> list[str]:
    """Node ids pytest can resolve. A truncated id is replaced by its test file.

    SWE-bench Verified stores some parametrized ids cut at a space
    (pylint-4551: ``test_get_annotation_annassign[a:``). No checkout has a node
    with that name, so the file runs instead; SWE-bench's own harness runs
    whole test files too.
    """
    out: list[str] = []
    for test in ids:
        name = test.split("::", 1)[1] if "::" in test else ""
        target = test.split("::", 1)[0] if name.count("[") != name.count("]") else test
        if target not in out:
            out.append(target)
    return out


def run_with_test_patch(instance: dict, python: str, workspace: Path, timeout: float) -> HookOutcome:
    """Run fail_to_pass the way SWE-bench evaluates: the subagent's source with the gold tests.

    The test patch adds or changes the fail_to_pass tests, so they do not exist (or
    are the old version) in the checkout the subagent sees. For each run: keep the
    subagent's copies of the patched files, reset them to the base commit, apply the
    test patch, run the tests, then put the subagent's copies back byte for byte.
    The subagent never sees the patch in its checkout.
    """
    tests = runnable_test_ids(list(instance["fail_to_pass"]))
    patch = instance.get("test_patch")
    if not patch:
        return _pytest_nodes(python, workspace, tests, timeout)
    files = test_patch_files(patch)
    saved = {name: ((workspace / name).read_bytes() if (workspace / name).is_file() else None)
             for name in files}
    base = instance["base_commit"]
    patch_file = workspace.parent / f".{workspace.name}.test.patch"
    try:
        for name in files:
            exists = subprocess.run(["git", "cat-file", "-e", f"{base}:{name}"], cwd=workspace,
                                    capture_output=True, check=False).returncode == 0
            if exists:
                subprocess.run(["git", "checkout", base, "--", name], cwd=workspace,
                               capture_output=True, check=True)
            elif (workspace / name).exists():
                (workspace / name).unlink()
        patch_file.write_text(patch, encoding="utf-8")
        applied = subprocess.run(["git", "apply", "--whitespace=nowarn", str(patch_file)], cwd=workspace,
                                 capture_output=True, text=True, check=False)
        if applied.returncode != 0:
            return HookOutcome("test", "pytest", False, "test patch did not apply: " + applied.stderr[-1000:])
        return _pytest_nodes(python, workspace, tests, timeout)
    finally:
        for name, data in saved.items():
            target = workspace / name
            if data is None:
                if target.exists():
                    target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        # Leave the index as the checkout had it: no staged test-patch changes.
        subprocess.run(["git", "reset", "-q", "--", *files], cwd=workspace, capture_output=True, check=False)
        patch_file.unlink(missing_ok=True)


def make_test_hook(instance: dict, python: str):
    """Map every test-kind hook onto the instance's fail_to_pass run. Other hooks stay on the allowlist."""

    def hook(spec_hook: dict, workspace: Path, include: list[str], timeout: float) -> HookOutcome:
        if spec_hook.get("kind") == "test" and spec_hook.get("command") in {"pytest", "unittest"}:
            return run_with_test_patch(instance, python, workspace, timeout)
        return run_hook(spec_hook, workspace, include, timeout)

    return hook


def server_tokens(log: list[dict]) -> int:
    return sum(item["prompt_tokens"] + item["output_tokens"] for item in log)


def schema_row(
    task_id: str,
    designer: str,
    seed: int,
    pin: dict,
    design_tokens: int,
    rounds: int,
    first_pass_valid: bool | None,
    resolved: bool,
    silent_handoff: bool,
    budget_violations: int,
    tool_denials: int,
    hook_failures: int,
    wall_clock_s: float,
    subagent_tokens: int,
) -> dict:
    row = {
        "task_id": task_id,
        "benchmark": "swebench",
        "designer": designer,
        "seed": seed,
        "model": pin["name"],
        "model_digest": pin["digest"],
        "design_tokens": design_tokens,
        "subagent_tokens": subagent_tokens,
        "rounds": rounds,
        "first_pass_valid": False if first_pass_valid is None else first_pass_valid,
        "resolved": resolved,
        "silent_handoff": silent_handoff,
        "budget_violations": budget_violations,
        "tool_denials": tool_denials,
        "hook_failures": hook_failures,
        "wall_clock_s": round(wall_clock_s, 3),
    }
    validate_result(row)
    return row


def _blank_row(task_id, designer, seed, pin, design_tokens, rounds, first_pass_valid, wall) -> dict:
    return schema_row(
        task_id, designer, seed, pin, design_tokens, rounds, first_pass_valid,
        False, False, 0, 0, 0, wall, 0,
    )


def attempt(instance: dict, designer: str, seed: int, client, pin: dict, workdir: Path,
            prepare=prepare_workspace) -> tuple[dict | None, dict]:
    """One designer on one instance. Returns the schema row and the trace record.

    The row is None when the checkout or install fails: that is an environment
    failure, not a result for either designer.
    """
    started = time.monotonic()
    task_id = instance["instance_id"]
    card = swebench_card()
    try:
        workspace, python = prepare(instance, workdir)
    except (SetupError, subprocess.CalledProcessError, OSError) as error:
        detail = error.stderr.strip() if isinstance(error, subprocess.CalledProcessError) and error.stderr else str(error)
        # No model ran, so this is not a designer outcome. Return no row: the
        # failure is logged and a later run retries the instance.
        return None, {"task_id": task_id, "designer": designer, "seed": seed,
                      "setup_error": detail[-2000:], "wall_clock_s": round(time.monotonic() - started, 3)}

    task = {"task_id": task_id, "statement": instance["problem_statement"]}
    result = design(task, card, designer, seed, client=client)
    try:
        spec = executable_spec(result, task, card)
    except NotExecutable as error:
        wall = time.monotonic() - started
        row = _blank_row(
            task_id, designer, seed, pin, result["design_tokens"], result["rounds"],
            result["first_pass_valid"], wall,
        )
        return row, {
            "task_id": task_id, "designer": designer, "seed": seed,
            "design": result, "not_executable": {"reason": error.reason, "detail": error.detail},
        }

    hook = make_test_hook(instance, python)
    outcome = run_subagent(
        spec, card, workspace, seed, GeneratedTokenBudget(client), clock=SystemClock(),
        hook_runner=hook,
        resolved_check=lambda _workspace: run_with_test_patch(
            instance, python, workspace, FINAL_TEST_TIMEOUT,
        ).passed,
    )
    trace = outcome["trace"]
    wall = time.monotonic() - started
    row = schema_row(
        task_id, designer, seed, pin, result["design_tokens"], result["rounds"],
        result["first_pass_valid"], outcome["resolved"], bool(trace.silent_handoff),
        trace.budget_violations, trace.tool_denials,
        sum(1 for item in trace.hooks if not item.passed), wall, server_tokens(outcome["log"]),
    )
    return row, {
        "task_id": task_id, "designer": designer, "seed": seed,
        "design": result, "trace": trace.as_dict(), "log": outcome["log"],
    }


def load_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    import json
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError(f"{path} is not a result array")
    for row in rows:
        validate_result(row)
    return rows


def trace_path(trace_dir: Path, row: dict) -> Path:
    return trace_dir / f"{row['task_id']}__{row['designer']}__seed{row['seed']}.json"


def run_plan(instances: list[dict], designers: list[str], seeds: list[int], workdir: Path,
             output: Path, trace_dir: Path, pin: dict, client_factory,
             prepare=prepare_workspace) -> list[dict]:
    """Skip finished rows. Write the array and each trace atomically after every attempt."""
    rows = load_rows(output)
    done = {result_key(row) for row in rows}
    client = None
    for instance in instances:
        for designer in designers:
            for seed in seeds:
                key = ("swebench", instance["instance_id"], designer, seed)
                if key in done:
                    continue
                if client is None:
                    client = client_factory()
                row, record = attempt(instance, designer, seed, client, pin, workdir, prepare=prepare)
                if row is None:
                    name = f"{instance['instance_id']}__{designer}__seed{seed}__setup_failed.json"
                    write_json(trace_dir / name, record)
                    print(f"setup failed: {instance['instance_id']} {designer} seed {seed}", flush=True)
                    continue
                rows.append(row)
                done.add(result_key(row))
                write_json(output, rows)
                write_json(trace_path(trace_dir, row), record)
    return rows


def load_pin_for_run() -> dict:
    return load_pin()
