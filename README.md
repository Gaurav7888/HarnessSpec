# HarnessSpec

Typed protocol for an orchestrator to design a subagent harness, and a compiler that checks the design before the subagent runs.

This repository is the mid-submission snapshot for CS6.403 AutoSE, Monsoon 2026. The registered proposal is `docs/proposal.pdf` (21 October 2026). The four-page progress report is `docs/mid_submission_progress_report.pdf`. Its source is `docs/mid_submission.tex`.

Registered proposal author: Syed Affan Daimi, M.S. CS, IIIT Hyderabad.

## What is done

- HarnessSpec 0.1, eight fields: goal, context, tools, budgets, stop, verification, return contract, model. `schema/harnessspec.schema.json` is the interchange file. `src/harnessspec/validator.py` is the compiler.
- Bounded repair, at most three rounds. It clamps privileges and budgets. It does not invent a goal, an acceptance test, or a context slice.
- A runtime that enforces step, token, and time budgets, tool allowlists, three in-process hooks, and the return gate. There is no shell.
- A trace revision that may spend unused parent budget and will not drop a citation requirement.
- A fixture pilot on one buggy Python function and 15 hand-written specs. Numbers are in `pilot/results.json`.
- One pinned model for every role, `qwen2.5-coder:7b`, in `pilot/model.json`. `src/harnessspec/llm.py` is the only client. It checks the local digest against the pin and passes `num_ctx`, `temperature`, and the run's seed on every call.
- The orchestrator: `design(task, card, designer, seed)` in `src/harnessspec/orchestrator.py`, for designers A–D. The H3 pilot is in `pilot/h3_results.json`, and every model reply is in `pilot/h3_transcripts.json`.

## What is not done

There is no SWE-bench Verified run, no SWE-QA run, no energy measurement, and no test of H1, H2, or H4. Condition C in `pilot/results.json` is a structural check of a four-field tuple. The model-emitted C is in `pilot/h3_results.json`.

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
- Subagents should call the model through `harnessspec.llm.OllamaClient`, so all three roles use the same pin.

## Reproduce

Python 3.10 or newer. No third-party packages.

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 pilot/run_pilot.py
PYTHONPATH=src python3 -m harnessspec examples/valid_spec.json examples/parent.json
PYTHONPATH=src python3 -m harnessspec --json examples/invalid_spec.json examples/parent.json
PYTHONPATH=src python3 pilot/run_h3.py   # needs Ollama and the pinned model, about 15 minutes
```

The unit test reads `pilot/results.json` and fails if a fresh pilot run disagrees with it. `tests/test_validator.py` has one test per validator rule. The `--json` run is expected to exit with code 1 and list typed errors for `examples/invalid_spec.json`.

## Layout

| Path | Role |
| --- | --- |
| `schema/harnessspec.schema.json` | Protocol artifact |
| `src/harnessspec/` | Validator, repair, runtime, return gate, revision |
| `examples/` | Parent capability card, one valid spec (harness D), one invalid spec |
| `tests/` | Protocol, repair, and pilot-snapshot tests; one test per validator rule |
| `fixtures/off_by_one/` | One function whose test fails until `src/app.py` is patched |
| `pilot/results.json` | Fixture measurements cited by the progress report |
| `docs/AI_USE.md` | Tool log required by the proposal |
