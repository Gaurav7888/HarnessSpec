# H3 — draft for the report (Affan)

Sources:
- **v2, the result to report:** `pilot/h3_results_v2.json` and `pilot/h3_transcripts_v2.json`.
- **v1, history only:** `pilot/h3_results.json` and `pilot/h3_transcripts.json`. v1 is frozen in the SWE-QA snapshot manifest.

The model is `qwen2.5-coder:7b` at the pinned digest, temperature 0.2, and `num_ctx` 16384. This is a draft. Recheck the numbers if `run_h3.py` is re-run.

## Orchestrator and designers

All four designers sit behind one function, `design(task, card, designer, seed)`.

- **A** is the fixed generic harness and makes no model call.
- **B** asks the model for a prose brief. The brief is stored and not compiled.
- **C** asks for the four AOrchestra fields: instruction, context, tools, and model. They are placed into a HarnessSpec envelope as emitted and scored before any repair.
- **D** asks for a full HarnessSpec. The prompt contains the task, the parent card, the JSON Schema, and the compiler's rules. It contains no filled-in spec, because the model copied such an example almost verbatim in a smoke test.

When D's spec is invalid, each round first applies the deterministic compiler repair. The compiler may do the following:

- clamp privileges and budgets
- strip unknown fields
- supply default stop rules, hooks, and return contracts
- reduce an allowlisted command written with arguments to its name, from v2 on

Any typed errors left are sent back to the model with an `allowed` hint read off the parent card. The loop runs for at most three rounds and stops early if the model returns the spec it was shown. The model, not the compiler, must write the goal, the acceptance tests, and the context slice.

## Result (v2)

On `fixtures/off_by_one` with seeds 1–3:

| Designer | First-pass valid | Valid at the end | Mean rounds | Model calls | Mean design tokens |
| --- | --- | --- | --- | --- | --- |
| C | 0/3 | 0/3 | 0 | 1 | 402 |
| D | 0/3 | 3/3 | 1 | 1 | 1,602 |

**H3 as registered fails on this pilot.** First-pass validity does not rise from C to D: both are 0/3.

- **Why D failed first time:** every first D reply wrote the acceptance test and hook as `pytest tests/test_app.py::...`, a shell command with a selector, where the protocol names a command, `pytest` (`command.unknown`). Two of the three also filled `model.digest` with the placeholder `"..."` (`schema.format`).
- **Why repair cleared it without the model:** the compiler reduced the commands and stripped the digest, so every D spec became valid in one round with no second model call.
- **C's errors:** every C reply lacked the fields the tuple does not carry (`schema.missing`) and a model tier (`model.tier`). Two of the three gave a tool a path outside its grant (`tool.path`), because the tuple carries one path list and the same list is applied to every tool.

The 15 hand-written corpus specs were also used as first drafts for D's repair loop at seed 1:

| | Valid |
| --- | --- |
| Before repair | 4/15 |
| After compiler repair alone (as in `pilot/results.json`) | 11/15 |
| After compiler repair plus the model | 15/15 |

- **What the model added:** the four extra specs are the ones the compiler may not fix: a missing acceptance test, a context slice that escaped the workspace, an empty goal, and the four-field tuple. All but one were cleared in one round, and `empty_goal` took two.
- **Missing acceptance tests:** no D row ended with one.
- **Cost:** the corpus used 7,268 design tokens.

**The supported claim is narrower than H3.** Typed validation with bounded repair takes D from 0/3 to 3/3 valid on the fixture, and the corpus from 4/15 to 15/15. It does this at about four times C's design cost. It does not make the orchestrator's first reply valid.

## Fixture end to end

From `pilot/subagent_fixture_pinned.json`, seed 1, pinned model for both stages:

- **A:** resolved, with 0 design tokens and 1,239 subagent tokens.
- **D:** resolved, with 1,603 design tokens, 1,770 subagent tokens, and one round.

On this one task, D costs about 2.7 times A's total tokens and gains no resolution.

## History: v1 to v2

v1 ran before `pytest` joined the allowlist. With three allowed names, D was first-pass valid on 1 of 3 seeds, and its remaining errors needed a model repair round with an `allowed` hint (about 3,000 design tokens). The corpus reached 14/15.

Adding `pytest`, which SWE-bench needs, changed the prompt, because the rules and hints list the allowlist. After that change the model wrote a selector on every first reply, here and on 6 of 10 SWE-QA designs. In both v1 and v2 it repeated the selector after a hint that said to use the exact name.

The compiler rule in v2 follows from the protocol. The runtime runs named commands only, and the tests a task selects come from the task (the SWE-bench fail-to-pass list), not from the spec.

## Threats to validity

- **Sample size:** three seeds on one fixture is a pilot, not an estimate.
- **C's zero is structural:** the tuple carries no acceptance test, budgets, stop rule, verification, or return contract, so C cannot be valid under this validator. A rise from C to D would partly restate the protocol. That it does not occur in v2 is informative: D's first reply is not valid either.
- **Changes made after looking at output:** two, both disclosed in `docs/AI_USE.md`.
  - The `allowed` hint and the unchanged-reply stop were added after one fixture run, before v1.
  - The command-reduction rule was added after the v1 and SWE-QA failures, before v2.
  - Neither was tuned on v2, and v2 is reported although it fails H3.
- **Compiler credit:** in v2 the compiler, not the model, clears every fixture error. Valid-after-repair measures the protocol plus compiler, not the orchestrator alone.
- **Only one model tier:** H3 also claims the gain is largest for a 7–14B orchestrator. With one model in one tier, that part is not tested.
