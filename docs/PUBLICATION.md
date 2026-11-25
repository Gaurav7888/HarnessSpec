# GitHub review edition

The public branch descends from the shared contract and includes the pre-experiment source through `f9b1664`, the prospective fixes, the verified official manifest, attribution/license, tests, aggregate preliminary results, and ACM report source. The coordinator preserves the original 11-commit branch and the local tag `sweqa-ad-seed1-v1`. The public head excludes commits containing candidate answers.

The original SHA-256 inventory covers 54 artifacts. It matched in full on the coordinator's machine at publication. The paths and digests in `pilot/snapshots/sweqa-ad-seed1-v1/SHA256SUMS` commit to their bytes. Twenty traces containing transcripts, answers and designer labels, twenty keyed energy sidecars, the finalized run rows, raw grading packet and execution log stay private. The enhanced packet, ID-bearing grade template, per-action index and per-question audit detail also stay private. Metadata for the latter derivatives is in `WITHHELD.sha256` beside the original inventory. The public metrics JSON and Markdown report aggregate observations. References to private artifacts in the research log and report describe the coordinator's checkout.

Only A produced accepted answers. Someone who has read the public aggregate results can infer the condition of an accepted answer. Recruit independent reviewers who have not seen those results, provide only the private packet, reviewer instructions and blank template, and record any prior exposure. GitHub code reviewers and blinded answer graders have different roles.

## Verify from a public checkout

~~~bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
sha256sum --ignore-missing -c pilot/snapshots/sweqa-ad-seed1-v1/SHA256SUMS
git clone https://github.com/peng-weihan/SWE-QA-Bench.git /tmp/sweqa-official
PYTHONPATH=src python3 pilot/select_sweqa.py /tmp/sweqa-official --output pilot/tmp/rebuilt-manifest.json
cmp pilot/sweqa_instances.json pilot/tmp/rebuilt-manifest.json
PYTHONPATH=src python3 pilot/run_sweqa.py --dry-run --verify-sources
~~~

The checksum command verifies only files present in the public checkout. Verifying all 54 or replaying the historical audit requires the private bundle. No reviewer should receive that bundle during blinded grading.

## Independently rerun the historical treatment

The following commands use the original v1 runner in its own checkout and write to a fresh local directory. Use Ollama 0.34.0 to match the historical pilot environment; the model pin was registered under 0.40.14. The client verifies the registered digest. Downloading archives and model weights requires network access; inference is local. No new run is represented as original evidence.

~~~bash
git worktree add --detach ../harnessspec-v1-reproduction f9b1664
cd ../harnessspec-v1-reproduction
ollama pull qwen2.5-coder:7b
PYTHONPATH=src python3 pilot/run_sweqa.py --dry-run --verify-sources
run_dir=$(mktemp -d)
PYTHONPATH=src python3 pilot/run_sweqa.py --designers A D --seeds 1 \
  --output "$run_dir/results.json" --trace-dir "$run_dir/traces" \
  --energy-dir "$run_dir/energy" --grading-packet "$run_dir/packet.json"
PYTHONPATH=src python3 pilot/metrics.py "$run_dir/results.json" \
  --diagnostics "$run_dir/traces" --sweqa-executions "$run_dir/traces" --energy "$run_dir/energy" \
  --json-output "$run_dir/metrics.json" --markdown-output "$run_dir/metrics.md"
~~~

Separate prospective runs use the public branch tip. The prospective code has offline regression coverage. Independent grades, a combined-budget experiment, B/C execution semantics, further seeds, measured caching benefits and supported energy hardware remain outstanding.
