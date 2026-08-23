#!/usr/bin/env bash
# Ollama sidecar entrypoint: start the server, pull the models DocuBrowse needs
# (idempotent — skipped if already present), then hand PID 1 to the server.
set -euo pipefail

MODELS=("nomic-embed-text" "dolphin3")

ollama serve &
serve_pid=$!

# Wait for the API to answer before pulling.
until ollama list >/dev/null 2>&1; do
  sleep 1
done

for m in "${MODELS[@]}"; do
  if ollama list | awk '{print $1}' | grep -q "^${m}"; then
    echo "ollama: ${m} already present"
  else
    echo "ollama: pulling ${m}..."
    ollama pull "${m}"
  fi
done

echo "ollama: sidecar ready"
# ponytail: bash forwards SIGTERM to serve via `wait`; fine for a sidecar.
# If clean fast shutdown matters, add a trap that kills $serve_pid.
wait "${serve_pid}"
