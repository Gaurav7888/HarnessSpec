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
