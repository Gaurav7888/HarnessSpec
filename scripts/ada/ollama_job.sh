#!/bin/bash
# Start the pinned Ollama server inside a SLURM job, then run a command against it.
#
#   sbatch scripts/ada/smoke.sbatch            # uses this file
#
# The server listens on 127.0.0.1 only, on a port derived from the job ID so two
# jobs on one node do not collide. It is killed when the job script exits.
# OLLAMA_HOST_URL is exported for the command.

set -euo pipefail

OLLAMA_BIN=${OLLAMA_BIN:-$HOME/opt/ollama-0.40.14/bin/ollama}
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
