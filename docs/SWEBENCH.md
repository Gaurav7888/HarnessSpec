# SWE-bench pilot (H1): designers A and D, seed 1

Ten SWE-bench Verified instances (`pilot/swebench_instances.json`) were run on the IIIT Ada cluster on 2026-11-27 with the pinned model on one RTX 2080 Ti per instance.

- **v1** is the registered comparison: `pilot/swebench_results.json`, with traces in `pilot/swebench/`.
- **v2** is a labelled extension: the same runs with the repository summary the proposal names as a design input. It is in `pilot/swebench_results_v2.json` and `pilot/swebench_v2/`.

Every row validates against `pilot/result.schema.json`.

## Result

| Seed 1, 10 instances | Resolved | Design tokens | Subagent tokens | Total tokens | Tool denials | Silent handoffs | Hook failures |
|---|---|---:|---:|---:|---:|---:|---:|
| A | 0/10 | 0 | 2,124,595 | 2,124,595 | 58 | 3 | 0 |
| D, v1 (registered) | 0/10 | 21,312 | 996,820 | 1,018,132 | 209 | 0 | 1 |
| D, v2 (+ repository summary) | 0/10 | 28,652 | 1,333,946 | 1,362,598 | 32 | 0 | 4 |

A in v2 matches v1 to within sampling (2,124,100 subagent tokens). A makes no design call, so the summary cannot reach it.

**H1 in v1.** Neither designer resolves an instance, so D does not trail A by more than 5 points and is non-inferior on resolution. D uses 1,018,132 tokens against A's 2,124,595, including its 21,312 design tokens.

**Read with care.** Both rates are 0, so the non-inferiority is uninformative about quality. D's lower token count comes from failing early, not from solving more cheaply. The failure analysis below explains how.

## Per instance

| Instance | A tokens | A denials | D v1 tokens (design + subagent) | D v1 denials | D v2 tokens | D v2 denials |
|---|---:|---:|---:|---:|---:|---:|
| astropy__astropy-12907 | 365,641 | 8 | 1,890 + 210,383 | 1 | 2,532 + 771 | 1 |
| matplotlib__matplotlib-13989 | 73,583 | 23 | 1,983 + 55,020 | 30 | 3,219 + 106,307 | 0 |
| mwaskom__seaborn-3069 | 404,577 | 0 | 1,857 + 125,964 | 28 | 2,654 + 6,938 | 1 |
| pallets__flask-5014 | 258,459 | 6 | 1,552 + 45,930 | 30 | 2,080 + 35,194 | 0 |
| psf__requests-1142 | 109,621 | 1 | 1,583 + 53,325 | 30 | 1,835 + 371,711 | 0 |
| pydata__xarray-2905 | 378,307 | 0 | 2,268 + 56,067 | 30 | 2,759 + 409,185 | 0 |
| pylint-dev__pylint-4551 | 76,575 | 15 | 3,921 + 446 | 0 | 5,013 + 1,843 | 0 |
| pytest-dev__pytest-10051 | 435,144 | 0 | 1,975 + 337,275 | 0 | 2,808 + 337,485 | 0 |
| scikit-learn__scikit-learn-10297 | 15,559 | 2 | 1,943 + 55,635 | 30 | 2,738 + 55,635 | 30 |
| sphinx-doc__sphinx-10323 | 7,129 | 3 | 2,340 + 56,775 | 30 | 3,014 + 8,877 | 0 |

## Why each designer fails

**D, v1.** `design()` sees the issue text and the parent card but not the repository, so it names paths that do not exist: `requests.py` (the code is in `requests/`), and `sklearn/linear_model.py` (the code is in `sklearn/linear_model/`). It often drops `list_dir`, so its subagent cannot look around. On six instances the subagent repeated a read of a nonexistent file until all 30 steps were refused. Dinesh's audit found the same failure on SWE-QA.

**D, v2.** With the repository summary (tracked paths to depth two), denials fall from 209 to 32. Of the eight instances with denials in v1, five have none in v2, and astropy and seaborn have one each.

- **Still failing on scikit-learn.** The model chose `sklearn/linear_model.py` again although the summary lists `sklearn/linear_model/`. Its design prompt grew from 1,564 to 2,333 tokens, so the summary was present, and the model did not use it.
- **Resolution is unchanged.** The subagent now reads real files, but resolution stays 0/10.

**A.** A gets every tool on the card. It mostly reads files 200 lines at a time and lists directories until its 30 steps run out. It wrote files only on flask (four writes) and scikit-learn (one), and neither fixed the tests.

