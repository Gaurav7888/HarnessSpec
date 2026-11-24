# SWE-QA pilot and shared result contract

**Public review edition.** Candidate materials, run-level records and the frozen tag are held privately while independent grading is pending. For the artifact inventory and public reproduction commands, see the [release notes](PUBLICATION.md).

The original twenty attempts are frozen at tag `sweqa-ad-seed1-v1`. The failure audit, reviewer packet, prospective budget policy and owner integration notes are in the [phase-2 audit](SWEQA_AUDIT.md).

## Dataset and selection

The registered proposal cites Oskooei et al., [Deep Agentic Search for
Repository-Level Code Question Answering](https://arxiv.org/abs/2608.01507).
That study uses Peng et al.'s [SWE-QA](https://aclanthology.org/2026.findings-acl.402/).
The [authors' Git release](https://github.com/peng-weihan/SWE-QA-Bench/tree/c13deac7a0d99b0ca2e593e004c4739475785b08)
is the source of the question and reference-answer text. The corresponding
dataset is [swe-qa/SWE-QA-Benchmark](https://huggingface.co/datasets/swe-qa/SWE-QA-Benchmark).
The source release uses [Apache 2.0](licenses/SWE-QA-Bench.txt).

The pilot is a deliberately small, purposive sample of the original Python
repositories. Flask, Requests, and pytest have compact source snapshots and
different application domains. The selection covers what, how, why, and
where questions with repository-specific answers, including serialization,
logging, configuration, and test fixtures. The pinned selector preserves
the reviewed source rows in manifest order.

| Project | One-based JSONL lines | Published commit prefix |
| --- | --- | --- |
| Flask | 1, 17, 35, 43 | `85c5d93` |
| Requests | 30, 48 | `46e939b` |
| pytest | 18, 24, 34, 44 | `5989efe` |

The release contains `question` and `answer` without a row ID or structured
evidence columns. `question_id` is the project and one-based line in the
pinned source, and `source` points to that exact row. `gold_files` and
`gold_evidence` extract repository paths and unambiguously attached line
ranges from the published reference prose. The original prose retains
other line mentions. Each extracted path exists and each extracted range
is within the referenced file at the authors' pinned revision. This check
does not assert semantic validity of every published citation or reference.
Full commit IDs are validated against GitHub archives' commit metadata and
against the prefixes in upstream `repo_commit.txt`.

```bash
git clone https://github.com/peng-weihan/SWE-QA-Bench.git /tmp/sweqa-official
PYTHONPATH=src python3 pilot/select_sweqa.py /tmp/sweqa-official --output pilot/tmp/verified_manifest.json
cmp pilot/sweqa_instances.json pilot/tmp/verified_manifest.json
PYTHONPATH=src python3 pilot/run_sweqa.py --dry-run --verify-sources
```

## Execution

Use Python 3.10+ on a POSIX host, Git for manifest reproduction, and Ollama
with the model in `pilot/model.json`. The runner checks the server's digest
before inference. Use the same checkout, manifest, model options, and
Ollama version for all conditions. The current runner defaults to A and D
at seed 1, with 20 planned attempts in a new directory under
`pilot/experiments/sweqa-ad-v2/`. The following execution command is for
a separately approved replication. The equal combined-budget proposal
still requires implementation and agreement.

```bash
ollama pull qwen2.5-coder:7b
PYTHONPATH=src python3 pilot/run_sweqa.py --designers A D --seeds 1 \
  --energy-dir pilot/experiments/sweqa-ad-v2/energy
# Append --resume to the same command after an interruption.
```

`--instances`, `--designers`, `--seeds`, `--limit`, `--output`,
`--trace-dir`, and `--archive-cache` control the inputs and destinations.
`--dry-run` lists the plan and needs no Ollama. Add `--verify-sources` to
check the archives and evidence offline if archives are already cached.
Benchmark execution sets up immutable-in-practice source slices from
regular tracked files with selected text extensions and no dotfiles,
symlinks, binary assets, untracked files, or Git metadata. A and D share a
parent ceiling of 12 steps, 8,000 generated tokens, 900 seconds and the
7–14B model tier. A uses the fixed generic harness through `design`.
D chooses its own limits within that ceiling and uses the original bounded
repair. Its invalid designs end the attempt with the actual design cost
and compiler diagnostics. Only `read_file` and `list_dir` are granted
on the source slice. The SWE-QA hook adapter refuses test hooks at runtime
and records a hook failure. Read-only AST and lint hooks can run. The
schema's mandatory named goal acceptance test remains metadata. No
fixture unittest resolution check runs.

The orchestrator receives the question and capability card. The subagent
receives the question, goal, context scope, tool grants and budget, and
the latest two action/observation pairs. A read may request up to 200
numbered lines at a time so long files remain navigable beyond the
runtime's output cap. Reference answers, evidence annotations, and
grading data are external to both prompts. A source file can still be
discovered by reading the permitted repository.

The Ollama client exposes `prompt_eval_count` and `eval_count`
(includes generated reasoning, if present) through `Reply`. Each scored
attempt counts all reported prompt and output tokens, including repair
calls, malformed replies, and replies intercepted after a budget check.
The step budget charges generated tokens only. The parent ceiling applies
to subagent execution and does not reserve or enforce an equal combined
design-plus-execution cap. This is a pilot departure from the registered
equal-total-budget study. Repository preparation and human grading sit
outside the reported run wall clock. Run duration includes design and
execution. Checkpoints preserve transport errors and known replies.
Missing server counts for an interrupted call cannot be recovered, so
transport-aborted executions are recorded separately and retried on
resume. They do not become completed benchmark rows. Report interruptions
when reporting the pilot.

One JSON trace per run preserves the parent card, emitted spec and repair
log, exact model messages and replies, charged versus server counts,
runtime events, returned answer, and evaluation diagnostics. Writes are
atomic and resume checks trace identity, protocol, manifest row and model
pin. Preserve the trace directory together with the matching result file.
An interruption after saving a completed trace can be recovered even if
the result file was never written.

## External answer evaluation

The [published evaluation](https://arxiv.org/html/2608.01507v1#A4)
combines five scores of 0–10 for correctness, completeness, relevance,
clarity, and reasoning. It doubles their sum, using Pass at 70 or above,
Partial at 50–69, and Fail below 50. The original study uses an external
Claude judge, and the benchmark author's [reference scorer](https://github.com/peng-weihan/SWE-QA-Bench/blob/c13deac7a0d99b0ca2e593e004c4739475785b08/Benchmark%20construction/score/llm-as-a-judge.py)
uses GPT-5. This pilot uses a human application of the cited study's
rubric. Scores are not directly comparable across judge implementations.

Reviewers receive a deterministic grading packet with a question,
reference, candidate, citations and opaque ID. They do not receive
condition, seed, costs, design or runtime traces. Rate technical accuracy,
coverage of the question, topical focus, readability, and sound
code-grounded reasoning separately. Inspect cited source at the pinned
revision when checking disputed details. Record a consensus score with
rationale per answer before unblinding. Supply a JSON object mapping each
`grading_id` to integer fields `correctness`, `completeness`,
`relevance`, `clarity`, `reasoning` and a non-empty `rationale`.
Preserve reviewer provenance and the grade file with published artifacts.

```bash
review=pilot/review/sweqa-ad-seed1-v1
PYTHONPATH=src python3 pilot/run_sweqa.py --resume --grade-only \
  --trace-dir pilot/traces/sweqa --grades pilot/tmp/independent_grades.json \
  --output pilot/analysis/graded-v1/results.json \
  --grading-packet pilot/analysis/graded-v1/packet.json
cmp "$review/packet.json" pilot/analysis/graded-v1/packet.json
```

Supply the [review instructions](../pilot/review/sweqa-ad-seed1-v1/REVIEW.md),
packet and blank template only to the reviewer. The coordinator stores the
returned grades and provenance before import. A fresh output with a complete
review should contain 20 unique rows. Omitting `--grades` from the command
in a fresh output directory reproduces the ten finalized D rows and packet
without inference. Duplicate IDs, unknown IDs, blank rationales and invalid
scores abort import. A completed
attempt with an accepted, non-empty answer awaits a grade before receiving a
boolean `resolved` in the derived result file. Invalid designs,
rejections, timeouts at the step gate, and empty responses are unresolved.
Accepted answers pass only at 70 or above. Gold-file overlap and same-file
gold-line range overlap are separate evidence diagnostics. An answer can
be incorrect while carrying a correct path. A pending grade is neither a
correct nor an incorrect answer. Run accuracy, H1 token-per-correct, and
H4 analyses only after the designated pilot rows have all been finalized.

## Observed seed-1 pilot

The pinned model completed all 20 A/D executions on the development host.
A accepted 10/10 returns. D accepted 0/10. Six D designs remained invalid
after repair because of unknown acceptance commands. The other four D
designs were first-pass valid and exhausted their runtime step budgets
after 48 total unrecognized actions. A consumed 6,026 tokens. D consumed
62,946 tokens, of which 31,839 were design and 31,107 subagent tokens.
Both conditions had zero silent handoffs. D had no accepted returns, so
its accepted-return rate of silent handoffs is undefined. H2 comparisons
with B and C and any H4 cache-reuse conclusion remain pending.

The 10 unresolved D attempts already have boolean outcomes.
All ten accepted A answers await independent review in the grading
packet. All 20 traces and all 20 energy sidecars are available. CPU
and GPU energy are unavailable in every sidecar.

## Shared records and analysis

`pilot/result.schema.json` is Draft 2020-12 for one benchmark row.
Result files contain arrays of rows. The standard-library helper
`harnessspec.results.validate_result` enforces the contract, including
integer JSON encoding for counters and finite wall clocks.
`harnessspec.results.read_results` rejects duplicates across input files
using `(benchmark, task_id, designer, seed)`. Model pins must agree within
each benchmark input. Leave legacy `pilot/results.json` and
`pilot/h3_results.json` outside this aggregation.

For A, `first_pass_valid` is the actual compiler check on the fixed spec.
For C it is the compiler check on the unmodified tuple representation, a
structural comparison with full HarnessSpec. B has no semantic first-pass
validity. The existing B designer returns `None`, while the shared wire
field is required and boolean. B execution is pending a transparent
adapter and a team-agreed wire placeholder. Metrics exclude B from the
validity denominator and report N/A regardless of the placeholder. They
accept future correctly shaped B/C execution rows.

Supplementary diagnostics are arrays or directories of JSON records keyed
by the same four fields. Each entry may contain a `diagnostics` object.
For H2, record a boolean `return_accepted` for each attempt, with false
when there was no accepted return. H2 uses attempted runs as the primary
denominator. Its supplementary denominator is accepted returns, reported
only with complete diagnostic coverage, and its conditioned rate is
undefined when none were accepted. The runtime marks a silent handoff
when an accepted nonempty summary lacks structurally usable file-line
citations. The external evidence check additionally verifies actual path and
line existence. The A/D contrast is preliminary. H2 requires D/B and D/C
contrasts, with the original free text and tuple conditions intact.

```bash
PYTHONPATH=src python3 pilot/metrics.py pilot/sweqa_results.json \
  --diagnostics pilot/traces/sweqa --energy pilot/traces/sweqa-energy \
  --sweqa-executions pilot/traces/sweqa
# Add pilot/swebench_results.json as another positional input once available.
```

The staged output contains the scored D condition and a separate A/D
execution-only section. After independent grading, rerun the command
using `pilot/analysis/graded-v1/results.json` as the sole SWE-QA result
input to include scored A rows in the paired answer and cost analysis.
Default metrics destinations are now under `pilot/analysis/`.

Each benchmark/designer table divides resolved, silent handoffs and
applicable first-pass validations by attempts. Mean costs, rounds, and
wall time use all attempted runs. Tokens per correct is combined design
and subagent tokens across all attempts divided by the number resolved.
A zero denominator yields JSON null. The paired estimate computes D minus
baseline on matching benchmark/task/seed pairs, averages the matched
seeds inside each task, and weights tasks equally. The percentile 95%
interval uses 10,000 bootstrap resamples of whole tasks (seed 20261124),
holding the within-task seed pairs together. JSON reports observed matched
seeds and unmatched run counts. Fewer than two matched tasks yield no
interval. An interval from one seed per task does not cover seed-to-seed
variation. Shared repositories and purposive task selection further
limit generalization.

Before grades are available, `--sweqa-executions pilot/traces/sweqa`
can generate a separate execution-only section with handoffs and token
counts for all complete executions. It omits accuracy and amortization.

The offline unit suite exercises the metrics on manually checked synthetic
records. To smoke-test the CLI without touching benchmark outputs:

```bash
PYTHONPATH=src:tests python3 - <<'PYTHON'
from pathlib import Path
from harnessspec.results import write_json
from test_results import row
write_json(Path("pilot/tmp/synthetic_sweqa.json"), [
    row(designer="A", resolved=True),
    row(designer="D", design_tokens=5),
])
PYTHON
PYTHONPATH=src python3 pilot/metrics.py pilot/tmp/synthetic_sweqa.json \
  --json-output pilot/tmp/synthetic_metrics.json \
  --markdown-output pilot/tmp/synthetic_metrics.md
```

### H4 cache scenario

The baseline is A. Each hypothetical group contains the same repository
commit and question type. Diagnostics carry `reuse_group`,
`design_tokens_measured`, and `design_valid`. The first sorted successful
pair in a group with positive measured D design cost is the priming run.
Estimate savings from other matched tasks where both designs resolved the
question, averaging repeated seeds within a task. This estimates costs at
matched correctness. Missing measurements or no held-out success pairs
yield undefined break-even. Zero or negative savings with measured
positive cost yield no finite break-even. Otherwise use the ceiling of
priming design tokens divided by per-task subagent savings. This assumes
a compatible reusable spec, negligible lookup/rebinding overhead, and
unchanged success and subagent cost after rebinding.

The existing `SpecCache` keys by task type and model tier and returns
the original task-bound spec. An empirical reuse treatment needs a
repository/revision and capability/model identity in its key, plus
validated rebinding of task ID and goal. The primary A/D pilot does not
use the cache. No observed cache reuse is attributed to the hypothetical
estimate.

### CPU and GPU energy

```bash
PYTHONPATH=src python3 -m harnessspec.energy --probe-seconds 1
```

Energy sidecars contain the keyed `energy` object and are optional.
RAPL samples only top-level CPU package domains from one controller
family, so subdomains and duplicate MMIO measurements are excluded.
Samples default to one-second spacing and handle one wrap per interval.
Counter resets and undiscovered multiple wraps can confound the estimate.
NVIDIA GPU power from `nvidia-smi` is sampled in watts and integrated by
the trapezoid rule. It is an estimated GPU energy value. A sample failure
marks the affected measurement unavailable. The scope is device-wide,
including other work and sampling overhead, and omits other hardware
domains. Use the utility on the Ollama host to include inference energy.
Conversions are 3,600 J/Wh and 3,600,000 J/kWh. Efficiency counts
successes and total energy over the same measured runs, stratified by
source, method and device inventory. Report measurement coverage.

The development host exposed Intel RAPL package domains, but reading
`/sys/class/powercap/intel-rapl:0/energy_uj` returned permission denied.
`nvidia-smi` and `pynvml` were absent. The hardware probe reported
unavailable and null for both sources.
