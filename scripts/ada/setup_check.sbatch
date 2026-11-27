#!/bin/bash
#SBATCH -A research
#SBATCH --qos=medium
#SBATCH --partition=u22
#SBATCH -c 2
#SBATCH --mem=6G
#SBATCH --time=01:00:00
#SBATCH --array=0-9
#SBATCH --job-name=hs-setupcheck
#SBATCH --output=logs/%x-%A_%a.out

# CPU only, no model: install each SWE-bench instance and run its fail_to_pass
# tests once at the base commit. One array task per instance.
#   sbatch scripts/ada/setup_check.sbatch            # all ten
#   sbatch --array=0,3 scripts/ada/setup_check.sbatch

set -euo pipefail
cd ~/code/HarnessSpec
PY=~/venvs/ai-cu121/bin/python
export PYTHONUNBUFFERED=1
ENVS=$HOME/.conda/envs
PYBIN=$HOME/opt/pybin
mkdir -p "$PYBIN"
for v in 3.6 3.7 3.9 3.10 3.11; do ln -sfn "$ENVS/py${v/./}/bin/python$v" "$PYBIN/python$v"; done
export PATH=$PYBIN:$PATH
export PIP_CACHE_DIR=/ssd_scratch/$USER/pip-cache PIP_DISABLE_PIP_VERSION_CHECK=1
ID=$($PY -c "import json,sys; print(json.load(open('pilot/swebench_instances.json'))['instances'][int(sys.argv[1])]['instance_id'])" "$SLURM_ARRAY_TASK_ID")
echo "task=$SLURM_ARRAY_TASK_ID instance=$ID node=$(hostname) start=$(date -Is)"
$PY scripts/ada/setup_check.py "$ID" "/ssd_scratch/$USER/setupcheck" "$HOME/runs/setupcheck"
echo "end=$(date -Is)"
