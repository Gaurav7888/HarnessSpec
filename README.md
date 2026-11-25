# HarnessSpec

**Public review edition.** Candidate materials, run-level records and the frozen tag are held privately while independent grading is pending. For the artifact inventory and public reproduction commands, see the [release notes](docs/PUBLICATION.md).

Typed protocol for an orchestrator to design a subagent harness, and a compiler that checks the design before the subagent runs.

This repository includes the mid-submission snapshot for CS6.403 AutoSE, Monsoon 2026. The registered proposal is `docs/proposal.pdf` (21 October 2026). The four-page progress report is `docs/mid_submission_progress_report.pdf`. Its source is `docs/mid_submission.tex`.

Registered proposal author: Syed Affan Daimi, M.S. CS, IIIT Hyderabad.

## What is done

- HarnessSpec 0.1, eight fields: goal, context, tools, budgets, stop, verification, return contract, model. `schema/harnessspec.schema.json` is the interchange file. `src/harnessspec/validator.py` is the compiler.
- Bounded repair, at most three rounds. It clamps privileges and budgets, and it reduces an allowlisted command written with arguments (`pytest tests/x.py::t`, `python -m unittest ...`) to its name. It does not invent a goal, an acceptance test, or a context slice.
- A runtime that enforces step, token, and time budgets, tool allowlists, four in-process hooks, and the return gate. There is no shell. `Session.step` applies one action and returns the observation a live subagent is allowed to see. `run_trace` is that loop over a finished list.
- The subagent loop in `src/harnessspec/subagent.py`. `pilot/run_subagent.py` runs designer A (`fixed_generic_harness`) and designer D (`design()`) on `fixtures/off_by_one` with the pinned model through `OllamaClient`. The step budget charges generated tokens. `subagent_tokens` is the server's prompt plus output count, as in the SWE-QA runner. Rows are in `pilot/subagent_fixture_pinned.json`. The earlier Grok rows from the Cursor CLI, in `pilot/subagent_fixture.json`, are kept only as history, because the plan fixes one model for every role.
- A trace revision that may spend unused parent budget and will not drop a citation requirement.
- A fixture pilot on one buggy Python function and 15 hand-written specs. Numbers are in `pilot/results.json`.
- One pinned model for the orchestrator, `qwen2.5-coder:7b`, in `pilot/model.json`. `src/harnessspec/llm.py` is that client. It checks the local digest against the pin and passes `num_ctx`, `temperature`, and the run's seed on every call. The fixture subagent uses `src/harnessspec/cursor_cli.py` for the historical fixture run.
- The orchestrator: `design(task, card, designer, seed)` in `src/harnessspec/orchestrator.py`, for designers A–D. The H3 pilot is in `pilot/h3_results.json`, and every model reply is in `pilot/h3_transcripts.json`.

The SWE-QA pilot completed 20 real seed-1 attempts. Ten accepted A answers await independent grading. D had no accepted return. [Audit, grading materials and integration notes](docs/SWEQA_AUDIT.md)

## What is not done

The ten SWE-bench Verified instances are listed in `pilot/swebench_instances.json`. They have not been run. See [SWE-QA pilot and analysis](docs/SWEQA.md) for the pinned question manifest, read-only runner, external grading, shared benchmark records, and energy sidecars. Condition C in `pilot/results.json` is a structural check of a four-field tuple. The model-emitted C is in `pilot/h3_results.json`.

## Orchestrator interface

```python
from harnessspec.orchestrator import design
from harnessspec.parent import reference_parent

result = design({"task_id": "off_by_one", "statement": "..."}, reference_parent(), "D", seed=1)
result["spec"], result["design_tokens"], result["rounds"], result["first_pass_valid"]
```

- `task` is `{"task_id", "statement"}`. `card` is the parent `CapabilityCard`. `designer` is `"A"`, `"B"`, `"C"`, or `"D"`.
- `rounds` counts repair rounds after the first reply, so 0 means the first spec was valid. There are at most 3.
- `design_tokens` is prompt plus output tokens over all of the designer's model calls. It is 0 for A.
- The result also carries `valid`, `remaining_errors`, `missing_acceptance_test`, `model`, `model_digest`, `wall_clock_s`, and `log` (every reply).
- For D, check `result["valid"]` before running the spec. A spec that is still invalid after three rounds is a logged orchestrator failure, not something to run.
- To run any designer, call `harnessspec.execution.executable_spec(result, task, card)`. It returns the spec to pass to `Session`, or raises `NotExecutable` with a `reason` to record. A and D run their own spec only when valid. B runs A's harness with the brief as the goal. C runs A's harness with the tuple's instruction, context and tools, permissions from the card, and paths narrowed to each tool's grant.
- The orchestrator and every subagent call the model through `harnessspec.llm.OllamaClient`. `harnessspec.cursor_cli` is kept only for the historical Grok rows and is not used for results.
- H3 v2 is `pilot/h3_results_v2.json` and `pilot/h3_transcripts_v2.json`. It was run with the current allowlist, which includes `pytest`, and with command reduction. v1, `pilot/h3_results.json`, predates both. It is frozen in the SWE-QA snapshot manifest and kept unchanged.

## Subagent step

```python
from harnessspec.runtime import Session
from harnessspec.subagent import run_subagent
```

`Session.step(action)` returns an `Observation`: whether the action was applied, the refusal code, and the file text on a read. A read of a directory returns the names inside it. After the session has stopped, a later step is refused and does not consume budget.

`run_subagent(spec, parent, workspace, seed, client)` keeps calling `client.chat` until the session stops. With `SystemClock`, the model-call duration is already on the clock, so it is not added again as `action.seconds`. The fixture runner uses `SystemClock` with the pinned model. Its step budget charges generated tokens through `budget_tokens`. `resolved` is whether `unittest` passes on the workspace after the loop, including for designer A, whose harness does not run hooks.

## Reproduce

Python 3.10 or newer. No third-party packages.

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 pilot/run_pilot.py
PYTHONPATH=src python3 -m harnessspec examples/valid_spec.json examples/parent.json
PYTHONPATH=src python3 -m harnessspec --json examples/invalid_spec.json examples/parent.json
PYTHONPATH=src python3 pilot/run_h3.py         # H3 v2; needs Ollama and the pinned model, about 15 minutes
PYTHONPATH=src python3 pilot/run_subagent.py   # A and D on the fixture with the pinned model
```

The unit test reads `pilot/results.json` and fails if a fresh pilot run disagrees with it. `tests/test_validator.py` has one test per validator rule. The `--json` run is expected to exit with code 1 and list typed errors for `examples/invalid_spec.json`.

## Layout

| Path | Role |
| --- | --- |
| `schema/harnessspec.schema.json` | Protocol artifact |
| `src/harnessspec/` | Validator, repair, runtime, return gate, revision, subagent step |
| `examples/` | Parent capability card, one valid spec (harness D), one invalid spec |
| `tests/` | Protocol, repair, and pilot-snapshot tests; one test per validator rule |
| `fixtures/off_by_one/` | One function whose test fails until `src/app.py` is patched |
| `pilot/results.json` | Fixture measurements cited by the progress report |
| `pilot/swebench_instances.json` | Ten SWE-bench Verified instances, not yet run |
| `pilot/subagent_fixture_pinned.json` | A and D fixture rows from `pilot/run_subagent.py`, with the pinned model |
| `pilot/subagent_fixture.json` | Earlier Grok fixture rows, history only (frozen in the SWE-QA manifest) |
| `docs/AI_USE.md` | Tool log required by the proposal |
