# Review of the original SWE-QA pilot

## What the twenty attempts establish

The frozen experiment is `sweqa-ad-v1`, tagged `sweqa-ad-seed1-v1`. All ten questions ran under both designers at seed 1. Ten D attempts have final boolean outcomes. Ten accepted A answers await external grades. The shared result array contains the ten finalized rows. Use the twenty traces for execution denominators. The audit and offline grading made zero inference calls.

| Seed-1 observation | A | D |
| --- | ---: | ---: |
| Accepted / attempted | 10/10 | 0/10 |
| Gate-silent / attempted | 0/10 | 0/10 |
| Gate-silent / accepted | 0/10 | Undefined (0/0) |
| Accepted answers with any repository-verified citation | 0/10 | N/A |
| Correct answers | Pending | 0/10 |
| Design (including repairs) | 0 | 31,839 |
| Subagent (including intercepted replies) | 6,026 | 31,107 |
| Total server tokens | 6,026 | 62,946 |
| Tokens per correct answer | Pending | Undefined |

All ten A answers returned on their first call without reading the repository. Each supplied citation syntax the gate accepted. None pointed to a verifiable file and line in the pinned source slice. This distinguishes three independent measurements: gate acceptance, source verification and semantic answer correctness. A reviewer may still credit a correct explanation.

For H2, D minus A was 0 percentage points across ten matched tasks, one seed, no unmatched observations. The 10,000-resample paired task bootstrap yields [0, 0] because every observed difference was zero. This sample cannot establish equivalent reliability, and D never faced the return gate. H2 compares D with B and C. Both comparisons are pending.

For H4, mean paired A minus D **subagent** cost per attempted task was (6,026 − 31,107)/10 = **−2,508.1 tokens**. Six invalid D designs contribute zero subagent tokens and their full design cost to the experiment. Even under that favorable accounting for marginal cost, no positive initial design cost can be recovered if this observed marginal difference persists. This calculation compares attempts with unequal outcomes. No successful matched pair identifies a quality-adjusted break-even, D's cost per correct answer is undefined, and the experiment recorded no cache hits. A causal estimate for reusing a particular validated spec on compatible held-out tasks remains unmeasured. [Recomputed metrics](../pilot/review/sweqa-ad-seed1-v1/metrics.md)

## Six design failures

Across six questions, eight unsupported pytest command strings survived all eight repair calls. Some appended a file and test selector; others appended a keyword filter. The final error was `command.unknown` at the relevant acceptance command field. Each loop stopped on an unchanged draft. The coordinator retains the question-level breakdown privately during grading.

The ten initial design prompts listed four exact IDs with their kinds: `ast.parse`, `lint.bare-except`, `pytest`, `unittest`. Each of eight repair calls repeated the schema, card, rules, previous spec and typed diagnostics, including the affected paths and the hint to use an exact command name. Only the bare `pytest` identifier selects the supported hook. Adding selectors or flags creates a different, unsupported string. The model repeatedly violated communicated constraints. The validator and repair feedback behaved as implemented.

Every D task statement explicitly described read-only QA, external assessment and empty verification hooks. The system still asked the orchestrator to design a coding harness with acceptance tests, and schema 0.1 requires a nonempty acceptance-test list. A named command in the goal is metadata. It cannot decide whether an explanation is accurate. All four structurally valid D specs selected `ast.parse`, set no hooks and demanded test output that the subagent could not obtain. The transcripts establish the emitted choices. They cannot establish the model's internal understanding of the task.

**Affan review.** The proposed prompt patch selects a QA-specific system message for the initial D call and every repair when the runner supplies `assessment=external_qa`. It keeps the coding prompts and all command, schema and repair rules intact. It cannot make external assessment expressible in 0.1. For a future protocol, agree a typed alternative for externally assessed goals (no shell command, no synthesized test output) and preserve the executable acceptance-test branch for coding tasks. Version that change, test both branches, and record its effects as a new treatment. The proposed prompt change has only been apply-checked. [Proposed patch](review/affan-external-qa.patch)

## Forty-eight intercepted actions

Twenty-four replies used `kind="read"` and 24 used `kind="read_file"`. Four runnable designs produced 12 intercepted actions each. The per-reply index remains with the frozen private evidence.

