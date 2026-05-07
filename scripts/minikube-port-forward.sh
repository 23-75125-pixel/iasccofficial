#!/usr/bin/env bash
set -uo pipefail

NAMESPACE="${NAMESPACE:-face-attendance}"
SERVICE="${SERVICE:-face-attendance-service}"
LOCAL_PORT="${LOCAL_PORT:-5000}"
SERVICE_PORT="${SERVICE_PORT:-80}"

trap 'echo; echo "Stopped port-forward."; exit 0' INT TERM

echo "Opening http://localhost:${LOCAL_PORT}"
echo "Keep this terminal open. Press Ctrl+C to stop."

while true; do
  kubectl port-forward -n "${NAMESPACE}" "svc/${SERVICE}" "${LOCAL_PORT}:${SERVICE_PORT}"
  status=$?

  if [ "${status}" -eq 130 ]; then
    exit 0
  fi

  echo "Port-forward disconnected; reconnecting in 2 seconds..."
  sleep 2
done
