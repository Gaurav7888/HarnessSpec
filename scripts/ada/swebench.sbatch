#!/bin/bash
#SBATCH -A research
#SBATCH --qos=medium
#SBATCH --partition=u22
#SBATCH --constraint=2080ti
#SBATCH --gres=gpu:1
#SBATCH -c 10
#SBATCH --mem-per-cpu=2G
#SBATCH --time=02:00:00
#SBATCH --array=0-9%4
#SBATCH --job-name=hs-swebench
#SBATCH --output=logs/%x-%A_%a.out

# SWE-bench on Ada with the pinned model: one array task per instance, one 2080 Ti
# each, at most 4 at once (the QoS GPU limit).
#   sbatch scripts/ada/swebench.sbatch                       # all ten, A and D, seed 1
#   DESIGNERS="B C" SEEDS="1 2 3" sbatch --array=0,4 scripts/ada/swebench.sbatch
#   VARIANT=v2 sbatch --export=ALL scripts/ada/swebench.sbatch   # with the repository summary
# Each instance writes pilot/swebench/<instance>.json (and _traces/), so tasks never
# share a file; scripts/ada/merge_swebench.py builds pilot/swebench_results.json.
# Rows are resumable: a resubmitted task skips finished ones. A setup failure
# writes no row. Checkouts and venvs live on the node's /ssd_scratch.

set -euo pipefail
cd ~/code/HarnessSpec
PY=~/venvs/ai-cu121/bin/python
export PYTHONUNBUFFERED=1 PYTHONPATH=src
ENVS=$HOME/.conda/envs

# Only the versioned names (python3.6 ... python3.11) go on PATH, so plain
# python3 stays the system one. The runner picks the instance's version.
PYBIN=$HOME/opt/pybin
mkdir -p "$PYBIN"
for v in 3.6 3.7 3.9 3.10 3.11; do ln -sfn "$ENVS/py${v/./}/bin/python$v" "$PYBIN/python$v"; done
export PATH=$PYBIN:$PATH

WORK=/ssd_scratch/$USER/swebench
mkdir -p "$WORK"
export PIP_CACHE_DIR=/ssd_scratch/$USER/pip-cache PIP_DISABLE_PIP_VERSION_CHECK=1
ID=$($PY -c "import json,sys; print(json.load(open('pilot/swebench_instances.json'))['instances'][int(sys.argv[1])]['instance_id'])" "$SLURM_ARRAY_TASK_ID")
RUN=~/runs/hs-swebench-${SLURM_ARRAY_JOB_ID}_$SLURM_ARRAY_TASK_ID
mkdir -p "$RUN"

echo "job=$SLURM_JOB_ID instance=$ID node=$(hostname) start=$(date -Is) commit=$(git rev-parse --short HEAD)"
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
source scripts/ada/ollama_job.sh
start_ollama "$RUN/ollama.log"
ensure_model qwen2.5-coder:7b

# VARIANT=v2 gives the designer the registered repository summary and writes to pilot/swebench_v2/.
OUT=pilot/swebench; EXTRA=()
if [ "${VARIANT:-v1}" = "v2" ]; then OUT=pilot/swebench_v2; EXTRA=(--repo-summary); fi
mkdir -p "$OUT"
$PY pilot/run_swebench.py --designers ${DESIGNERS:-A D} --seeds ${SEEDS:-1} --instances "$ID" \
    --workdir "$WORK" --output "$OUT/$ID.json" --ollama-host "$OLLAMA_HOST_URL" "${EXTRA[@]}"
echo "end=$(date -Is)"
