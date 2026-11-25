# SWE-QA v2

The ten questions, dataset and repository revisions, parent permissions, pinned model and human rubric are shared across the four conditions. The corrected runner uses the QA design prompts, shared execution adapters and preflight checks on upstream main. Each identity consists of benchmark, task, designer and seed within one experiment. The same identity in v1 belongs to a different treatment.

A runs the fixed generic harness. B delegates the emitted brief verbatim. The required boolean `first_pass_valid` is false for B and compiled validity is inapplicable. C retains the structural score of the emitted tuple even when the adapter can execute it. D runs only its own validated design. A rejected design retains the adapter reason, detail, repair rounds and design ledger in its private trace. Its execution cost is zero.

The parent grants repository-root reads and directory listings, with limits of 12 actions, 8,000 generated tokens and 900 seconds for execution. A design may narrow those grants and limits. The experimental ledger counts every server prompt and generated reply once across both stages, including repairs, malformed actions and budget interceptions. Ollama includes generated reasoning in its output count. The common execution ceilings depart from the registered requirement for equal combined token budgets.

## Outcomes and comparisons

For v2, `silent_handoff` requires an accepted nonempty summary and zero `usable_repository_citations`. Each usable citation resolves inside the authorized source snapshot to a regular file and an existing 1-based line at the pinned revision. The original format-based gate decision remains in `diagnostics.format_silent_handoff`. The result schema is shared across protocols. Read the experiment identifier before interpreting that field. The separate v1 retrospective reopens the pinned archives and recalculates evidence while preserving the original gate scores. [Historical audit](SWEQA_AUDIT.md)

The primary H2 rate divides silent handoffs by all attempts. The conditional rate divides by accepted returns. Citation coverage divides accepted nonempty answers with at least one verified citation by accepted returns. The repository-grounded return rate uses the same numerator over all attempts. These measures establish file and line existence. Independent grades establish semantic accuracy.

D/B and D/C differences are percentage points. Pair task and seed, average repeated seeds within task, then resample whole tasks 10,000 times. For conditional rates, use the ratio of the task-averaged silent and acceptance indicators in each arm. Report the number of resamples with a defined denominator. With zero accepted returns the conditional rate is undefined.

H4 uses A minus D subagent tokens on matched attempts. A nonpositive marginal saving cannot recover a positive design cost. A positive difference across attempts with unequal outcomes does not identify a reusable specification. Quality-adjusted scenarios require successful matched tasks in a compatible repository, revision and question type. Reserve the priming task and use held-out tasks for the marginal saving. Each live identity designs afresh.

## Run and audit

Use a separate experiment directory for a replication. The coordinator's experiment lives under `pilot/experiments/sweqa-ad-v2/`. Keep the per-attempt files, energy records, result array and reviewer materials private. The public files contain the protocol and aggregate observations. The manifest selects source snapshots by commit. The dry run verifies every reference path and range.

~~~bash
export PYTHONPATH=src:.
run=pilot/experiments/sweqa-ad-v2
python3 pilot/run_sweqa.py --dry-run --verify-sources
python3 -m harnessspec.energy --probe-seconds 1
python3 pilot/run_sweqa.py --designers A D --seeds 1 --limit 1 --energy-dir "$run/energy"
python3 -m pilot.sweqa_metrics --output "$run/smoke_metrics.json"
python3 -m pilot.prepare_sweqa_review
python3 pilot/run_sweqa.py --designers A D --seeds 1 --resume --energy-dir "$run/energy"
python3 -m pilot.sweqa_metrics --output "$run/ad_seed1_metrics.json"
~~~

Use `--ollama-host` to select the pinned local service and `--archive-cache` to reuse verified archives. The live run verifies the model digest. Each batch uses a cumulative identity selection and skips completed traces. After auditing and committing A/D seed 1, extend the selection to A/B/C/D at seed 1, then seeds 1 and 2, then seeds 1, 2 and 3. Audit each batch before advancing. The runner atomically writes completed traces and rows and preserves interrupted call journals. The offline audit replays the adapter and both token ledgers, rechecks every candidate citation and reconciles finalized outcomes. Raw outputs are excluded from Git.

## Independent review

Run `python3 -m pilot.prepare_sweqa_review` after the last completed batch. Give an independent reviewer only the private `reviewer/` folder. It contains the packet, blank rubric, instructions and a provenance template. Ask reviewers to disclose prior exposure before grading. The coordinator retains the private mapping. Preserve each returned grade file and provenance record separately. On the cumulative selection, import adjudicated grades using `run_sweqa.py --grade-only --resume --grades FILE` with the corresponding designers, seeds and paths, then rerun the aggregate audit. Accepted answers remain pending until graded. Execution failures have final boolean rows without a human grade. [Reviewer rubric](../pilot/review/sweqa-ad-seed1-v1/REVIEW.md)
