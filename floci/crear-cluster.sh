#!/usr/bin/env bash
# Voltrix Energy - Equipo 5 (Pronóstico de Generación)
# Componente A: crea el clúster EKS emulado en Floci como código (IaC).
# Versión Linux/macOS de crear-cluster.ps1 (mismos pasos).
#
# Requisitos: Docker rootful, AWS CLI v2 y kubectl.
# Uso (desde la raíz del repo):  bash floci/crear-cluster.sh
set -euo pipefail
cd "$(dirname "$0")"

CLUSTER_NAME="voltrix-equipo5"
REGION="us-east-1"
ENDPOINT="http://localhost:4566"
ROLE_NAME="voltrix-equipo5-eks-cluster-role"
USER_NAME="voltrix-equipo5-deployer"
AWS_PROFILE_NAME="floci-voltrix"

floci() { aws --endpoint-url "$ENDPOINT" --region "$REGION" "$@"; }
paso() { printf '\n==> %s\n' "$1"; }

paso "Verificando herramientas (docker, aws, kubectl)"
for cmd in docker aws kubectl; do
  command -v "$cmd" >/dev/null || { echo "Falta '$cmd'."; exit 1; }
done

export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_DEFAULT_REGION="$REGION"
unset AWS_PROFILE || true

paso "Levantando Floci (docker compose)"
docker compose -f docker-compose.yml up -d
for i in $(seq 1 30); do
  floci sts get-caller-identity >/dev/null 2>&1 && break
  [ "$i" -eq 30 ] && { echo "Floci no respondió. Revisa: docker logs voltrix-floci"; exit 1; }
  sleep 2
done

paso "Rol IAM del clúster: $ROLE_NAME"
if ! floci iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  floci iam create-role --role-name "$ROLE_NAME" \
    --assume-role-policy-document file://iam/eks-cluster-trust-policy.json >/dev/null
fi
floci iam attach-role-policy --role-name "$ROLE_NAME" \
  --policy-arn arn:aws:iam::aws:policy/AmazonEKSClusterPolicy >/dev/null 2>&1 \
  || echo "Aviso: no se pudo adjuntar AmazonEKSClusterPolicy (se continúa)."
ROLE_ARN=$(floci iam get-role --role-name "$ROLE_NAME" --query Role.Arn --output text)
echo "Rol: $ROLE_ARN"

paso "Usuario IAM de despliegue: $USER_NAME"
floci iam get-user --user-name "$USER_NAME" >/dev/null 2>&1 \
  || floci iam create-user --user-name "$USER_NAME" >/dev/null
floci iam put-user-policy --user-name "$USER_NAME" \
  --policy-name voltrix-equipo5-describe-cluster \
  --policy-document file://iam/deployer-policy.json >/dev/null
for id in $(floci iam list-access-keys --user-name "$USER_NAME" \
              --query "AccessKeyMetadata[].AccessKeyId" --output text); do
  floci iam delete-access-key --user-name "$USER_NAME" --access-key-id "$id" >/dev/null
done
read -r KEY_ID KEY_SECRET < <(floci iam create-access-key --user-name "$USER_NAME" \
  --query "AccessKey.[AccessKeyId,SecretAccessKey]" --output text)
aws configure set aws_access_key_id     "$KEY_ID"     --profile "$AWS_PROFILE_NAME"
aws configure set aws_secret_access_key "$KEY_SECRET" --profile "$AWS_PROFILE_NAME"
aws configure set region       "$REGION"   --profile "$AWS_PROFILE_NAME"
aws configure set endpoint_url "$ENDPOINT" --profile "$AWS_PROFILE_NAME"

paso "Clúster EKS: $CLUSTER_NAME"
if ! floci eks describe-cluster --name "$CLUSTER_NAME" >/dev/null 2>&1; then
  floci eks create-cluster --name "$CLUSTER_NAME" --role-arn "$ROLE_ARN" \
    --resources-vpc-config '{}' >/dev/null
else
  echo "El clúster ya existe; se reutiliza."
fi
for i in $(seq 1 60); do
  ESTADO=$(floci eks describe-cluster --name "$CLUSTER_NAME" --query cluster.status --output text)
  echo "  [$i] estado: $ESTADO"
  [ "$ESTADO" = "ACTIVE" ] && break
  [ "$ESTADO" = "FAILED" ] && { echo "El clúster quedó en FAILED."; exit 1; }
  [ "$i" -eq 60 ] && { echo "El clúster no llegó a ACTIVE a tiempo."; exit 1; }
  sleep 5
done

paso "Configurando kubectl (contexto $CLUSTER_NAME)"
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$REGION" \
  --profile "$AWS_PROFILE_NAME" --alias "$CLUSTER_NAME"

paso "Verificación con kubectl"
kubectl --context "$CLUSTER_NAME" wait --for=condition=Ready node --all --timeout=180s
kubectl --context "$CLUSTER_NAME" get nodes -o wide
kubectl --context "$CLUSTER_NAME" cluster-info
echo; echo "Clúster '$CLUSTER_NAME' listo en Floci."
