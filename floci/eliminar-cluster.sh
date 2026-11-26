#!/usr/bin/env bash
# Elimina el clúster EKS emulado del Equipo 5 y apaga Floci.
set -uo pipefail
cd "$(dirname "$0")"
export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test
aws --endpoint-url http://localhost:4566 --region us-east-1 \
  eks delete-cluster --name voltrix-equipo5 >/dev/null
kubectl config delete-context voltrix-equipo5 >/dev/null 2>&1
docker compose -f docker-compose.yml down
echo "Clúster eliminado y Floci detenido."