Each raw reply is valid JSON. The primary classification is **incorrect action name** for all 48. The wire format requires `kind="tool"` and the operation in `tool`. Thirty-six additionally omit required tool-call fields. None reached tool dispatch. The ledger's 48 tool denials include unknown actions by runtime convention, even though no access check denied a well-formed tool request. No observations support malformed JSON, a parser rejecting a legal action, an unsupported tool as the primary reason, context-window truncation, or another primary error. Input counts for these calls were 368–593, well below 16,384. The runner deliberately sends only the two most recent action/observation pairs. This history limit is distinct from server truncation. Each response has a SHA-256 and one-based index into its exact transcript.

Both conditions received the same historical system and action instructions. The question, goal, narrowed grants and return contract varied with the design. The shared examples included a root listing even when D omitted that tool (three tasks) or granted it only under `pytest` (one task). The return example omitted the test-output field. Unknown replies produced the uninformative observation `unknown action unparsed`. Thus the wrong discriminator is a real model output and the prompt supplied inconsistent examples. The available data cannot attribute the outcomes exclusively to either.

The historical loop received four further replies at zero remaining steps. Each used the correct return discriminator on call 13. The runtime intercepted all four before the gate. These 2,813 tokens belong in the original cost. No conclusion about hypothetical gate acceptance follows. Rechecking the four granted paths against the actual three pinned source archives found all four missing. The orchestrator received no repository tree or name inventory. Path authorization is lexical and does not imply path existence.

**Gaurav review.** The prospective shared preflight checks known step, token and monotonic wall limits before purchasing another reply. The step guard still intercepts an in-flight reply that exceeds a limit. A preflight stop has no attempted action and increments no violation counter. QA feedback now explains legal action kinds and renders examples from the assigned grants and return contract for both conditions. A separate regression exposed a runtime dispatch defect: a read-permission operation used the target's filesystem type to decide whether to list or read. This could make `list_dir` read a file or `read_file` list a directory. The fix enforces the named operation's target type. None of the 48 malformed calls reached this code. Review the shared changes before integrating the SWE-bench loop, including the earlier bounded line-range support, overflow handling and NUL-path rejection. No action alias or D-specific fallback was introduced.

## Fairness and reproducibility

| Control | Observed in v1 |
| --- | --- |
| Capability and source slice | Identical parent card for every run. Only read_file/list_dir with read at the repository root, 7–14B tier. The runtime has a filtered, read-only source workspace. A kept the parent grants, D could narrow them. No write, shell or repository test execution. |
| Runtime budgets | Same ceiling of 12 actions, 8,000 generated tokens and 900 s. All runnable D specs also selected exactly these limits. A received the same full limits. Input tokens and design time/cost did not debit these limits. |
| Experimental ledger | A had ten subagent calls. D had ten initial design calls (15,682 tokens), eight repair calls (16,157) and 52 subagent calls (31,107). Each server prompt and generation is counted, including all malformed replies. Ollama eval_count already includes generated reasoning. Reply.reasoning_tokens was zero on these calls. Replayed totals agree with every saved row. |
| Model | All rows and pin hashes agree with qwen2.5-coder:7b, Q4_K_M, digest `sha256:dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364`. The Ollama client checks the installed digest before inference. |
| Serving parameters | Ollama 0.34.0 locally versus 0.40.14 at pinning. The shared client constructs requests with num_ctx=16384, temperature=0.2 and seed=1 at both stages. All 80 transcript call entries record seed 1. Full raw HTTP option echoes and per-response server versions were not archived. |
| Revisions and visibility | Ten official source rows at three dataset-author pins, source-line IDs, verified gold paths and line bounds. Same repository/question for each pair. Gold answers and annotated ranges were available only to the external evaluator. Paths discovered in the allowed source or independently emitted by the model are possible. The design stage lacked the proposal's repository summary. |
| Study departures | Single host, one small model, one seed, ten purposive tasks per condition, fixed ordering, no pinned container recorded, human adaptation of a model judge pending. Evaluation excludes provisioning and grading time. Subagent receives the last two interactions. The experiment did not enforce the registered equal **combined** budget. |

### Prospective combined-budget policy for A–D

Before any corrected experiment, register one common per-task cap (proposal for review: 8,000 server tokens across both stages), 900 s of monotonic time starting at the initial design, and up to 12 runtime actions for every condition. Use the same pinned service, template, tokenizer, seed list and digest. A spends zero on design. B/C each spend their one call. D spends its initial call and any bounded repair calls. Charge each call's full input plus generated output once, including repeated context, repairs, malformed replies and intercepted actions. The remaining combined token allowance for execution is the initial cap minus actual design expenditure. A spec may narrow, but never enlarge, a common limit.