**Both.** This is what one would expect of a 7B model whose only edit tool replaces a whole file and that has 30 steps on repository-scale code.

## Protocol

- **Model.** `qwen2.5-coder:7b`, the pinned digest, with `num_ctx` 16384 and temperature 0.2. The run used seed 1.
  - **Server:** Ollama 0.32.15 from conda-forge, CUDA 12.9 build, with 100% of the model on the GPU and about 0.6 s per call.
  - **Why not the pinned 0.40.14:** its CUDA 13 libraries need a newer driver than Ada's 580, and GitHub release downloads do not reach Ada.
  - **Digest:** Ollama 0.32 reports the manifest's SHA-256 (`4aaba1ee…`). Its config layer is the pinned `dae161e2…`, and the manifest files are byte-identical on the pinning Mac and on Ada. `llm.py` accepts exactly that one equivalent.
- **Environments.** SWE-bench 2.1.0's specs (read from the published package) supply the Python versions, which come from conda-forge.
  - **Pre-installs.** The pip commands include SWE-bench's pre-installs:
    - astropy: setuptools pinned in `pyproject.toml`;
    - flask and pylint: their requirements files;
    - scikit-learn: pip 21.3.1, pytest and `cython<3`.
  - **Setup check.** Before any model run, a CPU-only check (`scripts/ada/setup_check.sbatch`) installed every instance and confirmed its fail-to-pass tests are collected and fail at the base commit.
- **Evaluation.** `resolved` means the instance's FAIL_TO_PASS tests pass after the run, as the plan defines it. PASS_TO_PASS is not run.
  - **Test patch.** Each test run resets the patched test files to the base commit, applies SWE-bench Verified's `test_patch`, runs the tests, and restores the subagent's files byte for byte, so the subagent never sees the gold tests in its checkout.
  - **Truncated IDs.** Two pylint IDs are stored truncated in the dataset (`test_get_annotation_annassign[a:`), so that test file runs whole.
- **Budgets.** The card allows read, list and write on the checkout, with 30 steps, 8,000 generated tokens and 900 s.
  - **What is counted.** The step budget charges generated tokens. `subagent_tokens` is the server's prompt plus output count, as on SWE-QA.
  - **Reply cap.** Each reply is capped at the 8,000-token budget (Ollama `num_predict`). The largest reply in any recorded run is 2,001 tokens, so the cap changes none.
- **Failures that are not results.** A failed install or a model call that times out writes no row (`*_setup_failed.json` or `*_model_error.json`) and is retried. Only the matplotlib D attempt in v2 needed a retry, after one call hung past the client timeout.

## What changed after looking at output

All of these changes are disclosed in `docs/AI_USE.md`. None was tuned on v1 or v2 results.

1. **v0, discarded and kept in `pilot/swebench_v0/`.** The shared subagent prompt showed the fixture's `src/app.py` in every example.
   - D's subagent sent `{"kind":"read_file","path":"src/app.py"}` 30 times and was told only `unknown action unparsed`.
   - A answered in prose and returned without editing.

   The prompt now builds its examples from the spec's own grants, states the job (edit files, then return), and answers a malformed action with the accepted shapes. Malformed actions are still refused and counted.
2. **Runner fixes before v1:**
   - test-patch evaluation;
   - the SWE-bench pre-installs;
   - `git clean` between designers;
   - re-cloning a partial checkout.
3. **v2** adds only the repository summary, and only when `--repo-summary` is passed. Without it every prompt is byte-identical, so H3 and SWE-QA are unaffected.

## Limits

- **Scale:** one seed and ten instances, against roughly 60 instances and three seeds in the registered plan.
- **Evaluation:** resolution uses FAIL_TO_PASS only, with no PASS_TO_PASS check.
- **Server version:** the server differs from the pin; the weights and the request options are the same.
- **Matplotlib build:** its tests ran with a newer FreeType than it expects, which matters only for image-comparison tests.
- **Energy:** not measured for these runs.

## Reproduce (Ada)

```bash
sbatch scripts/ada/setup_and_smoke.sbatch           # conda-forge Ollama + Pythons, GPU check, fixture smoke
sbatch scripts/ada/setup_check.sbatch               # CPU: install all ten, fail_to_pass fails at base
sbatch scripts/ada/swebench.sbatch                  # v1: A and D, seed 1, one GPU task per instance
VARIANT=v2 sbatch --export=ALL scripts/ada/swebench.sbatch
python scripts/ada/merge_swebench.py v1 && python scripts/ada/merge_swebench.py v2
```
