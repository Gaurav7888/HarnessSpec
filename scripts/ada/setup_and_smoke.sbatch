#!/bin/bash
#SBATCH -A research
#SBATCH --qos=medium
#SBATCH --partition=u22
#SBATCH --constraint=2080ti
#SBATCH --gres=gpu:1
#SBATCH -c 10
#SBATCH --mem-per-cpu=2G
#SBATCH --time=01:00:00
#SBATCH --job-name=hs-setup-smoke
#SBATCH --output=logs/%x-%j.out
# Everything from conda-forge (fast from Ada): Ollama 0.32.15 CUDA 12.9 build and the
# SWE-bench Python versions. Then the GPU smoke test with that Ollama.
set -euo pipefail
OPT=$HOME/opt; MM=$OPT/bin/micromamba
export MAMBA_ROOT_PREFIX=$OPT/mamba
# ~/.condarc sets envs_dirs to ~/.conda/envs; micromamba follows it.
ENVS=$HOME/.conda/envs
mkdir -p $OPT/bin $MAMBA_ROOT_PREFIX
[ -x $MM ] || curl -sSL https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xj -C $OPT bin/micromamba
echo "micromamba $($MM --version)  start $(date -Is)"
mk() { local name=$1; shift
  [ -d $ENVS/$name/conda-meta ] || $MM create -y -q -n $name --override-channels -c conda-forge "$@"
  echo "env $name ready $(date +%T)"; }
mk ollama "ollama=0.32.15=cuda_129*"
for v in 3.6 3.7 3.9 3.10 3.11; do mk py${v/./} python=$v pip; done
$MM list -n ollama | grep -E "^ *(ollama|libcublas|cuda-cudart) " || true
$MM clean -y -a -q || true
du -sh $ENVS; df -h $HOME | tail -1

cd ~/code/HarnessSpec
RUN=~/runs/hs-smoke-$SLURM_JOB_ID; mkdir -p $RUN
source scripts/ada/ollama_job.sh
start_ollama "$RUN/ollama.log"
ensure_model qwen2.5-coder:7b
PY=~/venvs/ai-cu121/bin/python
$PY scripts/ada/smoke_ollama.py --host "$OLLAMA_HOST_URL" --out "$RUN" || echo "smoke exit $?"
echo "--- placement"; "$OLLAMA_BIN" ps
echo "--- energy probe"; PYTHONPATH=src $PY -m harnessspec.energy --probe-seconds 1 2>&1 | tail -8 || true
echo "end $(date -Is)"
