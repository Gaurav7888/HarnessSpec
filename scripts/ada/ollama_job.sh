#!/bin/bash
# Start Ollama inside a SLURM job, then run a command against it.
#
#   source scripts/ada/ollama_job.sh
#   start_ollama "$RUN/ollama.log"     # refuses to continue on CPU
#   ensure_model qwen2.5-coder:7b
#
# Ollama on Ada is the conda-forge CUDA 12.9 build (0.32.15) in ~/.conda/envs/ollama.
# The official 0.40.14 release's cuda_v13 needs a newer driver than Ada's (580), and
# GitHub release downloads do not reach Ada. The model, its digest, and the request
# options are the pinned ones (pilot/model.json).
#
# The server listens on 127.0.0.1 only, on a port derived from the job ID so two
# jobs on one node do not collide. It is killed when the job script exits.
# OLLAMA_HOST_URL is exported for the command.

set -euo pipefail

OLLAMA_ENV=${OLLAMA_ENV:-$HOME/.conda/envs/ollama}
OLLAMA_BIN=${OLLAMA_BIN:-$OLLAMA_ENV/bin/ollama}
export LD_LIBRARY_PATH=$OLLAMA_ENV/lib:${LD_LIBRARY_PATH:-}
export OLLAMA_MODELS=${OLLAMA_MODELS:-$HOME/ollama-models}
PORT=$((20000 + ${SLURM_JOB_ID:-0} % 20000))
export OLLAMA_HOST=127.0.0.1:$PORT
export OLLAMA_HOST_URL=http://127.0.0.1:$PORT
# Keep the model on the GPU between calls for the whole job.
export OLLAMA_KEEP_ALIVE=-1

start_ollama() {
  local log=$1
  "$OLLAMA_BIN" serve > "$log" 2>&1 &
  OLLAMA_PID=$!
  trap 'kill $OLLAMA_PID 2>/dev/null || true' EXIT
  for _ in $(seq 90); do
    if curl -sf "$OLLAMA_HOST_URL/api/version" > /dev/null; then
      echo "ollama $(curl -s "$OLLAMA_HOST_URL/api/version") on $OLLAMA_HOST_URL"
      local compute
      compute=$(grep -m1 "inference compute" "$log" || true)
      echo "$compute"
      # A CPU fallback runs a 7B call in minutes, not seconds; stop rather than waste the job.
      if ! grep -q "library=CUDA" <<< "$compute"; then
        echo "ollama did not find a CUDA GPU; refusing to run on CPU (see $log)" >&2
        return 1
      fi
      return 0
    fi
    sleep 2
  done
  echo "ollama did not start; see $log" >&2
  return 1
}

ensure_model() {
  local name=$1
  if ! "$OLLAMA_BIN" list | awk '{print $1}' | grep -qx "$name"; then
    echo "pulling $name into $OLLAMA_MODELS"
    "$OLLAMA_BIN" pull "$name"
  fi
}
