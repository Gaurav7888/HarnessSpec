# AI tool log

**Public review edition.** Candidate materials, run-level records and the frozen tag are held privately while independent grading is pending. For the artifact inventory and public reproduction commands, see the [release notes](PUBLICATION.md).

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

## 2026-11-24 (SWE-QA and benchmark integration)

- OpenAI Codex implemented Dinesh's shared benchmark contract, official SWE-QA
  ingestion and ten-task manifest, read-only A/D runner, grading workflow,
  clustered bootstrap metrics, H2 and H4 analysis, energy logging, tests,
  reproducibility notes, and ACM report skeleton. The prompt specified ownership
  boundaries, the registered hypotheses, reproducible data provenance, and
  preservation of negative and unavailable results.
- The work started from clean upstream main
  `45e2332ade7912ab41833f6e5cfe1a8b14641441` on
  `dinesh/sweqa-metrics-report`. It added `pilot/{result.schema.json,select_sweqa.py,sweqa_instances.json,run_sweqa.py,metrics.py}`,
  `src/harnessspec/{results,sweqa,energy}.py`,
  `tests/test_{results,sweqa,benchmark_metrics,energy}.py`,
  `docs/{SWEQA.md,final_report.tex,licenses/SWE-QA-Bench.txt}`.
  It updated this log, `README.md`, `.gitignore`, and the shared runtime,
  path guard and model-action parser. Optional line ranges expose source
  beyond the original 12,000-character read limit. The optional hook
  runner refuses repository execution in SWE-QA while keeping the default
  hook behavior for existing callers.
- The baseline `PYTHONPATH=src python3 -m unittest discover -s tests -v`
  passed 49 tests. The same command passed 78 after changes.
  `PYTHONPATH=src python3 pilot/run_pilot.py` reproduced the committed
  fixture snapshot byte for byte. The valid and invalid examples exited
  0 and 1 respectively. `git diff --check` passed.
- `PYTHONPATH=src python3 pilot/select_sweqa.py /tmp/harnessspec-sweqa-source --archive-cache /tmp/harnessspec-sweqa-targets`
  verified ten genuine released questions and their extracted gold paths
  and line bounds across three pinned repository archives. A second
  manifest write compared byte for byte. The release has no official
  question ID field, so the manifest uses source-line IDs.
  `PYTHONPATH=src python3 pilot/run_sweqa.py --dry-run --verify-sources --archive-cache /tmp/harnessspec-sweqa-targets`
  planned 20 executions. Tests mocked model replies and energy counters.
  The metrics CLI smoke test used two synthetic files in `pilot/tmp/`
  and checked both four-run-per-condition aggregates and the paired
  intervals. Neither the fixture run nor the mocks are benchmark evidence.
- The hardware probe
  `PYTHONPATH=src python3 -m harnessspec.energy --probe-seconds 0.1`
  found Intel RAPL package domains under `/sys/class/powercap/`, but
  failed to read `intel-rapl:0/energy_uj` with permission denied.
  `nvidia-smi` and `pynvml` were absent. Both energy readings were null.
- The initial Ollama preflight exited 1 with
  `RuntimeError: qwen2.5-coder:7b is not pulled; run: ollama pull qwen2.5-coder:7b`.
  The registry manifest advertised the digest in `pilot/model.json`.
  This host served Ollama 0.34.0, while the pin records 0.40.14 as the
  original model pinning environment. Documentation defines the human
  adaptation of the published rubric, the single-seed pilot ceiling,
  and the pending B/C adapters and empirical cache-reuse experiment.
- The registry pull completed and the installed digest passed the existing
  Ollama client check. The real command was
  `PYTHONPATH=src python3 pilot/run_sweqa.py --designers A D --seeds 1 --archive-cache /tmp/harnessspec-sweqa-targets --energy-dir pilot/traces/sweqa-energy --resume`.
  All 20 live executions completed on CPU. A accepted 10 answers for
  external grading. D finalized 10 unresolved attempts, including six
  invalid designs and four step-budget stops after unrecognized actions.
  Both had zero silent handoffs. The artifact audit confirmed all 20
  run identities and energy sidecars, the pin in every run, server token
  totals against each transcript, and the absence of subagent calls for
  invalid designs. CPU and GPU energy were unavailable in all runs.
- The real `--resume --grade-only` check reproduced the exact result
  bytes and generated the blinded ten-answer packet without inference.
  `PYTHONPATH=src python3 pilot/metrics.py pilot/sweqa_results.json --diagnostics pilot/traces/sweqa --energy pilot/traces/sweqa-energy --sweqa-executions pilot/traces/sweqa`
  generated the real D scoring summary and separate full A/D execution
  metrics. A accuracy awaits human scores. D resolved no attempts, so
  this pilot has no successful pair for H4. No B/C execution or
  additional seeds were run.
- Tectonic 0.17.0 compiled the final ACM report with
  `tectonic -b https://data1b.fullyjustified.net/tlextras-2022.0r0.tar --outdir /tmp/harnessspec-tex docs/final_report.tex`.
  `pdfinfo` confirmed two pages and text extraction confirmed the actual
  pilot outcomes appear in the report. The generated PDF is available
  locally at `pilot/tmp/final_report.pdf`.

## 2026-11-24 (Phase 2 pilot audit, IST)

