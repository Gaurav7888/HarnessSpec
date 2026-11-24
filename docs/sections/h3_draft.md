# H3 — draft for the report (Affan)

Source: `pilot/h3_results.json` (summary and rows) and `pilot/h3_transcripts.json` (every reply). The model is `qwen2.5-coder:7b` at the pinned digest, temperature 0.2, and `num_ctx` 16384. This is a draft. Recheck the numbers if `run_h3.py` is re-run.

## Orchestrator and designers

All four designers sit behind one function, `design(task, card, designer, seed)`.

- **A** is the fixed generic harness and makes no model call.
- **B** asks the model for a prose brief. The brief is stored and not compiled.
- **C** asks for the four AOrchestra fields: instruction, context, tools, and model. They are placed into a HarnessSpec envelope as emitted and scored before any repair.
- **D** asks for a full HarnessSpec. The prompt contains the task, the parent card, the JSON Schema, and the compiler's rules. It contains no filled-in spec, because the model copied such an example almost verbatim in a smoke test.

When D's spec is invalid, each round first applies the deterministic compiler repair. The compiler may clamp privileges and budgets, strip unknown fields, and supply default stop rules, hooks, and return contracts. Any typed errors left are sent back to the model with an `allowed` hint read off the parent card. The loop runs for at most three rounds and stops early if the model returns the spec it was shown. The model, not the compiler, must write the goal, the acceptance tests, and the context slice.

## Result

On `fixtures/off_by_one` with seeds 1–3:

| Designer | First-pass valid | Valid at the end | Mean rounds | Mean design tokens |
| --- | --- | --- | --- | --- |
| C | 0/3 | 0/3 | 0 | 401 |
| D | 1/3 | 3/3 | 0.67 | 2,972 |

First-pass validity rose from 0 for C to 0.33 for D, so H3 is not falsified on this pilot.

- **C's errors:** every C reply lacked the fields the tuple does not carry (`schema.missing`) and a model tier (`model.tier`). Two of the three also gave a tool a path outside its grant (`tool.path`). The tuple carries one path list, and the same list is applied to every tool.
- **D's first-pass errors:** two D replies wrote a shell command, `python -m unittest ...`, where the protocol names a command, `unittest` (`command.unknown`). One of the two also filled `model.digest` with the placeholder `"..."` (`schema.format`). Both were cleared in one round.

The 15 hand-written corpus specs were also used as first drafts for D's repair loop at seed 1:

| | Valid |
| --- | --- |
| Before repair | 4/15 |
| After compiler repair alone (as in `pilot/results.json`) | 11/15 |
| After compiler repair plus the model | 14/15 |

- **What the model added:** the three extra specs are exactly the ones the compiler may not fix: a missing acceptance test, a context slice that escaped the workspace, and the four-field tuple. Each was cleared in one model round. That is the division of labour the protocol intends. The compiler clamps, and the orchestrator states the task.
- **Remaining failure:** `empty_goal`. The model wrote a correct goal but put the tool name `run_tests` where a hook command belongs. It repeated that after the hint, so the loop stopped as unchanged with `command.unknown` left.
- **Missing acceptance tests:** no remaining failure in any D row was a missing acceptance test.
- **Cost:** the corpus used 9,177 design tokens.

## Threats to validity

- **Sample size:** three seeds on one fixture is a pilot, not an estimate.
- **C's zero is structural:** the tuple carries no acceptance test, budgets, stop rule, verification, or return contract, so C cannot be valid under this validator. The C-to-D rise therefore partly restates the protocol, and the informative quantities are D's first-pass errors and the rounds D needs.
- **The prompt was changed after one look at output:** the first live D run spent three rounds on `command.unknown`. The `allowed` hint and the unchanged-reply stop were added before `pilot/h3_results.json` was generated. The prompt has been held fixed since. The hint is part of the D treatment, not of the validator.
- **Only one model tier:** H3 also claims the gain is largest for a 7–14B orchestrator. With one model in one tier, that part is not tested.
