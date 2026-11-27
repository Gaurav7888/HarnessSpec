# GitHub review edition

The public branch descends from the shared contract and includes the pre-experiment source through `f9b1664`, the prospective fixes, the verified official manifest, attribution/license, tests, aggregate preliminary results, and ACM report source. The coordinator preserves the original 11-commit branch and the local tag `sweqa-ad-seed1-v1`. The public head excludes commits containing candidate answers.

The original SHA-256 inventory covers 54 artifacts. It matched in full on the coordinator's machine at publication. The paths and digests in `pilot/snapshots/sweqa-ad-seed1-v1/SHA256SUMS` commit to their bytes. Twenty traces containing transcripts, answers and designer labels, twenty keyed energy sidecars, the finalized run rows, raw grading packet and execution log stay private. The enhanced packet, ID-bearing grade template, per-action index and per-question audit detail also stay private. Metadata for the latter derivatives is in `WITHHELD.sha256` beside the original inventory. The public metrics JSON and Markdown report aggregate observations. References to private artifacts in the research log and report describe the coordinator's checkout.

Only A produced accepted answers. Someone who has read the public aggregate results can infer the condition of an accepted answer. Recruit independent reviewers who have not seen those results, provide only the private packet, reviewer instructions and blank template, and record any prior exposure. GitHub code reviewers and blinded answer graders have different roles.

## Verify from a public checkout

~~~bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
historical=$(mktemp -d)
git archive 25e094471905fb54cc55ad8cfbc4456598e4376b | tar -x -C "$historical"
(cd "$historical" && sha256sum --ignore-missing -c pilot/snapshots/sweqa-ad-seed1-v1/SHA256SUMS)
git clone https://github.com/peng-weihan/SWE-QA-Bench.git /tmp/sweqa-official
PYTHONPATH=src python3 pilot/select_sweqa.py /tmp/sweqa-official --output pilot/tmp/rebuilt-manifest.json
cmp pilot/sweqa_instances.json pilot/tmp/rebuilt-manifest.json
PYTHONPATH=src python3 pilot/run_sweqa.py --dry-run --verify-sources
~~~

The checksum command verifies the 11 published entries at the public release commit. The active SWE-bench manifest subsequently gained installation metadata, so its current bytes differ from the historical digest. Verifying all 54 or replaying the historical audit requires the private bundle. No reviewer should receive that bundle during blinded grading.

## Reproduce the report without inference

The final SWE-QA checkpoint covers 120 attempts. The coordinator can replay its token ledgers, source checks and paired intervals with the private experiment directory and pinned source archives. From the repository root, set `run` to that directory and `cache` to the archive cache. The replay writes only a new aggregate.

~~~bash
replay_dir=$(mktemp -d)
PYTHONPATH=src:. python3 -m pilot.sweqa_metrics --trace-dir "$run/traces" \
  --results "$run/results.json" --energy-dir "$run/energy" --archive-cache "$cache" \
  --output "$replay_dir/replay.json"
cmp "$replay_dir/replay.json" pilot/experiments/sweqa-ad-v2/abcd_seed3_metrics.json
~~~

The SWE-bench evidence is pinned to the reviewed revision of PR #1. Fetch it once, then sum each result file separately with jq. Each line below reports arm, attempts, resolved, design tokens, subagent tokens, total tokens and denials, in that order. [Runner, evaluation details and traces](https://github.com/Gaurav7888/HarnessSpec/blob/f584be43a85ad577b7439172ef1b51f197da80c1/docs/SWEBENCH.md)

~~~bash
git fetch --no-tags https://github.com/Gaurav7888/HarnessSpec.git refs/pull/1/head
rev=f584be43a85ad577b7439172ef1b51f197da80c1
for file in swebench_results.json swebench_results_v2.json; do
  echo "$file"
  git show "$rev:pilot/$file" | jq -r 'group_by(.designer)[] |
    [.[0].designer, length, (map(select(.resolved)) | length),
     (map(.design_tokens) | add), (map(.subagent_tokens) | add),
     (map(.design_tokens + .subagent_tokens) | add), (map(.tool_denials) | add)] | @tsv'
done
~~~

Build the ACM report from the repository root with Tectonic and inspect the final log and page count. Tectonic uses its cached bundle after the first download.

~~~bash
build=$(mktemp -d)
tectonic -b https://data1b.fullyjustified.net/tlextras-2022.0r0.tar \
  --keep-logs --keep-intermediates --outdir "$build" docs/final_report.tex
pdfinfo "$build/final_report.pdf"
~~~

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

The v2 protocol and aggregate results have their own experiment directory. The coordinator retains per-attempt artifacts and the blinded reviewer packet locally. The protocol records the approved budget departure and the shared execution rules for B and C. [SWE-QA v2 methods and grading](SWEQA_V2.md)