OpenAI Codex audited Dinesh's local work at the user's request. The prompt asked for an immutable pilot snapshot, root-cause analysis of the six design failures and 48 intercepted actions, a fairness and grading review, owner integration notes, energy checks, a revised report, regression tests and local commits. The audit started on the existing feature branch at `45e2332`. A fresh fetch still placed upstream main there. The original 78-test suite passed. No new benchmark inference, external reviewer submission, public posting, push or merge occurred during this phase.

* Preserved all original data before editing. Recorded SHA-256 for 54 files, including the 20 transcripts/traces and 20 energy sidecars. The frozen tag is `sweqa-ad-seed1-v1`. Copies of the original blind packet and live execution log are under `pilot/snapshots/sweqa-ad-seed1-v1/`. Both the pre-edit and committed checksum lists passed after the audit.
* Compared all raw model replies, prompts, typed repair feedback, source revisions, token and acceptance records. Added `pilot/audit_sweqa_v1.py`, the per-action TSV, review metrics JSON/Markdown and reviewer packet/instructions/template in `pilot/review/sweqa-ad-seed1-v1/`. The ledger contains 80 real calls, including eight repairs and four post-exhaustion returns, all from the original experiment. The audit classifications and descriptive costs are derived from these calls. No audit classification is a human answer grade.
* Changed `src/harnessspec/runtime.py`, `src/harnessspec/subagent.py`, `src/harnessspec/results.py`, `pilot/run_sweqa.py`, `pilot/select_sweqa.py`, `pilot/metrics.py` and `.gitignore` for prospective budget checks, read-operation dispatch, grant-aware prompts, snapshot-safe outputs, validated offline grading and separate marginal-cost/acceptance reporting. Added regression coverage in `tests/test_step.py`, `tests/test_sweqa.py` and `tests/test_benchmark_metrics.py`. Those tests use synthetic replies, grades and counters.
* Updated `README.md`, `docs/SWEQA.md`, `docs/SWEQA_AUDIT.md` and `docs/final_report.tex`. Prepared `docs/review/affan-external-qa.patch` for owner review. `git apply --check docs/review/affan-external-qa.patch` passed. The production orchestrator and validator were untouched. Reviewed the cited [published rubric](https://arxiv.org/html/2608.01507v1#A4) and the [benchmark authors' released scorer](https://github.com/peng-weihan/SWE-QA-Bench/blob/c13deac7a0d99b0ca2e593e004c4739475785b08/Benchmark%20construction/score/llm-as-a-judge.py) for evaluation provenance.
* `PYTHONPATH=src python3 -m unittest discover -s tests -v` passed all **87** tests. `PYTHONPATH=src python3 pilot/run_pilot.py` in a disposable copy reproduced all 7,552 original fixture bytes. `PYTHONPATH=src:. python3 -m pilot.audit_sweqa_v1 | cmp - pilot/review/sweqa-ad-seed1-v1/actions.tsv` passed. `sha256sum --quiet -c pilot/snapshots/sweqa-ad-seed1-v1/SHA256SUMS` passed.
* `PYTHONPATH=src python3 pilot/select_sweqa.py /tmp/harnessspec-sweqa-source --archive-cache /tmp/harnessspec-sweqa-targets --output pilot/tmp/phase2-verified-manifest.json` verified ten rows from the official release and matched the frozen manifest bytes. `PYTHONPATH=src python3 pilot/run_sweqa.py --dry-run --verify-sources --archive-cache /tmp/harnessspec-sweqa-targets` planned twenty paired runs. All four runnable D grants were absent from their pinned snapshots. The installed model digest passed the shared client's preflight and the version endpoint reported 0.34.0 (pinning environment 0.40.14).
* `PYTHONPATH=src python3 pilot/run_sweqa.py --resume --grade-only --trace-dir pilot/traces/sweqa --output pilot/tmp/phase2-grade-preview/results.json --grading-packet pilot/tmp/phase2-grade-preview/packet.json` read 20 traces, finalized ten D rows and left ten A answers pending. Compared output bytes against the frozen result array and the new blinded packet. Compared the ten original anonymous IDs, candidate answers, questions and reference text with the expanded packet. No independent grades were available.
* `PYTHONPATH=src python3 pilot/metrics.py pilot/sweqa_results.json --diagnostics pilot/traces/sweqa --energy pilot/traces/sweqa-energy --sweqa-executions pilot/traces/sweqa --json-output pilot/tmp/phase2-verified-metrics.json --markdown-output pilot/tmp/phase2-verified-metrics.md` reproduced both review summaries byte for byte. A separate smoke test used only synthetic inputs: `PYTHONPATH=src python3 pilot/metrics.py pilot/tmp/synthetic_swebench.json pilot/tmp/synthetic_sweqa.json --json-output pilot/tmp/phase2-synthetic-metrics.json --markdown-output pilot/tmp/phase2-synthetic-metrics.md`.
* `PYTHONPATH=src python3 -m harnessspec.energy --probe-seconds 1` reported permission denied reading `/sys/class/powercap/intel-rapl:0/energy_uj`, missing `nvidia-smi`, and null CPU and GPU joules. Python module lookup found no `pynvml`. No permissions were changed. No human accuracy, cache hits, successful D costs, B/C comparisons, additional seeds, equal-combined-budget replication or energy efficiencies were measured.
* Tectonic compiled `docs/final_report.tex` with `tectonic -b https://data1b.fullyjustified.net/tlextras-2022.0r0.tar --outdir pilot/tmp/phase2-report docs/final_report.tex`. Font and underfull-box warnings were nonfatal. `pdfinfo` reported three pages. Extracted text contains the failure counts, token figures, server deviation and unavailable energy. The compiled PDF and build intermediates are local.
