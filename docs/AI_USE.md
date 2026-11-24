# AI tool log

The registered proposal commits to logging substantial AI-tool use: the tool, the task, and how the result was checked.

## 2026-11-05

- Tool: Cursor, Grok 4.7.
- Task: implement the midpoint of HarnessSpec (schema, validator, bounded repair, runtime, fixture pilot) and draft the four-page progress report.
- Check: `PYTHONPATH=src python3 -m unittest discover -s tests -v` and `PYTHONPATH=src python3 pilot/run_pilot.py`. The test suite re-runs the pilot and compares it to `pilot/results.json`.
- Not invoked: no orchestrator model, no subagent model, no SWE-bench task, no SWE-QA task.

## 2026-11-06

- Tool: Claude Code (Claude Opus 5.5).
- Task: port the Member 1 schema-and-validator starter (DineshThiraj) into this repository. Its per-rule tests were rewritten against `src/harnessspec/validator.py` as `tests/test_validator.py`, its rejected example became `examples/invalid_spec.json`, and its JSON verdict became the `--json` CLI option. The starter's own validator, schema, and `jsonschema` dependency were not copied, because this repository's validator already enforces every one of its rules.
- Check: `PYTHONPATH=src python3 -m unittest discover -s tests -v` (22 tests, including the pilot snapshot test, so `pilot/results.json` is unchanged).
- Not invoked: no orchestrator model, no subagent model.

## 2026-11-24

- Tool: Claude Code (Claude Opus 5.5).
- Task: Phase 0, pin the one model for the orchestrator and both subagents. Candidates were checked against the 7–14B tier and a 16 GB Apple M4. Qwen3.8-Flash-Next and GRIN-MoE were rejected as mixture-of-experts models far above the tier in total weights. Phi-4-reasoning was rejected because its thinking traces would inflate token counts. Nemotron-Mini-4B was rejected as below the tier. SenseNova Loop-9B and the Sakana 7B Conductor were rejected as not available on Ollama. `qwen2.5-coder:7b` (Q4_K_M, Ollama 0.40.14) was pinned in `pilot/model.json` with its full digest, `num_ctx` 16384, and temperature 0.2.
- Check: digest read from Ollama `/api/tags` and matches the validator's `sha256:<64 hex>` format. One smoke call (seed 1) asked the model for a HarnessSpec for `fixtures/off_by_one`. It returned parseable JSON in 27 s (677 prompt and 369 output tokens) that failed only `schema.missing task_id`, because the smoke prompt removed `task_id` from its example. This was a smoke test, not an H3 row. `PYTHONPATH=src python3 -m unittest discover -s tests -v` passes.
- Not invoked: no `design()`, no subagent, no SWE-bench or SWE-QA task.

## 2026-11-24 (orchestrator)

- Tool: Claude Code (Claude Opus 5.5).
- Task: Phase 1 for Affan. Added `src/harnessspec/llm.py` (the one Ollama client, with the digest check), `src/harnessspec/orchestrator.py` (`design()` for designers A–D), `src/harnessspec/h3.py` and `pilot/run_h3.py` (the H3 pilot), and tests that run against a scripted model.
- Prompt change made after seeing output: the first live D run on the fixture got stuck for three rounds on `command.unknown` (it wrote `python -m unittest ...` instead of `unittest`). Two changes followed. Each typed error sent back to the model now carries an `allowed` hint read off the parent card and the allowlist. The loop now stops when the model returns the spec it was shown. Both changes were made before `pilot/h3_results.json` was generated, and the prompt was not changed after it. The validator is unchanged.
- Check: `PYTHONPATH=src python3 -m unittest discover -s tests -v` (40 tests). `tests/test_h3.py` recomputes the summary from the committed rows. `pilot/results.json` is unchanged by a fresh `run_pilot.py`. Ollama reported the full prompt token count on repeated prefixes (1525 on three calls), so `design_tokens` is the sum of `prompt_eval_count` and `eval_count`.
- Model invoked: `qwen2.5-coder:7b` at the pinned digest, temperature 0.2, `num_ctx` 16384, seeds 1–3 on the fixture and seed 1 on the corpus.

## 2026-11-24 (subagent step)

- Tool: Cursor, Grok 4.7.
- Task: Gaurav's phase-1 slice. `Session.step` advances one action through the existing budget, tool-grant, hook, and return-gate checks. `run_trace` now calls that step, so the fixture pilot is unchanged. `pytest` is a named test command in the allowlist and in `hooks.py`, invoked as `python -m pytest` with no shell. `src/harnessspec/subagent.py` turns one model reply into one action and calls the model only through the shared client. `pilot/swebench_instances.json` lists ten SWE-bench Verified instances, one repository each, whose published FAIL_TO_PASS ids contain `::`.
- Check: `PYTHONPATH=src python3 -m unittest discover -s tests -v` (49 tests). The scripted subagent test patches `fixtures/off_by_one` under designer D and records a silent handoff under designer A. `pilot/results.json` still matches a fresh pilot run.
- Model invoked: `grok-4.7-low` through the Cursor CLI (`agent -p --mode ask --output-format json`), seed 1, designers A and D on a copy of `fixtures/off_by_one`. Ollama was not installed. The CLI reports no weight digest and no seed flag; the seed is written into the prompt and is not a sampler seed. `subagent_tokens` charges output tokens plus reasoning tokens. `server_input_tokens` is the CLI `inputTokens` figure, which includes the agent preamble, and is not charged against `max_tokens` because one preamble is larger than both harness caps. The harness clock advances by `duration_api_ms`. Rows are in `pilot/subagent_fixture.json`. On this seed both designers read `src/app.py`, wrote `return a + b`, and returned with a citation. Both resolved. A cited even though its contract does not require a citation, so this seed is not a silent handoff. D's unittest hook and `ast.parse` hook passed.
