#!/bin/bash
#SBATCH -A research
#SBATCH --qos=medium
#SBATCH --partition=u22
#SBATCH --constraint=2080ti
#SBATCH --gres=gpu:1
#SBATCH -c 10
#SBATCH --mem-per-cpu=2G
#SBATCH --time=04:00:00
#SBATCH --job-name=hs-swebench
#SBATCH --output=logs/%x-%j.out

# SWE-bench A/D on Ada with the pinned model on one 2080 Ti.
#   INSTANCES="astropy__astropy-12907" DESIGNERS="A D" SEEDS="1" sbatch scripts/ada/swebench.sbatch
# Leave INSTANCES empty for all ten. Rows are resumable: a resubmitted job skips
# finished ones. Checkouts and venvs live on the node's /ssd_scratch.

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
RUN=~/runs/hs-swebench-$SLURM_JOB_ID
mkdir -p "$RUN"

echo "job=$SLURM_JOB_ID node=$(hostname) start=$(date -Is) commit=$(git rev-parse --short HEAD)"
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
source scripts/ada/ollama_job.sh
start_ollama "$RUN/ollama.log"
ensure_model qwen2.5-coder:7b

ARGS=(--designers ${DESIGNERS:-A D} --seeds ${SEEDS:-1} --workdir "$WORK"
      --output pilot/swebench_results.json --ollama-host "$OLLAMA_HOST_URL")
if [ -n "${INSTANCES:-}" ]; then ARGS+=(--instances $INSTANCES); fi
$PY pilot/run_swebench.py "${ARGS[@]}"
echo "end=$(date -Is)"
