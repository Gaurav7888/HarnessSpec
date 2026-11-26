#!/bin/bash
#SBATCH -A research
#SBATCH --qos=medium
#SBATCH --partition=u22
#SBATCH --constraint=2080ti
#SBATCH --gres=gpu:1
#SBATCH -c 10
#SBATCH --mem-per-cpu=2G
#SBATCH --time=00:45:00
#SBATCH --job-name=hs-ollama-smoke
#SBATCH --output=logs/%x-%j.out

# Smoke test: pinned Ollama on one 2080 Ti, digest check, design() and the
# fixture subagent for A and D, plus the energy probe. Results go to
# ~/runs/hs-smoke-<jobid>/.

set -euo pipefail
cd ~/code/HarnessSpec
PY=~/venvs/ai-cu121/bin/python
export PYTHONUNBUFFERED=1 OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK
RUN=~/runs/hs-smoke-$SLURM_JOB_ID
mkdir -p "$RUN"

echo "job=$SLURM_JOB_ID node=$(hostname) gpus=${CUDA_VISIBLE_DEVICES:-none} start=$(date -Is) commit=$(git rev-parse --short HEAD)"
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader

source scripts/ada/ollama_job.sh
start_ollama "$RUN/ollama.log"
ensure_model qwen2.5-coder:7b

$PY scripts/ada/smoke_ollama.py --host "$OLLAMA_HOST_URL" --out "$RUN" || echo "smoke exit $?"

echo "--- placement (expect 100% GPU)"
"$OLLAMA_BIN" ps
echo "--- energy probe"
PYTHONPATH=src $PY -m harnessspec.energy --probe-seconds 1 2>&1 | tail -20 || true
echo "end=$(date -Is)"
