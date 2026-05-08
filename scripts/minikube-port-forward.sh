#!/usr/bin/env bash
set -uo pipefail

NAMESPACE="${NAMESPACE:-face-attendance}"
SERVICE="${SERVICE:-face-attendance-service}"
DEPLOYMENT="${DEPLOYMENT:-face-attendance-web}"
LOCAL_PORT="${LOCAL_PORT:-5000}"
SERVICE_PORT="${SERVICE_PORT:-80}"

trap 'echo; echo "Stopped port-forward."; exit 0' INT TERM

echo "Opening http://localhost:${LOCAL_PORT}"
echo "Keep this terminal open. Press Ctrl+C to stop."

wait_for_ready_service() {
  kubectl get deployment "${DEPLOYMENT}" -n "${NAMESPACE}" >/dev/null || return 1

  echo "Waiting for deployment/${DEPLOYMENT} to become ready..."
  kubectl rollout status "deployment/${DEPLOYMENT}" -n "${NAMESPACE}" --timeout=180s || return 1

  echo "Waiting for service/${SERVICE} endpoints..."
  until [ -n "$(kubectl get endpoints "${SERVICE}" -n "${NAMESPACE}" -o jsonpath='{.subsets[*].addresses[*].ip}' 2>/dev/null)" ]; do
    sleep 2
  done
}

while true; do
  wait_for_ready_service
  status=$?
  if [ "${status}" -ne 0 ]; then
    echo "Service is not ready; retrying in 5 seconds..."
    sleep 5
    continue
  fi

  kubectl port-forward --address 127.0.0.1 -n "${NAMESPACE}" "svc/${SERVICE}" "${LOCAL_PORT}:${SERVICE_PORT}"
  status=$?

  if [ "${status}" -eq 130 ]; then
    exit 0
  fi

  echo "Port-forward disconnected; reconnecting in 2 seconds..."
  sleep 2
done