Implement admission before **every** model call, including design and repair: account for the exact serialized prompt using the pinned server tokenizer/template, reserve it, and cap generation with `num_predict` at the remaining tokens. Refuse inference if the prompt leaves insufficient room. Bound request time by remaining wall time. Reconcile actual counts after each call. A transport interruption with unknown consumption is an incomplete attempt requiring separate reporting. Test tokenizer agreement, deadline enforcement and unknown accounting before collecting data. Keep the identical parent ceiling, QA action instructions and evaluator across treatments. Record proposal approval, full server settings, per-call ledger, separate experiment ID and directories. The tagged experiment cannot be retrospectively made equal-budget. The prospective runner fixes alone do not implement this policy.

### B and C execution agreement needed

* **B**: use the emitted free-text brief verbatim as subagent instruction under the same read-only parent, wall/token/action ceilings, common action protocol and baseline summary return gate. One design call. No compilation of prose and no repair. Record non-applicability of compiled validity. The current design API returns null. Proposal for the required boolean wire field: reserve false solely as a serialization placeholder plus explicit applicability=false in diagnostics. Metrics already exclude B from this denominator. Require team agreement before producing B rows.
* **C**: use exactly the emitted instruction, context, tools and model from the original model response. Validate basic tuple types and authorize paths/tools/model against the parent before execution. Reject unrepresentable/unauthorized tuples with reason and actual design cost. No inferred fields, substituted model, extra design call or repair. Common execution ceilings and summary gate come from the adapter. Preserve the existing H3 structural first-pass check on the as-emitted tuple mapping and log tuple executability as a separate diagnostic. A failed full-HarnessSpec check does not itself determine whether a tuple can execute.
* **Integration**: agree the common minimal return behavior, restrictions for an invalid tuple, B wire convention and first-pass reporting with both owners. A shared parent-backed session adapter should enforce the same action parser/guards without treating a compiled B/C HarnessSpec as a model output. The existing `Session` constructor requires a valid full spec, so these semantics are still a proposal. Additional evidence requirements authored by D remain part of D. No B/C runs or additional seeds were collected.

### Energy

A one-second probe again found a RAPL package domain, with `PermissionError: [Errno 13] Permission denied: '/sys/class/powercap/intel-rapl:0/energy_uj'`. Neither `nvidia-smi` nor the Python `pynvml` module was present. No permission changes. All 20 original sidecars retain null CPU/GPU joules and Wh. Device energy and success/kWh are unavailable. On an inference host exposing readable package counters or a supported NVIDIA power interface, run the probe and supply a fresh experiment's energy directory when executing its approved protocol. The CPU method uses nonoverlapping package counters and handles wraparound. The GPU method integrates sampled device power by the trapezoid rule. Both are device-wide.

~~~bash
PYTHONPATH=src python3 -m harnessspec.energy --probe-seconds 1
# For a separately registered replication on a supported inference host
PYTHONPATH=src python3 pilot/run_sweqa.py --designers A D --seeds 1 \
  --energy-dir pilot/experiments/sweqa-ad-v2/energy
~~~

### Offline verification and integration

The first two commands require the private historical evidence bundle. Public verification commands are in the [release notes](PUBLICATION.md).

~~~bash
sha256sum --quiet -c pilot/snapshots/sweqa-ad-seed1-v1/SHA256SUMS
PYTHONPATH=src:. python3 -m pilot.audit_sweqa_v1 | cmp - pilot/review/sweqa-ad-seed1-v1/actions.tsv
PYTHONPATH=src python3 pilot/run_sweqa.py --dry-run --verify-sources
PYTHONPATH=src python3 -m unittest discover -s tests -v
git apply --check docs/review/affan-external-qa.patch
~~~

Gaurav can use the shared one-row Draft 2020-12 schema and standard-library `validate_result(row)` directly. Result files are JSON arrays. `read_results([path])` rejects duplicate identities. Record every attempted SWE-bench run including failures, actual server counts for both stages, and accepted-return status in a keyed diagnostic sidecar. Keep the fixture producer's `benchmark="fixture"` rows and its runtime-charged token counts out of the benchmark file. Affan owns the orchestrator patch decision and H3 analysis. The grade importer, archived evidence and metrics require neither teammate's changes. [Human grading workflow](../pilot/review/sweqa-ad-seed1-v1/REVIEW.md)
